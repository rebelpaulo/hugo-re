"""Router de áudio do bridge.

Escuta nas mesmas portas UDP onde `game/audio_helper.py` já fala (uma por
jogador), responde-lhe imediatamente como o `audio-server` faria, e em vez de
tocar o som no Mac encaminha-o para a sessão WebSocket daquele jogador.

Contrato UDP com o jogo (fixo, não mexer — ver `game/audio_helper.py` e
`audio-server/audio_server.py`):

    PLAY -> {"cmd":"PLAY","resource":"...","loops":0,"volume":1.0}
            resposta: {"instance_id": N}
    STOP -> {"cmd":"STOP","instance_id":N,"duration":ms}
            resposta: {"success": true, "instance_id": N}

ARMADILHA que isto existe para evitar: `game/audio_helper.py:24` faz
`settimeout(1.0)` e espera resposta no fio principal do jogo. Por isso este
router responde sempre — mesmo sem sessão ligada para aquele jogador, mesmo
com o `audio-server` local em baixo no modo "pa" — nunca deixa o pedido sem
resposta.

Mensagem enviada à webapp (novo tipo `audio`, acrescentado ao protocolo
WebSocket existente sem o alterar — ver `bridge/adapters/web_adapter.py`):

    {"type":"audio","action":"play","resource":"...","loops":0,"id":N}
    {"type":"audio","action":"stop","id":N}

Deteção de fim de partida: o jogo é one-way por desenho e nunca fala com o
bridge, mas toca um som próprio (`you_lost.wav`, o apresentador a
despedir-se) uma única vez, exactamente ao entrar no estado de fim de jogo
(ver `game/tv_show/ending.py` + `game/tv_show/in_cave.py:19`). Um `PLAY` cujo
`resource` esteja em `ending_resources` (derivado do código do jogo, nunca
escrito à mão — ver `_tv_show_ending_resources` em
`adapters/web_adapter.py`) dispara `on_match_ended(player)`, que liberta o
lugar e avisa a sessão — ver `bridge/README.md`.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import socket
from typing import Awaitable, Callable, Optional

LOGGER = logging.getLogger("bridge.audio_router")

# player:int, mensagem:dict -> True se entregue a uma sessão ligada.
Dispatch = Callable[[int, dict], Awaitable[bool]]


class _PortEndpoint(asyncio.DatagramProtocol):
    """Um protocolo por porta/jogador — o jogo já assume uma porta por quadrante."""

    def __init__(self, router: "AudioRouter", player: int) -> None:
        self.router = router
        self.player = player
        self.transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr) -> None:
        assert self.transport is not None
        self.router._handle_datagram(self.player, data, addr, self.transport)

    def error_received(self, exc: Exception) -> None:
        LOGGER.warning("Erro UDP no jogador %d: %s", self.player, exc)


class _PaClient:
    """Cliente UDP bloqueante para o `audio-server` local — mesma forma do
    `UDPAudioClient` em `game/audio_helper.py`. Corre sempre num thread do
    executor (`run_in_executor`) para nunca bloquear o loop de eventos."""

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.addr = (host, port)
        self.timeout = timeout

    def request(self, payload: bytes) -> Optional[bytes]:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(self.timeout)
            sock.sendto(payload, self.addr)
            data, _ = sock.recvfrom(4096)
            return data
        except socket.timeout:
            return None
        except OSError as exc:
            LOGGER.warning("Falha a falar com o audio-server em %s: %s", self.addr, exc)
            return None
        finally:
            sock.close()


class AudioRouter:
    """Escuta em `ports[i]` como o áudio do jogador `i`.

    modo "devices" (default): encaminha PLAY/STOP para a sessão WebSocket do
    jogador via `dispatch`; sem sessão ligada não é erro, só descarta.

    modo "pa": interruptor de recurso — reencaminha tudo, transparente, para o
    `audio-server` local (colunas do Mac). É o que salva o evento se os
    altifalantes dos telemóveis não chegarem no dia.
    """

    def __init__(
        self,
        ports: list[int],
        dispatch: Dispatch,
        *,
        mode: str = "devices",
        pa_host: str = "127.0.0.1",
        pa_ports: list[int] | None = None,
        pa_timeout: float = 0.4,
        host: str = "0.0.0.0",
        ending_resources: frozenset[str] = frozenset(),
        on_match_ended: Optional[Callable[[int], Awaitable[None]]] = None,
    ) -> None:
        if mode not in ("devices", "pa"):
            raise ValueError(f"modo de áudio desconhecido: {mode!r}")
        if mode == "pa" and (not pa_ports or len(pa_ports) < len(ports)):
            raise ValueError("modo 'pa' precisa de uma pa_port por jogador")

        self.ports = ports
        self.dispatch = dispatch
        self.mode = mode
        self.host = host
        self.pa_timeout = pa_timeout
        # Fim de partida: o jogo é one-way por desenho (nunca fala com o
        # bridge — ver bridge/README.md), mas toca `you_lost.wav` (o
        # apresentador a despedir-se) uma única vez, exactamente ao entrar
        # em `tv_show/ending.py` (ver `game/tv_show/in_cave.py:19`, só
        # alcançado quando `cave.ended`). `ending_resources` vem já
        # derivado do código do jogo por quem instancia o router (ver
        # `_tv_show_ending_resources` em `adapters/web_adapter.py`) — nunca
        # escrito à mão aqui. Vazio = detecção desligada.
        self.ending_resources = ending_resources
        self.on_match_ended = on_match_ended
        self._pa_clients = (
            [_PaClient(pa_host, port, pa_timeout) for port in (pa_ports or [])]
            if mode == "pa"
            else []
        )
        self._next_id = itertools.count(1)
        self._transports: list[asyncio.DatagramTransport] = []

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        for player, port in enumerate(self.ports):
            try:
                transport, _protocol = await loop.create_datagram_endpoint(
                    lambda player=player: _PortEndpoint(self, player),
                    local_addr=(self.host, port),
                )
            except OSError as erro:
                # Quase de certeza é o audio-server clássico a ocupar a mesma
                # porta. Em modo "devices" é o bridge que fala com o jogo, e os
                # dois não podem coexistir. Um traceback em bruto às 21h não
                # ajuda ninguém — diz-se o que fazer.
                await self.stop()
                raise RuntimeError(
                    f"Não consegui escutar em {self.host}:{port} ({erro}).\n"
                    f"  Com audio.mode: {self.mode!r} é o bridge que recebe o áudio do\n"
                    f"  jogo nas portas {self.ports}. O audio-server clássico usa as\n"
                    f"  mesmas e não podem correr ao mesmo tempo.\n"
                    f"  Ou fechas o audio-server (pkill -f '[a]udio_server\\.py'),\n"
                    f"  ou mudas audio.mode para 'pa' no bridge/config.yaml se quiseres\n"
                    f"  o som a sair pelas colunas em vez dos telemóveis."
                ) from erro
            self._transports.append(transport)
        LOGGER.info(
            "AudioRouter a escutar em %s (jogadores 0..%d), modo=%s",
            self.ports,
            len(self.ports) - 1,
            self.mode,
        )

    async def stop(self) -> None:
        for transport in self._transports:
            transport.close()
        self._transports.clear()

    # ------------------------------------------------------------------
    # Receção UDP — corre síncrono dentro do loop, tem de ser rápido e nunca
    # deixar o jogo sem resposta.
    # ------------------------------------------------------------------
    def _handle_datagram(self, player: int, data: bytes, addr, transport) -> None:
        try:
            cmd = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            LOGGER.debug("Pacote UDP ilegível do jogador %d", player)
            return
        if not isinstance(cmd, dict):
            return

        # Deteção de fim de partida: independente do modo (`devices`/`pa`) —
        # o som ainda dá sinal do fim mesmo quando sai pelas colunas do Mac
        # em vez do telemóvel. Em modo "pa" não há mensagem de áudio para
        # entregar por WebSocket primeiro, por isso corre logo à parte; em
        # modo "devices" entra depois na mesma tarefa que a entrega do PLAY
        # (ver `_dispatch_then_maybe_end_match` abaixo) — a ordem importa.
        resource = cmd.get("resource")
        is_ending = cmd.get("cmd") == "PLAY" and resource in self.ending_resources

        if self.mode == "pa":
            asyncio.ensure_future(self._proxy_to_pa(player, data, addr, transport, cmd))
            if is_ending:
                asyncio.ensure_future(self._safe_match_ended(player))
            return

        cmd_type = cmd.get("cmd")
        if cmd_type == "PLAY":
            instance_id = next(self._next_id)
            transport.sendto(json.dumps({"instance_id": instance_id}).encode("utf-8"), addr)
            message = {
                "type": "audio",
                "action": "play",
                "resource": resource,
                "loops": cmd.get("loops", 0),
                "id": instance_id,
            }
            asyncio.ensure_future(
                self._dispatch_then_maybe_end_match(player, message, is_ending)
            )
        elif cmd_type == "STOP":
            instance_id = cmd.get("instance_id")
            transport.sendto(
                json.dumps({"success": True, "instance_id": instance_id}).encode("utf-8"), addr
            )
            message = {"type": "audio", "action": "stop", "id": instance_id}
            asyncio.ensure_future(self._safe_dispatch(player, message))
        else:
            transport.sendto(
                json.dumps({"error": f"Unknown command: {cmd_type}"}).encode("utf-8"), addr
            )

    async def _safe_dispatch(self, player: int, message: dict) -> None:
        try:
            await self.dispatch(player, message)
        except Exception:  # uma falha de entrega nunca pode derrubar o router
            LOGGER.exception("Falha a encaminhar %s para o jogador %d", message, player)

    async def _safe_match_ended(self, player: int) -> None:
        if self.on_match_ended is None:
            return
        try:
            await self.on_match_ended(player)
        except Exception:  # idem — nunca pode derrubar o router
            LOGGER.exception("Falha a processar fim de partida do jogador %d", player)

    async def _dispatch_then_maybe_end_match(
        self, player: int, message: dict, is_ending: bool
    ) -> None:
        """Entrega primeiro a mensagem de áudio, só depois trata o fim de
        partida — nesta ordem, nunca ao contrário.

        Libertar o lugar limpa `SlotManager._slots[player]`, que é
        exactamente o que `dispatch_audio` (`adapters/web_adapter.py`) usa
        para encontrar a sessão do jogador. Se a ordem fosse invertida, o
        próprio som de fim de partida (`you_lost.wav`) arriscava nunca
        chegar ao telemóvel — o jogador ficaria sem ouvir a despedida."""
        await self._safe_dispatch(player, message)
        if is_ending:
            await self._safe_match_ended(player)

    # ------------------------------------------------------------------
    # Modo "pa": proxy transparente para o audio-server local.
    # ------------------------------------------------------------------
    async def _proxy_to_pa(self, player: int, data: bytes, addr, transport, cmd: dict) -> None:
        loop = asyncio.get_running_loop()
        client = self._pa_clients[player]
        response = await loop.run_in_executor(None, client.request, data)
        if response is None:
            response = self._pa_fallback(cmd)
        transport.sendto(response, addr)

    @staticmethod
    def _pa_fallback(cmd: dict) -> bytes:
        """O audio-server local não respondeu a tempo — não deixamos o jogo bloquear por isso."""
        if cmd.get("cmd") == "PLAY":
            payload = {"error": "audio-server local sem resposta"}
        else:
            payload = {"success": False, "instance_id": cmd.get("instance_id")}
        return json.dumps(payload).encode("utf-8")
