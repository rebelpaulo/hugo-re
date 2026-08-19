"""Adaptador SIP: liga o FreeSWITCH ao `SlotManager` por Event Socket (ESL).

Mesma forma que `adapters/web_adapter.py` (ver `bridge/README.md`) mas do
lado dos telefones físicos: descolgar -> `connect()`+`offhook`, DTMF ->
`handle_event(press_N)`, desligar -> `hungup`+`disconnect()`. Não sabe nada
de WebSocket nem de HTTP — só fala o protocolo de texto do ESL, por socket
puro (`asyncio.open_connection`, biblioteca padrão).

Porquê sem `python-ESL` (o binding oficial): não vem do PyPI, tem de ser
compilado a partir do código-fonte do FreeSWITCH instalado — mais uma peça
móvel duvidosa para uma máquina de evento. O protocolo em si é simples
(cabeçalhos tipo HTTP + `Content-Length`, ver `_read_frame`), e pedimos os
eventos em `event json` precisamente para não ter de escrever também um
parser da forma "plain" (url-encoded). Ver `bridge/freeswitch/README.md`
para o resto da configuração (perfil, dialplan, contexto).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from slot_manager import Decision, SlotManager


LOGGER = logging.getLogger("bridge.sip_adapter")

DEFAULT_ESL_HOST = "127.0.0.1"
DEFAULT_ESL_PORT = 8021
DEFAULT_ESL_PASSWORD = "ClueCon"  # password de origem do event_socket.conf.xml
DEFAULT_CONTEXT = "hugo-lan"

# Eventos que nos interessam — a chamada é atendida e estacionada
# (`dialplan/hugo-lan.xml`), nada mais lhe acontece até ao desligar.
SUBSCRIBED_EVENTS = "CHANNEL_ANSWER CHANNEL_HANGUP_COMPLETE DTMF"

RECONNECT_BACKOFF_INITIAL_SECONDS = 1.0
RECONNECT_BACKOFF_MAX_SECONDS = 30.0

KEY_TO_EVENT = {str(digit): f"press_{digit}" for digit in range(10)}
KEY_TO_EVENT["*"] = "press_star"
KEY_TO_EVENT["#"] = "press_pound"

Connector = Callable[[str, int], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]
Router = Callable[[list[Decision]], Awaitable[None]]


class ESLProtocolError(Exception):
    """A ligação ESL respondeu de forma que não sabemos interpretar."""


@dataclass
class _ActiveCall:
    source_id: str
    destination_number: str


async def _read_frame(reader: asyncio.StreamReader) -> tuple[dict[str, str], bytes]:
    """Lê uma mensagem ESL: cabeçalhos `Chave: valor` até à linha em
    branco, seguidos de `Content-Length` bytes de corpo, se o cabeçalho
    existir. Usado tanto para respostas a comandos como para eventos."""
    headers: dict[str, str] = {}
    while True:
        line = await reader.readline()
        if not line:
            raise ConnectionError("ligação ESL fechada a meio de um cabeçalho")
        text = line.decode("utf-8", errors="replace").rstrip("\r\n")
        if text == "":
            break
        key, sep, value = text.partition(":")
        if sep:
            headers[key.strip()] = value.strip()
    body = b""
    length = headers.get("Content-Length")
    if length is not None:
        body = await reader.readexactly(int(length))
    return headers, body


async def _send(writer: asyncio.StreamWriter, command: str) -> None:
    writer.write(f"{command}\n\n".encode("utf-8"))
    await writer.drain()


class SipAdapter:
    """Liga-se ao ESL do FreeSWITCH, subscreve os eventos da chamada, e
    encaminha-os para o `SlotManager` — o equivalente SIP do `WebBridge`
    em `web_adapter.py`. Uma instância corre `run()` num único `asyncio.Task`
    (ver `main.py`) durante toda a vida do bridge; reconecta sozinha."""

    def __init__(
        self,
        manager: SlotManager,
        route: Router,
        *,
        host: str = DEFAULT_ESL_HOST,
        port: int = DEFAULT_ESL_PORT,
        password: str = DEFAULT_ESL_PASSWORD,
        context: str = DEFAULT_CONTEXT,
        backoff_initial: float = RECONNECT_BACKOFF_INITIAL_SECONDS,
        backoff_max: float = RECONNECT_BACKOFF_MAX_SECONDS,
        connector: Connector = asyncio.open_connection,
    ) -> None:
        self.manager = manager
        self.route = route
        self.host = host
        self.port = port
        self.password = password
        self.context = context
        self.backoff_initial = backoff_initial
        self.backoff_max = backoff_max
        self._connector = connector

        self._calls: dict[str, _ActiveCall] = {}  # uuid da chamada -> sessão
        self._active_source_ids: set[str] = set()
        self._stop_event = asyncio.Event()
        self._writer: asyncio.StreamWriter | None = None

    async def run(self) -> None:
        """Corre até `stop()`: liga, autentica, subscreve, lê eventos para
        sempre. Uma queda da ligação (rede, FreeSWITCH reiniciado, ESL em
        baixo) não propaga — regista, espera com backoff exponencial
        (1s, 2s, 4s... até 30s, a repetir), e tenta outra vez. É isto que
        garante que um ESL que caia a meio do evento e volte não deixa os
        telefones "mortos em silêncio" para sempre; só os deixa surdos
        durante o tempo da reconexão, e resincroniza ao voltar (`_reconcile`)."""
        backoff = self.backoff_initial
        while not self._stop_event.is_set():
            try:
                await self._connect_and_serve()
                backoff = self.backoff_initial  # desligou por stop(), não por falha
            except (OSError, ConnectionError, asyncio.IncompleteReadError) as exc:
                # stop() fecha o writer para desbloquear a leitura, o que
                # também levanta uma destas — desligar de propósito não é
                # falha nenhuma, não vale um aviso a assustar quem lê o log.
                if self._stop_event.is_set():
                    break
                LOGGER.warning("ESL caiu (%s) — nova tentativa em %.1fs", exc, backoff)
            except ESLProtocolError as exc:
                if self._stop_event.is_set():
                    break
                LOGGER.error("ESL respondeu de forma inesperada (%s) — nova tentativa em %.1fs", exc, backoff)
            except Exception:
                if self._stop_event.is_set():
                    break
                LOGGER.exception("Erro inesperado no adaptador SIP — nova tentativa em %.1fs", backoff)
            else:
                continue
            await self._sleep_or_stop(backoff)
            backoff = min(backoff * 2, self.backoff_max)

    async def stop(self) -> None:
        """Pára `run()` de forma limpa — chamado no desligar do bridge.

        Antes de largar o ESL, desliga as chamadas em curso. Sem isto os
        telefones ficavam fora do gancho e mudos: quem estivesse ao telefone
        quando a produção passa para os telemóveis não ouvia nada e não tinha
        forma de perceber que a chamada já não conta. Com o `hupall` o
        auscultador ganha o tom de ocupado, que toda a gente sabe ler.
        """
        self._stop_event.set()
        if self._writer is not None:
            with contextlib.suppress(Exception):
                await _send(self._writer, "api hupall normal_clearing")
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()

    async def _sleep_or_stop(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _connect_and_serve(self) -> None:
        reader, writer = await self._connector(self.host, self.port)
        self._writer = writer
        try:
            await self._auth(reader, writer)
            await self._subscribe(reader, writer)
            LOGGER.info("ESL ligado a %s:%d", self.host, self.port)
            await self._reconcile(reader, writer)
            while not self._stop_event.is_set():
                headers, body = await _read_frame(reader)
                await self._handle_frame(headers, body)
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            if self._writer is writer:
                self._writer = None

    async def _auth(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        headers, _ = await _read_frame(reader)
        if headers.get("Content-Type") != "auth/request":
            raise ESLProtocolError(f"esperava auth/request no cumprimento, veio {headers!r}")
        await _send(writer, f"auth {self.password}")
        headers, _ = await _read_frame(reader)
        if not headers.get("Reply-Text", "").startswith("+OK"):
            raise ESLProtocolError(f"autenticação ESL rejeitada: {headers.get('Reply-Text')!r}")

    async def _subscribe(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _send(writer, f"event json {SUBSCRIBED_EVENTS}")
        headers, _ = await _read_frame(reader)
        if not headers.get("Reply-Text", "").startswith("+OK"):
            raise ESLProtocolError(f"subscrição de eventos rejeitada: {headers.get('Reply-Text')!r}")

    async def _reconcile(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Chamado logo a seguir a (re)ligar: pergunta ao FreeSWITCH o que
        está mesmo em curso (`show channels`) e alinha o nosso estado com
        isso. Sem isto, uma queda do ESL a meio do evento deixava dois
        tipos de fantasma: uma chamada que atendeu e nós nunca soubemos
        (o `CHANNEL_ANSWER` passou-nos ao lado, o telefone fica sem slot),
        ou o inverso, uma chamada que já desligou mas continuamos a achar
        activa (o slot fica preso, o próximo telefone não entra) — exactamente
        o "telefones morrem em silêncio" que isto tem de evitar."""
        await _send(writer, "api show channels as json")
        headers, body = await _read_frame(reader)
        if headers.get("Content-Type") != "api/response" or not body:
            return
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            LOGGER.warning("'show channels as json' devolveu um corpo não-JSON — a saltar reconciliação")
            return

        live_uuids: set[str] = set()
        for row in payload.get("rows") or []:
            if row.get("context") != self.context:
                continue
            uuid = row.get("uuid")
            if not uuid:
                continue
            live_uuids.add(uuid)
            if uuid not in self._calls and row.get("callstate") == "ACTIVE":
                destination = row.get("dest") or uuid
                await self._start_call(uuid, destination)

        for uuid in [u for u in self._calls if u not in live_uuids]:
            await self._end_call(uuid)

    async def _handle_frame(self, headers: dict[str, str], body: bytes) -> None:
        if headers.get("Content-Type") != "text/event-json":
            return  # resposta a um comando avulso (ex.: a própria reconciliação) — nada nosso aqui
        try:
            event = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            LOGGER.warning("evento ESL com corpo não-JSON: %r", body[:200])
            return

        name = event.get("Event-Name")
        uuid = event.get("Unique-ID")
        if not uuid:
            return

        if name == "CHANNEL_ANSWER":
            destination = event.get("Caller-Destination-Number") or uuid
            await self._start_call(uuid, destination)
        elif name == "DTMF":
            await self._on_dtmf(uuid, event.get("DTMF-Digit"))
        elif name == "CHANNEL_HANGUP_COMPLETE":
            await self._end_call(uuid)

    def _make_source_id(self, destination: str, uuid: str) -> str:
        """`sip:<extensão marcada>` — identifica o telefone pelo destino da
        chamada, não pelo caller ID (que em chamada IP directa não é de
        fiar: pode vir vazio ou igual em todos os telefones). Estável
        enquanto cada telefone físico marcar sempre o mesmo alvo (ver
        `bridge/freeswitch/README.md`). Só junta o UUID da chamada a seguir
        a ":" se dois telefones marcarem o mesmo destino ao mesmo tempo
        (configuração errada) — para nunca perder uma linha em silêncio por
        colisão de nome; ver bridge/README.md."""
        candidate = f"sip:{destination}"
        if candidate not in self._active_source_ids:
            return candidate
        return f"sip:{destination}:{uuid[:8]}"

    async def _start_call(self, uuid: str, destination: str) -> None:
        if uuid in self._calls:
            return  # ANSWER repetido (re-INVITE) ou já reconstruído por _reconcile — nada a fazer
        source_id = self._make_source_id(destination, uuid)
        self._calls[uuid] = _ActiveCall(source_id=source_id, destination_number=destination)
        self._active_source_ids.add(source_id)
        decisions = self.manager.connect(source_id, "sip")
        # connect() já pede lugar sozinho (chama _request_slot internamente);
        # esta chamada extra é sempre um no-op depois de connect() ter corrido
        # (o estado da sessão já não é "idle"), mantida por segurança/simetria
        # com o resto do adaptador.
        decisions += self.manager.request_slot(source_id)
        decisions += self.manager.handle_event(source_id, "offhook")
        await self.route(decisions)

    async def _on_dtmf(self, uuid: str, digit: str | None) -> None:
        call = self._calls.get(uuid)
        if call is None:
            return  # DTMF de uma chamada que não vimos atender — ordem de eventos rara, ignora
        game_event = KEY_TO_EVENT.get(digit or "")
        if game_event is None:
            LOGGER.debug("DTMF desconhecido %r na chamada %s", digit, uuid)
            return
        await self.route(self.manager.handle_event(call.source_id, game_event))

    async def _end_call(self, uuid: str) -> None:
        call = self._calls.pop(uuid, None)
        if call is None:
            return
        self._active_source_ids.discard(call.source_id)
        decisions = self.manager.handle_event(call.source_id, "hungup")
        decisions += self.manager.disconnect(call.source_id)
        await self.route(decisions)
