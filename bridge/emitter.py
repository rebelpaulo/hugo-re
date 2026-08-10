"""Emissor UDP fire-and-forget para o jogo."""

from __future__ import annotations

import json
import logging
import socket
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml


LOGGER = logging.getLogger(__name__)

VALID_EVENTS = frozenset(
    {"offhook", "hungup", "press_star", "press_pound"}
    | {f"press_{digit}" for digit in range(10)}
)


class UdpEmitter:
    """Envia datagramas para o jogo sem propagar falhas ao chamador."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9100,
        *,
        socket_factory: Callable[..., socket.socket] = socket.socket,
    ) -> None:
        self.host = host
        self.port = port
        self._socket_factory = socket_factory

    @classmethod
    def from_config(cls, path: str | Path) -> "UdpEmitter":
        """Cria um emissor a partir da secção ``game`` do YAML."""
        with Path(path).open(encoding="utf-8") as config_file:
            config = yaml.safe_load(config_file) or {}
        game = config.get("game") or {}
        return cls(host=game.get("host", "127.0.0.1"), port=int(game.get("port", 9100)))

    def send_event(self, player: int, event: str) -> bool:
        """Envia um evento de jogador; devolve ``False`` se não o conseguir fazer."""
        if not isinstance(player, int) or isinstance(player, bool) or not 0 <= player <= 3:
            LOGGER.error("Evento UDP rejeitado: jogador inválido %r", player)
            return False
        if not isinstance(event, str) or event not in VALID_EVENTS:
            LOGGER.error("Evento UDP rejeitado: evento inválido %r", event)
            return False
        return self._send({"player": player, "event": event})

    def send_slots(self, occupied: list[int], queue_len: int) -> bool:
        """Envia o estado de ocupação; devolve ``False`` em qualquer falha."""
        if not isinstance(occupied, (list, tuple)):
            LOGGER.error("Estado UDP rejeitado: occupied=%r", occupied)
            return False
        if (
            not isinstance(queue_len, int)
            or isinstance(queue_len, bool)
            or queue_len < 0
            or any(
                not isinstance(player, int)
                or isinstance(player, bool)
                or not 0 <= player <= 3
                for player in occupied
            )
        ):
            LOGGER.error(
                "Estado UDP rejeitado: occupied=%r queue_len=%r", occupied, queue_len
            )
            return False
        return self._send(
            {"type": "slots", "occupied": sorted(set(occupied)), "queue_len": queue_len}
        )

    def _send(self, payload: Mapping[str, Any]) -> bool:
        try:
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            with self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
                udp_socket.sendto(data, (self.host, self.port))
            return True
        except Exception:
            # O jogo pode estar fechado ou a reiniciar; isso nunca deve parar o bridge.
            LOGGER.exception("Não foi possível enviar o pacote UDP para o jogo")
            return False
