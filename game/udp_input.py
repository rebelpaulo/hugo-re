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
import socket
import threading

from phone_events import PhoneEvents

# Campos aceites em PhoneEvents — construído a partir da dataclass para nunca
# divergir do contrato real.
_VALID_EVENTS = set(PhoneEvents.__dataclass_fields__.keys())

MAX_PACKET_SIZE = 4096


class UdpInput:
    def __init__(self, host="127.0.0.1", port=9100):
        self.host = host
        self.port = port
        self._lock = threading.Lock()
        self._pending = []  # lista de (player, event) por consumir
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

            self._handle_packet(data)

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
            if not isinstance(occupied, list) or not isinstance(queue_len, int):
                return
            with self._lock:
                self.last_slots = {"occupied": occupied, "queue_len": queue_len}
            return

        player = msg.get("player")
        event = msg.get("event")
        if not isinstance(player, int) or not (0 <= player <= 3):
            return
        if event not in _VALID_EVENTS:
            return

        with self._lock:
            self._pending.append((player, event))

    def drain_into(self, phone_events):
        """Aplica todos os eventos pendentes à lista phone_events (4 elementos)
        e esvazia a fila. Chamar uma vez por frame, logo a seguir ao
        pygame.event.get()."""
        with self._lock:
            pending, self._pending = self._pending, []

        for player, event in pending:
            setattr(phone_events[player], event, True)
