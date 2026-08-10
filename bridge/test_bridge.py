"""Testes corríveis sem framework: .venv/bin/python bridge/test_bridge.py"""

from __future__ import annotations

import json
import logging
import socket
from pathlib import Path

from emitter import UdpEmitter
from slot_manager import Decision, QueueStatus, SlotManager


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


class NonClosingDatagramSender:
    """Adapta um socketpair à assinatura sendto usada pelo emissor."""

    def __init__(self, sender: socket.socket) -> None:
        self.sender = sender

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        pass

    def sendto(self, data: bytes, _address: tuple[str, int]) -> int:
        return self.sender.send(data)

def make_manager() -> tuple[SlotManager, FakeClock, FakeEmitter]:
    clock = FakeClock()
    emitter = FakeEmitter()
    return SlotManager(emitter, clock=clock), clock, emitter


def find(decisions: list[Decision], kind: str, source_id: str) -> Decision:
    return next(
        decision
        for decision in decisions
        if decision.kind == kind and decision.source_id == source_id
    )


def fill(manager: SlotManager) -> None:
    for index in range(4):
        decisions = manager.connect(f"web-{index}", "web")
        assert find(decisions, "assigned", f"web-{index}").player == index


def test_capacity_and_fifo_position() -> None:
    manager, _, _ = make_manager()
    fill(manager)
    decisions = manager.connect("web-4", "web")
    status = find(decisions, "queue_status", "web-4")
    assert manager.occupied == [0, 1, 2, 3]
    assert (status.position, status.ahead) == (1, 0)
    assert manager.queue_status("web-4") == QueueStatus(position=1, ahead=0)


def test_release_offers_first_in_queue() -> None:
    manager, _, _ = make_manager()
    fill(manager)
    manager.connect("web-4", "web")
    decisions = manager.disconnect("web-0")
    offer = find(decisions, "offer", "web-4")
    assert offer.player == 0
    assert manager.player_for("web-4") is None
    confirmed = manager.confirm("web-4")
    assert find(confirmed, "assigned", "web-4").player == 0
    assert manager.player_for("web-4") == 0


def test_confirmation_timeout_rotates() -> None:
    manager, clock, _ = make_manager()
    fill(manager)
    manager.connect("web-4", "web")
    manager.connect("web-5", "web")
    offered = manager.disconnect("web-0")
    assert find(offered, "offer", "web-4").deadline == clock() + 15
    clock.advance(15)
    decisions = manager.tick()
    assert find(decisions, "offer_expired", "web-4").player == 0
    assert find(decisions, "offer", "web-5").player == 0
    confirmed = manager.confirm("web-5")
    assert find(confirmed, "assigned", "web-5").player == 0
    assert manager.player_for("web-4") is None


def test_inactivity_timeout_releases_slot() -> None:
    manager, clock, emitter = make_manager()
    manager.connect("web-0", "web")
    clock.advance(119.999)
    assert not any(decision.kind == "released" for decision in manager.tick())
    clock.advance(0.001)
    decisions = manager.tick()
    released = find(decisions, "released", "web-0")
    assert released.reason == "inactivity_timeout"
    assert manager.occupied == []
    assert emitter.slot_states[-1] == ([], 0)
    # P0: sem hungup explícito, a ausência dele nunca chegava ao jogo — o
    # quadrante ficava preso a meio da partida anterior (ver slot_manager.py,
    # _release_active). inactivity_timeout tem de repor sozinho.
    assert emitter.events == [(0, "hungup")]


# ---------------------------------------------------------------------------
# P0: qualquer libertação que não venha de um `hungup` explícito (disconnect,
# inactivity_timeout, ou o novo release_player do fim de partida) tem de
# repor o quadrante mandando `hungup` sintético ao jogo — e esse sintético
# não pode ser engolido pela deduplicação de 60ms nem envenenar a janela do
# próximo jogador a ocupar o mesmo lugar.
# ---------------------------------------------------------------------------


def test_disconnect_without_hungup_sends_synthetic_hungup() -> None:
    manager, _, emitter = make_manager()
    manager.connect("web-0", "web")
    manager.handle_event("web-0", "offhook")
    assert emitter.events == [(0, "offhook")]

    # Página fechada à bruta: nunca chega um {"type":"hangup"} da webapp.
    decisions = manager.disconnect("web-0")
    released = find(decisions, "released", "web-0")
    assert released.reason == "disconnected"
    assert emitter.events == [(0, "offhook"), (0, "hungup")], emitter.events


def test_explicit_hungup_is_not_duplicated() -> None:
    """O caminho que já manda `hungup` (handle_event, linha ~246) não pode
    voltar a mandá-lo ao libertar — só um `hungup` por partida."""
    manager, _, emitter = make_manager()
    manager.connect("web-0", "web")
    decisions = manager.handle_event("web-0", "hungup")
    assert find(decisions, "forwarded", "web-0").event == "hungup"
    assert find(decisions, "released", "web-0").reason == "hungup"
    assert emitter.events == [(0, "hungup")], emitter.events


def test_synthetic_hungup_bypasses_dedup_and_does_not_poison_next_player() -> None:
    """O sintético não pode ser engolido pela janela de 60ms, nem deixar lá
    um registo que engula o `hungup` real do próximo jogador a ocupar o
    mesmo lugar, mandado poucos milissegundos depois."""
    manager, clock, emitter = make_manager()
    manager.connect("web-0", "web")
    manager.disconnect("web-0")
    assert emitter.events == [(0, "hungup")]

    clock.advance(0.030)  # dentro da janela de dedup de 60ms
    manager.connect("web-1", "web")  # apanha o lugar 0, agora livre
    assert manager.player_for("web-1") == 0

    decisions = manager.handle_event("web-1", "hungup")
    forwarded = find(decisions, "forwarded", "web-1")
    assert forwarded.player == 0
    assert emitter.events == [(0, "hungup"), (0, "hungup")], emitter.events


def test_release_player_by_index_resets_quadrant() -> None:
    """`release_player`, usado pela deteção de fim de partida no
    AudioRouter (só conhece o jogador, não o source_id)."""
    manager, _, emitter = make_manager()
    fill(manager)
    manager.connect("web-4", "web")

    decisions = manager.release_player(2)
    released = find(decisions, "released", "web-2")
    assert released.reason == "match_ended"
    assert manager.occupied == [0, 1, 3]
    assert emitter.events == [(2, "hungup")]
    # o lugar 2 fica livre e disponível — quem estava na fila é oferecido.
    assert find(decisions, "offer", "web-4").player == 2

    # jogador sem ninguém no lugar: no-op silencioso, sem excepção.
    assert manager.release_player(2) == []


def test_event_dedup_window() -> None:
    manager, clock, emitter = make_manager()
    manager.connect("web-0", "web")
    first = manager.handle_event("web-0", "press_5")
    clock.advance(0.030)
    duplicate = manager.handle_event("web-0", "press_5")
    clock.advance(0.070)
    accepted = manager.handle_event("web-0", "press_5")
    assert find(first, "forwarded", "web-0").player == 0
    assert find(duplicate, "ignored", "web-0").reason == "duplicate"
    assert find(accepted, "forwarded", "web-0").player == 0
    assert emitter.events == [(0, "press_5"), (0, "press_5")]


def test_sip_waiter_has_priority_over_web_queue() -> None:
    manager, _, _ = make_manager()
    fill(manager)
    manager.connect("web-4", "web")
    waiting = manager.connect("sip-0", "sip")
    assert find(waiting, "waiting", "sip-0")
    decisions = manager.disconnect("web-0")
    assert find(decisions, "assigned", "sip-0").player == 0
    assert manager.player_for("sip-0") == 0
    assert manager.queue_status("web-4").position == 1
    assert not any(decision.kind == "offer" for decision in decisions)


def test_sip_never_preempts() -> None:
    manager, _, _ = make_manager()
    fill(manager)
    before = manager.occupied.copy()
    decisions = manager.connect("sip-0", "sip")
    assert find(decisions, "waiting", "sip-0")
    assert manager.occupied == before == [0, 1, 2, 3]
    assert [manager.player_for(f"web-{index}") for index in range(4)] == [0, 1, 2, 3]


def test_hungup_disconnect_and_end_match() -> None:
    manager, _, emitter = make_manager()
    manager.connect("sip-0", "sip")
    decisions = manager.handle_event("sip-0", "hungup")
    assert find(decisions, "forwarded", "sip-0")
    assert find(decisions, "released", "sip-0").reason == "hungup"
    assert emitter.events == [(0, "hungup")]

    manager.request_slot("sip-0")
    manager.connect("web-0", "web")
    ended = manager.end_match()
    assert len([decision for decision in ended if decision.kind == "match_ended"]) == 2
    assert manager.occupied == []


def test_config_loading() -> None:
    config_path = Path(__file__).with_name("config.yaml")
    emitter = UdpEmitter.from_config(config_path)
    manager = SlotManager.from_config(config_path, FakeEmitter(), clock=FakeClock())
    assert (emitter.host, emitter.port) == ("127.0.0.1", 9100)
    assert manager.slot_count == 4
    assert manager.inactivity_timeout == 120
    assert manager.offer_timeout == 15
    assert manager.dedup_window == 0.060
    assert manager.sip_preempt is False


def test_emitter_end_to_end() -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender = None
    mode = "UDP/IP"
    try:
        listener.bind(("127.0.0.1", 0))
        host, port = listener.getsockname()
        emitter = UdpEmitter(host, port)
    except PermissionError:
        listener.close()
        sender, listener = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        adapter = NonClosingDatagramSender(sender)
        emitter = UdpEmitter(socket_factory=lambda *_args: adapter)
        mode = "datagrama local (sandbox sem bind UDP/IP)"
    listener.settimeout(1)
    try:
        assert emitter.send_event(2, "press_5") is True
        event = json.loads(listener.recvfrom(4096)[0])
        assert event == {"player": 2, "event": "press_5"}

        assert emitter.send_slots([2, 0], 5) is True
        slots = json.loads(listener.recvfrom(4096)[0])
        assert slots == {"type": "slots", "occupied": [0, 2], "queue_len": 5}
        print(f"EMITTER transporte: {mode}")
        print(f"EMITTER event recebido: {json.dumps(event, separators=(',', ':'))}")
        print(f"EMITTER slots recebido: {json.dumps(slots, separators=(',', ':'))}")
    finally:
        listener.close()
        if sender is not None:
            sender.close()


def test_emitter_failure_is_contained() -> None:
    logging.disable(logging.CRITICAL)
    try:
        emitter = UdpEmitter("nome de host inválido", 9100)
        assert emitter.send_event(0, "press_0") is False
        assert emitter.send_event(99, "press_0") is False
        assert emitter.send_event(0, "evento_inventado") is False
        assert emitter.send_event(0, []) is False
        assert emitter.send_slots(None, 0) is False
        assert emitter.send_slots([0], -1) is False
    finally:
        logging.disable(logging.NOTSET)


TESTS = [
    test_capacity_and_fifo_position,
    test_release_offers_first_in_queue,
    test_confirmation_timeout_rotates,
    test_inactivity_timeout_releases_slot,
    test_disconnect_without_hungup_sends_synthetic_hungup,
    test_explicit_hungup_is_not_duplicated,
    test_synthetic_hungup_bypasses_dedup_and_does_not_poison_next_player,
    test_release_player_by_index_resets_quadrant,
    test_event_dedup_window,
    test_sip_waiter_has_priority_over_web_queue,
    test_sip_never_preempts,
    test_hungup_disconnect_and_end_match,
    test_config_loading,
    test_emitter_end_to_end,
    test_emitter_failure_is_contained,
]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print(f"OK {test.__name__}")
    print(f"OK {len(TESTS)} testes")
