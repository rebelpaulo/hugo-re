"""Entrada de eventos por UDP para os 4 telefones.

Permite a uma aplicação externa (a bridge) carregar nas teclas dos jogadores
sem tocar no teclado físico, que continua a ser o fallback de emergência em
palco. Corre numa thread daemon para nunca bloquear o loop de render, e é
à prova de lixo: qualquer pacote malformado é ignorado em silêncio (só um
aviso raro no arranque/porta ocupada), nunca derruba o jogo.

Protocolo (JSON, um pacote UDP por evento):
    {"player": 0..3, "event": "press_5"}
    {"type": "slots", "occupied": [0, 2], "queue_len": 5}

"event" tem de ser um campo booleano válido de PhoneEvents (ver
phone_events.py): offhook, hungup, press_0..press_9, press_star, press_pound.
"""
import json
import logging
import socket
import threading

from phone_events import PhoneEvents

# Campos aceites em PhoneEvents — construído a partir da dataclass para nunca
# divergir do contrato real.
_VALID_EVENTS = set(PhoneEvents.__dataclass_fields__.keys())

MAX_PACKET_SIZE = 4096
MAX_PENDING_EVENTS = 1024

LOGGER = logging.getLogger(__name__)


class UdpInput:
    def __init__(self, host="127.0.0.1", port=9100):
        self.host = host
        self.port = port
        self._lock = threading.Lock()
        self._pending = []  # lista de (player, event) por consumir
        self._queue_limit_warned = False
        self._packet_error_types = set()
        self.last_slots = None  # último {"occupied": [...], "queue_len": N} recebido
        self._sock = None
        self._thread = None

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind((self.host, self.port))
            sock.settimeout(0.5)
            self._sock = sock
        except OSError as e:
            # Porta ocupada, sem permissões, etc. — o jogo tem de arrancar à
            # mesma, jogável por teclado, só com um aviso claro no arranque.
            print(f"[udp_input] AVISO: não foi possível abrir UDP {self.host}:{self.port} ({e}). "
                  f"Entrada por bridge desativada, teclado continua a funcionar.")
            return

        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()

    def _recv_loop(self):
        while True:
            try:
                data, _addr = self._sock.recvfrom(MAX_PACKET_SIZE)
            except socket.timeout:
                continue
            except OSError:
                # Socket fechado ou outro erro de baixo nível — termina a thread.
                return

            try:
                self._handle_packet(data)
            except Exception as exc:
                # A receção é infraestrutura de palco: um pacote nunca pode
                # impedir os seguintes. Regista só a primeira falha de cada
                # tipo para não inundar o log se houver tráfego hostil.
                error_type = type(exc)
                if error_type not in self._packet_error_types:
                    self._packet_error_types.add(error_type)
                    LOGGER.exception("Pacote UDP ignorado após erro inesperado")

    def _handle_packet(self, data):
        try:
            msg = json.loads(data)
        except (ValueError, UnicodeDecodeError):
            return

        if not isinstance(msg, dict):
            return

        if msg.get("type") == "slots":
            occupied = msg.get("occupied")
            queue_len = msg.get("queue_len")
            if (
                not isinstance(occupied, list)
                or any(
                    not isinstance(player, int)
                    or isinstance(player, bool)
                    or not 0 <= player <= 3
                    for player in occupied
                )
                or len(set(occupied)) != len(occupied)
                or not isinstance(queue_len, int)
                or isinstance(queue_len, bool)
                or queue_len < 0
            ):
                return
            with self._lock:
                self.last_slots = {"occupied": occupied, "queue_len": queue_len}
            return

        player = msg.get("player")
        event = msg.get("event")
        if (
            not isinstance(player, int)
            or isinstance(player, bool)
            or not 0 <= player <= 3
        ):
            return
        if not isinstance(event, str) or event not in _VALID_EVENTS:
            return

        with self._lock:
            if len(self._pending) >= MAX_PENDING_EVENTS:
                if not self._queue_limit_warned:
                    self._queue_limit_warned = True
                    LOGGER.warning(
                        "Fila UDP cheia (%d eventos); eventos novos serão ignorados",
                        MAX_PENDING_EVENTS,
                    )
                return
            self._pending.append((player, event))

    def get_slots(self):
        """Devolve uma cópia do último {"occupied": [...], "queue_len": N}
        recebido, ou None se ainda não chegou nenhuma mensagem 'slots' (por
        exemplo, a bridge não está a correr)."""
        with self._lock:
            return dict(self.last_slots) if self.last_slots is not None else None

    def drain_into(self, phone_events):
        """Aplica todos os eventos pendentes à lista phone_events (4 elementos)
        e esvazia a fila. Chamar uma vez por frame, logo a seguir ao
        pygame.event.get()."""
        with self._lock:
            pending, self._pending = self._pending, []

        for player, event in pending:
            setattr(phone_events[player], event, True)
