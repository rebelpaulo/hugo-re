"""Gestão independente de slots, fila web e espera SIP."""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Protocol

import yaml


LOGGER = logging.getLogger(__name__)

SourceType = Literal["web", "sip"]
VALID_EVENTS = frozenset(
    {"offhook", "hungup", "press_star", "press_pound"}
    | {f"press_{digit}" for digit in range(10)}
)


class Emitter(Protocol):
    def send_event(self, player: int, event: str) -> bool: ...

    def send_slots(self, occupied: list[int], queue_len: int) -> bool: ...


@dataclass(frozen=True)
class Decision:
    """Resultado que um adaptador B2/B3 deve encaminhar para a sua sessão."""

    kind: str
    source_id: str | None = None
    source_type: SourceType | None = None
    player: int | None = None
    position: int | None = None
    ahead: int | None = None
    deadline: float | None = None
    event: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class QueueStatus:
    position: int
    ahead: int


@dataclass
class _Session:
    source_id: str
    source_type: SourceType
    state: Literal["idle", "active", "queued", "offered", "waiting"] = "idle"
    player: int | None = None
    last_activity: float | None = None


@dataclass(frozen=True)
class _Offer:
    source_id: str
    player: int
    deadline: float


class SlotManager:
    """Atribui slots sem conhecer transportes HTTP, WebSocket, SIP ou ARI."""

    def __init__(
        self,
        emitter: Emitter,
        *,
        slot_count: int = 4,
        inactivity_timeout: float = 120.0,
        offer_timeout: float = 15.0,
        dedup_window: float = 0.060,
        sip_preempt: bool = False,
        clock: Callable[[], float] = time.monotonic,
        on_decision: Callable[[Decision], None] | None = None,
    ) -> None:
        if not 1 <= slot_count <= 4:
            raise ValueError("slot_count tem de estar entre 1 e 4")
        if inactivity_timeout <= 0 or offer_timeout <= 0 or dedup_window < 0:
            raise ValueError("os timeouts têm de ser positivos")
        if sip_preempt:
            raise ValueError("sip_preempt=true não é suportado por este contrato")

        self.emitter = emitter
        self.slot_count = slot_count
        self.inactivity_timeout = inactivity_timeout
        self.offer_timeout = offer_timeout
        self.dedup_window = dedup_window
        self.sip_preempt = sip_preempt
        self.clock = clock
        self.on_decision = on_decision

        self._slots: list[str | None] = [None] * slot_count
        self._sessions: dict[str, _Session] = {}
        self._web_queue: deque[str] = deque()
        self._sip_waiting: deque[str] = deque()
        self._offers: dict[str, _Offer] = {}
        self._reserved_slots: dict[int, str] = {}
        self._last_events: dict[tuple[int, str], float] = {}

    @classmethod
    def from_config(
        cls,
        path: str | Path,
        emitter: Emitter,
        *,
        clock: Callable[[], float] = time.monotonic,
        on_decision: Callable[[Decision], None] | None = None,
    ) -> "SlotManager":
        """Cria o gestor a partir da secção ``bridge`` do YAML."""
        with Path(path).open(encoding="utf-8") as config_file:
            config = yaml.safe_load(config_file) or {}
        bridge = config.get("bridge") or {}
        return cls(
            emitter,
            slot_count=int(bridge.get("slots", 4)),
            inactivity_timeout=float(bridge.get("inactivity_timeout_seconds", 120)),
            offer_timeout=float(bridge.get("offer_timeout_seconds", 15)),
            dedup_window=float(bridge.get("dedup_window_ms", 60)) / 1000,
            sip_preempt=bool(bridge.get("sip_preempt", False)),
            clock=clock,
            on_decision=on_decision,
        )

    @property
    def occupied(self) -> list[int]:
        return [player for player, source_id in enumerate(self._slots) if source_id]

    @property
    def queue_len(self) -> int:
        """Número de sessões web ainda na fila, sem contar ofertas activas."""
        return len(self._web_queue)

    def player_for(self, source_id: str) -> int | None:
        session = self._sessions.get(source_id)
        return session.player if session and session.state == "active" else None

    def queue_status(self, source_id: str) -> QueueStatus | None:
        try:
            index = self._web_queue.index(source_id)
        except ValueError:
            return None
        return QueueStatus(position=index + 1, ahead=index)

    def queue_snapshot(self) -> dict[str, QueueStatus]:
        return {
            source_id: QueueStatus(position=index + 1, ahead=index)
            for index, source_id in enumerate(self._web_queue)
        }

    def connect(self, source_id: str, source_type: SourceType) -> list[Decision]:
        """Regista uma fonte e pede-lhe um slot."""
        decisions: list[Decision] = []
        now = self.clock()
        self._expire(now, decisions)

        if not source_id:
            decisions.append(Decision("rejected", reason="invalid_source_id"))
            return self._finish(decisions)
        if source_type not in ("web", "sip"):
            decisions.append(
                Decision("rejected", source_id=source_id, reason="invalid_source_type")
            )
            return self._finish(decisions)

        existing = self._sessions.get(source_id)
        if existing:
            if existing.source_type != source_type:
                decisions.append(
                    Decision("rejected", source_id=source_id, reason="source_type_changed")
                )
            else:
                self._report_existing(existing, decisions)
            return self._finish(decisions)

        session = _Session(source_id=source_id, source_type=source_type)
        self._sessions[source_id] = session
        self._request_slot(session, now, decisions)
        return self._finish(decisions)

    def request_slot(self, source_id: str) -> list[Decision]:
        """Volta a pedir lugar, por exemplo depois de uma oferta expirar."""
        decisions: list[Decision] = []
        now = self.clock()
        self._expire(now, decisions)
        session = self._sessions.get(source_id)
        if not session:
            decisions.append(Decision("rejected", source_id=source_id, reason="unknown_source"))
        elif session.state != "idle":
            self._report_existing(session, decisions)
        else:
            self._request_slot(session, now, decisions)
        return self._finish(decisions)

    def confirm(self, source_id: str) -> list[Decision]:
        """Confirma uma oferta web dentro do prazo e ocupa o slot reservado."""
        decisions: list[Decision] = []
        now = self.clock()
        self._expire(now, decisions)
        offer = self._offers.pop(source_id, None)
        if not offer:
            decisions.append(Decision("rejected", source_id=source_id, reason="no_offer"))
            return self._finish(decisions)

        self._reserved_slots.pop(offer.player, None)
        session = self._sessions[source_id]
        self._assign(session, offer.player, now, decisions)
        self._fill_available(now, decisions)
        return self._finish(decisions)

    def handle_event(self, source_id: str, event: str) -> list[Decision]:
        """Aceita um evento abstracto e envia-o ao jogo se a fonte tiver slot."""
        decisions: list[Decision] = []
        now = self.clock()
        self._expire(now, decisions)
        session = self._sessions.get(source_id)

        if not isinstance(event, str) or event not in VALID_EVENTS:
            decisions.append(
                Decision("rejected", source_id=source_id, event=event, reason="invalid_event")
            )
        elif not session or session.state != "active" or session.player is None:
            decisions.append(
                Decision("ignored", source_id=source_id, event=event, reason="no_slot")
            )
        else:
            session.last_activity = now
            event_key = (session.player, event)
            previous = self._last_events.get(event_key)
            if previous is not None and now - previous < self.dedup_window:
                decisions.append(
                    Decision(
                        "ignored",
                        source_id=source_id,
                        source_type=session.source_type,
                        player=session.player,
                        event=event,
                        reason="duplicate",
                    )
                )
            else:
                if not self.emitter.send_event(session.player, event):
                    LOGGER.error(
                        "Não foi possível encaminhar %s do jogador %d",
                        event,
                        session.player,
                    )
                    decisions.append(
                        Decision(
                            "rejected",
                            source_id=source_id,
                            source_type=session.source_type,
                            player=session.player,
                            event=event,
                            reason="emitter_failed",
                        )
                    )
                else:
                    self._last_events[event_key] = now
                    decisions.append(
                        Decision(
                            "forwarded",
                            source_id=source_id,
                            source_type=session.source_type,
                            player=session.player,
                            event=event,
                        )
                    )
                    if event == "hungup":
                        self._release_active(session, "hungup", decisions)
                        self._fill_available(now, decisions)
        return self._finish(decisions)

    def touch(self, source_id: str) -> list[Decision]:
        """Renova a actividade de uma sessão sem gerar um evento no jogo."""
        decisions: list[Decision] = []
        now = self.clock()
        self._expire(now, decisions)
        session = self._sessions.get(source_id)
        if session and session.state == "active":
            session.last_activity = now
            decisions.append(
                Decision(
                    "touched",
                    source_id=source_id,
                    source_type=session.source_type,
                    player=session.player,
                )
            )
        else:
            decisions.append(Decision("ignored", source_id=source_id, reason="no_slot"))
        return self._finish(decisions)

    def disconnect(self, source_id: str) -> list[Decision]:
        """Remove uma sessão, esteja activa, em espera ou na fila."""
        decisions: list[Decision] = []
        now = self.clock()
        self._expire(now, decisions)
        session = self._sessions.get(source_id)
        if not session:
            decisions.append(Decision("ignored", source_id=source_id, reason="unknown_source"))
            return self._finish(decisions)

        queue_changed = False
        if session.state == "active":
            self._release_active(session, "disconnected", decisions)
        elif session.state == "queued":
            self._web_queue.remove(source_id)
            queue_changed = True
        elif session.state == "waiting":
            self._sip_waiting.remove(source_id)
        elif session.state == "offered":
            offer = self._offers.pop(source_id)
            self._reserved_slots.pop(offer.player, None)

        decisions.append(
            Decision(
                "disconnected", source_id=source_id, source_type=session.source_type
            )
        )
        del self._sessions[source_id]
        self._fill_available(now, decisions)
        if queue_changed:
            self._append_queue_updates(decisions)
            self._emit_slots()
        return self._finish(decisions)

    def tick(self) -> list[Decision]:
        """Processa prazos usando o relógio injectado; deve ser chamado regularmente."""
        decisions: list[Decision] = []
        self._expire(self.clock(), decisions)
        return self._finish(decisions)

    def end_match(self) -> list[Decision]:
        """Termina a partida e limpa ocupantes, ofertas e esperas de forma atómica."""
        decisions: list[Decision] = []
        had_occupants = bool(self.occupied)
        for session in self._sessions.values():
            decisions.append(
                Decision(
                    "match_ended",
                    source_id=session.source_id,
                    source_type=session.source_type,
                    player=session.player,
                )
            )
        self._slots = [None] * self.slot_count
        self._sessions.clear()
        self._web_queue.clear()
        self._sip_waiting.clear()
        self._offers.clear()
        self._reserved_slots.clear()
        self._last_events.clear()
        if had_occupants or decisions:
            self._emit_slots()
        return self._finish(decisions)

    def _request_slot(
        self, session: _Session, now: float, decisions: list[Decision]
    ) -> None:
        free_player = self._first_free_slot()
        if free_player is not None:
            self._assign(session, free_player, now, decisions)
        elif session.source_type == "sip":
            session.state = "waiting"
            self._sip_waiting.append(session.source_id)
            decisions.append(
                Decision("waiting", source_id=session.source_id, source_type="sip")
            )
        else:
            session.state = "queued"
            self._web_queue.append(session.source_id)
            self._append_queue_updates(decisions)
            self._emit_slots()

    def _assign(
        self, session: _Session, player: int, now: float, decisions: list[Decision]
    ) -> None:
        self._slots[player] = session.source_id
        session.state = "active"
        session.player = player
        session.last_activity = now
        decisions.append(
            Decision(
                "assigned",
                source_id=session.source_id,
                source_type=session.source_type,
                player=player,
            )
        )
        self._emit_slots()

    def _release_active(
        self, session: _Session, reason: str, decisions: list[Decision]
    ) -> None:
        player = session.player
        if player is None:
            return
        self._slots[player] = None
        session.state = "idle"
        session.player = None
        session.last_activity = None
        self._clear_player_dedup(player)
        decisions.append(
            Decision(
                "released",
                source_id=session.source_id,
                source_type=session.source_type,
                player=player,
                reason=reason,
            )
        )
        self._emit_slots()

    def _fill_available(self, now: float, decisions: list[Decision]) -> None:
        while self._sip_waiting:
            player = self._first_free_slot()
            if player is None:
                break
            source_id = self._sip_waiting.popleft()
            session = self._sessions.get(source_id)
            if session and session.state == "waiting":
                self._assign(session, player, now, decisions)

        offered_any = False
        while self._web_queue:
            player = self._first_free_slot()
            if player is None:
                break
            source_id = self._web_queue.popleft()
            session = self._sessions.get(source_id)
            if not session or session.state != "queued":
                continue
            deadline = now + self.offer_timeout
            offer = _Offer(source_id=source_id, player=player, deadline=deadline)
            self._offers[source_id] = offer
            self._reserved_slots[player] = source_id
            session.state = "offered"
            decisions.append(
                Decision(
                    "offer",
                    source_id=source_id,
                    source_type="web",
                    player=player,
                    deadline=deadline,
                )
            )
            offered_any = True
        if offered_any:
            self._append_queue_updates(decisions)
            self._emit_slots()

    def _expire(self, now: float, decisions: list[Decision]) -> None:
        expired_offers = [
            offer for offer in self._offers.values() if now >= offer.deadline
        ]
        for offer in sorted(expired_offers, key=lambda item: (item.deadline, item.player)):
            self._offers.pop(offer.source_id, None)
            self._reserved_slots.pop(offer.player, None)
            session = self._sessions.get(offer.source_id)
            if session and session.state == "offered":
                session.state = "idle"
            decisions.append(
                Decision(
                    "offer_expired",
                    source_id=offer.source_id,
                    source_type="web",
                    player=offer.player,
                    reason="confirmation_timeout",
                )
            )

        inactive = [
            session
            for session in self._sessions.values()
            if session.state == "active"
            and session.last_activity is not None
            and now - session.last_activity >= self.inactivity_timeout
        ]
        for session in inactive:
            self._release_active(session, "inactivity_timeout", decisions)

        if expired_offers or inactive:
            self._fill_available(now, decisions)

    def _first_free_slot(self) -> int | None:
        for player, source_id in enumerate(self._slots):
            if source_id is None and player not in self._reserved_slots:
                return player
        return None

    def _report_existing(self, session: _Session, decisions: list[Decision]) -> None:
        if session.state == "active":
            decisions.append(
                Decision(
                    "assigned",
                    source_id=session.source_id,
                    source_type=session.source_type,
                    player=session.player,
                    reason="already_assigned",
                )
            )
        elif session.state == "queued":
            status = self.queue_status(session.source_id)
            if status:
                decisions.append(
                    Decision(
                        "queue_status",
                        source_id=session.source_id,
                        source_type="web",
                        position=status.position,
                        ahead=status.ahead,
                    )
                )
        elif session.state == "offered":
            offer = self._offers[session.source_id]
            decisions.append(
                Decision(
                    "offer",
                    source_id=session.source_id,
                    source_type="web",
                    player=offer.player,
                    deadline=offer.deadline,
                    reason="already_offered",
                )
            )
        else:
            decisions.append(
                Decision(
                    "waiting",
                    source_id=session.source_id,
                    source_type=session.source_type,
                    reason="already_waiting",
                )
            )

    def _append_queue_updates(self, decisions: list[Decision]) -> None:
        for source_id, status in self.queue_snapshot().items():
            decisions.append(
                Decision(
                    "queue_status",
                    source_id=source_id,
                    source_type="web",
                    position=status.position,
                    ahead=status.ahead,
                )
            )

    def _emit_slots(self) -> None:
        self.emitter.send_slots(self.occupied, self.queue_len)

    def _clear_player_dedup(self, player: int) -> None:
        for key in [key for key in self._last_events if key[0] == player]:
            del self._last_events[key]

    def _finish(self, decisions: list[Decision]) -> list[Decision]:
        if self.on_decision:
            for decision in decisions:
                try:
                    self.on_decision(decision)
                except Exception:
                    LOGGER.exception("O callback de decisão falhou")
        return decisions
