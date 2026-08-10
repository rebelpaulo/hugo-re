"""Testes corríveis sem framework: .venv/bin/python bridge/test_sip_adapter.py

Fala ESL a sério por socket (asyncio, `127.0.0.1`, porta efémera) com um
`FakeEslServer` local que implementa o mesmo protocolo de texto que o
FreeSWITCH — cumprimento, `auth`, `event json`, `api show channels as
json` — e deixa o teste empurrar eventos como se viessem de uma chamada
real. Isto exercita o `SipAdapter` de verdade (o parser de frames ESL, a
tradução para o `SlotManager`, a reconexão): só o extremo de rede é falso,
tal como `test_web_adapter.py` usa um aiohttp a sério com um socket UDP
local a fazer de "jogo".

A prova de uma chamada real com um softphone (baresip) está fora deste
ficheiro — precisa do FreeSWITCH instalado e a correr, o que não é dado
adquirido em qualquer máquina que corra os testes (ver bridge/README.md,
secção SIP, para essa prova em separado).
"""

from __future__ import annotations

import asyncio
import json

from adapters.sip_adapter import SipAdapter
from slot_manager import SlotManager


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[int, str]] = []
        self.slot_states: list[tuple[list[int], int]] = []

    def send_event(self, player: int, event: str) -> bool:
        self.events.append((player, event))
        return True

    def send_slots(self, occupied: list[int], queue_len: int) -> bool:
        self.slot_states.append((occupied.copy(), queue_len))
        return True


def make_manager() -> tuple[SlotManager, FakeClock, FakeEmitter]:
    clock = FakeClock()
    emitter = FakeEmitter()
    return SlotManager(emitter, clock=clock), clock, emitter


async def _read_command(reader: asyncio.StreamReader) -> str:
    """Lê um comando ESL do cliente: linhas até uma em branco, devolve a
    primeira (os comandos que o `SipAdapter` manda cabem numa linha só)."""
    lines: list[str] = []
    while True:
        line = await reader.readline()
        if not line:
            raise ConnectionError("eof")
        text = line.decode("utf-8", "replace").rstrip("\r\n")
        if text == "":
            break
        lines.append(text)
    return lines[0] if lines else ""


class FakeEslServer:
    """Do lado do FreeSWITCH: cumprimento -> auth -> subscrição -> resposta
    à reconciliação (`show channels`) -> fica à escuta de mais nada, à
    espera que o teste empurre eventos com `push_event`. Um `writer` por
    ligação; `connection_count` sobe a cada nova ligação aceite, o que serve
    de prova de reconexão."""

    def __init__(self, password: str = "ClueCon") -> None:
        self.password = password
        self._server: asyncio.base_events.Server | None = None
        self.port = 0
        self.connection_count = 0
        self._ready_events: list[asyncio.Event] = []
        self._writer: asyncio.StreamWriter | None = None
        self.show_channels_rows: list[dict] = []
        self.fail_first_n_connections = 0

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def wait_ready(self, index: int) -> None:
        """Espera a ligação nº `index` (1 = primeira) completar o
        handshake+reconciliação."""
        while len(self._ready_events) < index:
            await asyncio.sleep(0.005)
        await self._ready_events[index - 1].wait()

    async def push_event(self, event: dict) -> None:
        assert self._writer is not None, "sem ligação activa para empurrar o evento"
        body = json.dumps(event).encode("utf-8")
        frame = (
            f"Content-Type: text/event-json\nContent-Length: {len(body)}\n\n".encode("utf-8")
            + body
        )
        self._writer.write(frame)
        await self._writer.drain()

    async def drop_connection(self) -> None:
        assert self._writer is not None
        self._writer.close()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self.fail_first_n_connections > 0:
            self.fail_first_n_connections -= 1
            writer.close()
            return

        self.connection_count += 1
        ready = asyncio.Event()
        self._ready_events.append(ready)
        self._writer = writer
        try:
            writer.write(b"Content-Type: auth/request\n\n")
            await writer.drain()

            cmd = await _read_command(reader)
            assert cmd == f"auth {self.password}", cmd
            writer.write(b"Content-Type: command/reply\nReply-Text: +OK accepted\n\n")
            await writer.drain()

            cmd = await _read_command(reader)
            assert cmd.startswith("event json"), cmd
            writer.write(b"Content-Type: command/reply\nReply-Text: +OK event listener enabled json\n\n")
            await writer.drain()

            cmd = await _read_command(reader)
            assert cmd == "api show channels as json", cmd
            payload = json.dumps(
                {"row_count": len(self.show_channels_rows), "rows": self.show_channels_rows}
            ).encode("utf-8")
            writer.write(
                f"Content-Type: api/response\nContent-Length: {len(payload)}\n\n".encode("utf-8")
                + payload
            )
            await writer.drain()

            ready.set()
            await reader.read()  # fica vivo até a ligação fechar (drop_connection ou stop())
        except (ConnectionError, asyncio.IncompleteReadError, AssertionError):
            pass
        finally:
            if self._writer is writer:
                self._writer = None


async def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"condição não satisfeita em {timeout}s")


class Harness:
    """Junta servidor falso + adaptador + `SlotManager`, com o `route()` a
    acumular as `Decision` recebidas (o mesmo papel do `WebBridge.route`,
    ver `web_adapter.py`)."""

    def __init__(self) -> None:
        self.server = FakeEslServer()
        self.manager, self.clock, self.emitter = make_manager()
        self.routed: list = []
        self.adapter: SipAdapter | None = None
        self.task: asyncio.Task | None = None

    async def start(self, **adapter_kwargs) -> None:
        await self.server.start()

        async def route(decisions):
            self.routed.extend(decisions)

        self.adapter = SipAdapter(
            self.manager,
            route,
            host="127.0.0.1",
            port=self.server.port,
            backoff_initial=0.01,
            backoff_max=0.05,
            **adapter_kwargs,
        )
        self.task = asyncio.create_task(self.adapter.run())
        await self.server.wait_ready(1)

    async def stop(self) -> None:
        assert self.adapter is not None and self.task is not None
        await self.adapter.stop()
        await asyncio.wait_for(self.task, timeout=2.0)
        await self.server.stop()


async def test_answer_forwards_connect_and_offhook_by_destination() -> None:
    """Uma chamada atendida entra no `SlotManager` pelo NÚMERO MARCADO, não
    pelo caller ID (aqui deliberadamente diferente e sem qualquer relação),
    fica com um slot, e o `offhook` chega ao "jogo"."""
    h = Harness()
    await h.start()
    try:
        await h.server.push_event(
            {
                "Event-Name": "CHANNEL_ANSWER",
                "Unique-ID": "uuid-1",
                "Caller-Destination-Number": "9001",
                "Caller-Caller-ID-Number": "Anonymous",
            }
        )
        await _wait_until(lambda: h.manager.player_for("sip:9001") is not None)
        assert h.manager.player_for("sip:9001") == 0
        assert (0, "offhook") in h.emitter.events, h.emitter.events
        assigned = [d for d in h.routed if d.kind == "assigned"]
        assert assigned and assigned[0].source_id == "sip:9001", h.routed
    finally:
        await h.stop()


async def test_destination_collision_gets_distinct_source_ids() -> None:
    """Duas chamadas ao mesmo destino ao mesmo tempo (configuração errada
    dos telefones) não perdem a segunda em silêncio — ganham identidades
    distintas e slots distintos."""
    h = Harness()
    await h.start()
    try:
        await h.server.push_event(
            {"Event-Name": "CHANNEL_ANSWER", "Unique-ID": "uuid-a", "Caller-Destination-Number": "9001"}
        )
        await h.server.push_event(
            {"Event-Name": "CHANNEL_ANSWER", "Unique-ID": "uuid-b", "Caller-Destination-Number": "9001"}
        )
        await _wait_until(lambda: len(h.manager.occupied) == 2)
        assert h.manager.player_for("sip:9001") is not None
        assert h.manager.player_for("sip:9001:uuid-b") is not None
    finally:
        await h.stop()


async def test_dtmf_maps_to_press_event() -> None:
    h = Harness()
    await h.start()
    try:
        await h.server.push_event(
            {"Event-Name": "CHANNEL_ANSWER", "Unique-ID": "uuid-1", "Caller-Destination-Number": "9001"}
        )
        await _wait_until(lambda: h.manager.player_for("sip:9001") is not None)
        await h.server.push_event({"Event-Name": "DTMF", "Unique-ID": "uuid-1", "DTMF-Digit": "5"})
        await _wait_until(lambda: (0, "press_5") in h.emitter.events)

        await h.server.push_event({"Event-Name": "DTMF", "Unique-ID": "uuid-1", "DTMF-Digit": "*"})
        await _wait_until(lambda: (0, "press_star") in h.emitter.events)
    finally:
        await h.stop()


async def test_dtmf_dedup_30ms_collapses_100ms_does_not() -> None:
    """Mesma janela de deduplicação do `SlotManager` (60ms por omissão),
    exercitada pelo caminho a sério do adaptador: dois DTMF iguais a 30ms
    de intervalo contam como um; a 100ms contam como dois. Duas chamadas
    diferentes, uma por cenário, para não misturar os relógios."""
    h = Harness()
    await h.start()
    try:
        await h.server.push_event(
            {"Event-Name": "CHANNEL_ANSWER", "Unique-ID": "uuid-a", "Caller-Destination-Number": "9001"}
        )
        await h.server.push_event(
            {"Event-Name": "CHANNEL_ANSWER", "Unique-ID": "uuid-b", "Caller-Destination-Number": "9002"}
        )
        await _wait_until(lambda: len(h.manager.occupied) == 2)
        player_a = h.manager.player_for("sip:9001")
        player_b = h.manager.player_for("sip:9002")

        # Cenário 1: 30ms de intervalo — o SEGUNDO fica de fora (duplicado).
        await h.server.push_event({"Event-Name": "DTMF", "Unique-ID": "uuid-a", "DTMF-Digit": "5"})
        await _wait_until(lambda: (player_a, "press_5") in h.emitter.events)
        h.clock.advance(0.030)
        await h.server.push_event({"Event-Name": "DTMF", "Unique-ID": "uuid-a", "DTMF-Digit": "5"})
        await asyncio.sleep(0.05)  # dá tempo ao adaptador processar (e não haver mais nada a chegar)
        assert h.emitter.events.count((player_a, "press_5")) == 1, h.emitter.events

        # Cenário 2: 100ms de intervalo — os DOIS contam.
        await h.server.push_event({"Event-Name": "DTMF", "Unique-ID": "uuid-b", "DTMF-Digit": "5"})
        await _wait_until(lambda: (player_b, "press_5") in h.emitter.events)
        h.clock.advance(0.100)
        await h.server.push_event({"Event-Name": "DTMF", "Unique-ID": "uuid-b", "DTMF-Digit": "5"})
        await _wait_until(lambda: h.emitter.events.count((player_b, "press_5")) == 2)
    finally:
        await h.stop()


async def test_hangup_releases_slot_and_disconnects() -> None:
    h = Harness()
    await h.start()
    try:
        await h.server.push_event(
            {"Event-Name": "CHANNEL_ANSWER", "Unique-ID": "uuid-1", "Caller-Destination-Number": "9001"}
        )
        await _wait_until(lambda: h.manager.player_for("sip:9001") is not None)
        await h.server.push_event({"Event-Name": "CHANNEL_HANGUP_COMPLETE", "Unique-ID": "uuid-1"})
        await _wait_until(lambda: h.manager.occupied == [])
        assert (0, "hungup") in h.emitter.events, h.emitter.events
        disconnected = [d for d in h.routed if d.kind == "disconnected"]
        assert disconnected and disconnected[-1].source_id == "sip:9001", h.routed
    finally:
        await h.stop()


async def test_reconnect_with_backoff_and_reconciliation() -> None:
    """Prova de reconexão: a ligação ESL cai a meio de uma chamada activa;
    o adaptador reconecta sozinho (com backoff), e a reconciliação
    (`show channels`) sincroniza os dois lados nos dois sentidos:

    - `sip:9001` estava activa e já não aparece no FreeSWITCH ao voltar
      (desligou às escuras) -> liberta o slot sozinho, sem ficar preso.
    - `sip:9002` aparece activa no FreeSWITCH mas o adaptador nunca viu o
      `CHANNEL_ANSWER` (chegou e foi atendida enquanto o ESL estava em
      baixo) -> entra no `SlotManager` mesmo assim, sem esperar por outro
      evento que nunca mais vem.

    Isto é o que evita "telefones mortos em silêncio" (ver bridge/README.md).
    """
    h = Harness()
    await h.start()
    try:
        await h.server.push_event(
            {"Event-Name": "CHANNEL_ANSWER", "Unique-ID": "uuid-1", "Caller-Destination-Number": "9001"}
        )
        await _wait_until(lambda: h.manager.player_for("sip:9001") is not None)

        # Ao reconectar, o FreeSWITCH já não sabe de uuid-1 (desligou às
        # escuras) mas sabe de uma chamada nova, uuid-2/9002, já activa.
        h.server.show_channels_rows = [
            {
                "uuid": "uuid-2",
                "context": "hugo-lan",
                "dest": "9002",
                "callstate": "ACTIVE",
            }
        ]
        await h.server.drop_connection()
        await h.server.wait_ready(2)
        assert h.server.connection_count == 2, "não reconectou"

        await _wait_until(lambda: h.manager.player_for("sip:9001") is None)
        await _wait_until(lambda: h.manager.player_for("sip:9002") is not None)
        hungup_decisions = [d for d in h.routed if d.kind == "released" and d.source_id == "sip:9001"]
        assert hungup_decisions, h.routed
    finally:
        await h.stop()


TESTS = [
    test_answer_forwards_connect_and_offhook_by_destination,
    test_destination_collision_gets_distinct_source_ids,
    test_dtmf_maps_to_press_event,
    test_dtmf_dedup_30ms_collapses_100ms_does_not,
    test_hangup_releases_slot_and_disconnects,
    test_reconnect_with_backoff_and_reconciliation,
]


def main() -> None:
    for test in TESTS:
        asyncio.run(test())
        print(f"OK {test.__name__}")
    print(f"OK {len(TESTS)} testes")


if __name__ == "__main__":
    main()
