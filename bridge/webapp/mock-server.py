#!/usr/bin/env python3
"""mock-server.py — serve os ficheiros do webapp e finge o protocolo do bridge,
para testar o telefone sem o servidor real (bridge/adapters/web_adapter.py).

Só biblioteca standard (http.server, socket, threading, hashlib, base64, struct).
Implementa um servidor WebSocket (RFC 6455) mínimo à mão — não há módulo `websockets`
na standard library.

Uso:
    .venv/bin/python bridge/webapp/mock-server.py [--port 8765] [--full] [--cycle 5] [--mode web]

    --full    arranca com os 4 lugares ocupados por "fantasmas", para forçar
              qualquer ligação nova a cair na fila (útil para testar o ecrã de fila).
    --cycle   segundos entre ciclos automáticos de "liberta um lugar e oferece
              a vez a quem está na fila" (para testar o ecrã "é a tua vez" sem
              precisar de 4 pessoas reais). 0 desliga o ciclo.
    --mode    input_mode simulado (web/sip — ver bridge/config.yaml),
              mandado ao cliente logo na ligação. Omissão: web.

Protocolo (fixo, ver bridge/webapp/index.html e README do bridge):
    cliente -> servidor: hello, press, offhook, hangup, confirm, ping
    servidor -> cliente: config (logo na ligação), slot, queued, your_turn,
                          released, pong, audio

Áudio (bridge/webapp/game-audio.js): o bridge a sério serve /audio-manifest.json
e /audio/<recurso> a partir de hugo-assets; este mock não tem esses ficheiros,
por isso finge os dois — um manifesto com o attract_demo.wav e um WAV de
silêncio válido gerado na hora — para a webapp poder pré-carregar e tocar a
sério em testes manuais. `GET /debug/send-audio` manda uma mensagem "audio" a
todos os clientes ligados, para simular o jogo a tomar conta do som (prova de
que a intro local se cala) sem precisar do bridge a sério.
"""

import argparse
import base64
import hashlib
import io
import json
import os
import random
import struct
import threading
import time
import urllib.parse
import uuid
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
WEBAPP_DIR = os.path.dirname(os.path.abspath(__file__))
COLORS = ["blue", "green", "red", "white"]
OFFER_SECONDS = 15
INPUT_MODE = "web"   # mudado por --mode (ver main())

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
}

# Só para o mock: o ficheiro a sério vem do bridge (hugo-assets), aqui é só
# uma referência ao mesmo caminho para o manifesto/pré-carga bater certo.
INTRO_RESOURCE = "audio_for_videos/pt/attract_demo.wav"


def fake_wav_bytes(seconds=1.0, rate=8000):
    """WAV válido (silêncio, 16 bits/mono) só para o decodeAudioData ter algo
    a sério para decodificar — o mock não tem o áudio verdadeiro."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


_FAKE_WAV = fake_wav_bytes()

# ---------------- estado partilhado (jogo falso) ----------------

lock = threading.RLock()
slots = [None, None, None, None]     # client_id ou "__ghost__" ou None
queue = []                           # lista de client_id, FIFO
clients = {}                         # client_id -> {"send": callable, "conn_alive": bool}
pending_offer = {"idx": None, "client_id": None, "deadline": 0.0}


def log(*a):
    print("[mock-server]", *a, flush=True)


def free_slot_index():
    for i, occ in enumerate(slots):
        if occ is None:
            return i
    return None


def assign_slot(client_id):
    """Chamado com o lock preso. Devolve o índice atribuído ou None."""
    idx = free_slot_index()
    if idx is None:
        return None
    slots[idx] = client_id
    return idx


def queue_positions_for(client_id):
    pos = queue.index(client_id) + 1
    return pos, pos - 1


def try_offer_next():
    """Chamado com o lock preso. Se houver lugar livre e gente na fila, oferece a vez."""
    if pending_offer["idx"] is not None:
        return
    idx = free_slot_index()
    if idx is None or not queue:
        return
    client_id = queue.pop(0)
    pending_offer["idx"] = idx
    pending_offer["client_id"] = client_id
    pending_offer["deadline"] = time.time() + OFFER_SECONDS
    info = clients.get(client_id)
    if info:
        info["send"]({"type": "your_turn", "player": idx, "seconds": OFFER_SECONDS})
    log("ofereceu lugar", idx, "a", client_id)


def offer_watchdog():
    while True:
        time.sleep(0.5)
        with lock:
            if pending_offer["idx"] is not None and time.time() > pending_offer["deadline"]:
                log("oferta expirou para", pending_offer["client_id"])
                pending_offer["idx"] = None
                pending_offer["client_id"] = None
                try_offer_next()


def auto_cycle(interval):
    """Ciclo de demonstração: liberta periodicamente um lugar ocupado para dar
    lugar a quem está na fila. Só serve para testar o webapp sem 4 jogadores reais."""
    if interval <= 0:
        return
    while True:
        time.sleep(interval)
        with lock:
            occupied = [i for i, occ in enumerate(slots) if occ is not None]
            if not occupied or not queue:
                continue
            idx = random.choice(occupied)
            occ = slots[idx]
            slots[idx] = None
            log("ciclo automático: libertou o lugar", idx, "(era", occ, ")")
            if occ != "__ghost__":
                info = clients.get(occ)
                if info:
                    info["send"]({"type": "released"})
            try_offer_next()


def handle_message(client_id, msg):
    mtype = msg.get("type")
    with lock:
        if mtype == "hello":
            if client_id in slots or client_id in queue:
                return
            idx = assign_slot(client_id)
            info = clients[client_id]
            if idx is not None:
                info["send"]({"type": "slot", "player": idx, "color": COLORS[idx]})
                log(client_id, "-> lugar", idx)
            else:
                queue.append(client_id)
                pos, ahead = queue_positions_for(client_id)
                info["send"]({"type": "queued", "position": pos, "ahead": ahead})
                log(client_id, "-> fila, posição", pos)

        elif mtype == "confirm":
            if pending_offer["client_id"] == client_id:
                idx = pending_offer["idx"]
                slots[idx] = client_id
                pending_offer["idx"] = None
                pending_offer["client_id"] = None
                clients[client_id]["send"]({"type": "slot", "player": idx, "color": COLORS[idx]})
                log(client_id, "confirmou -> lugar", idx)

        elif mtype == "hangup":
            for i, occ in enumerate(slots):
                if occ == client_id:
                    slots[i] = None
            if client_id in queue:
                queue.remove(client_id)
            try_offer_next()

        elif mtype == "ping":
            clients[client_id]["send"]({"type": "pong"})

        elif mtype in ("press", "offhook"):
            pass  # o mock não precisa de reagir; o adaptador real envia por UDP


def cleanup_client(client_id):
    with lock:
        clients.pop(client_id, None)
        for i, occ in enumerate(slots):
            if occ == client_id:
                slots[i] = None
        if client_id in queue:
            queue.remove(client_id)
        if pending_offer["client_id"] == client_id:
            pending_offer["idx"] = None
            pending_offer["client_id"] = None
        try_offer_next()


# ---------------- WebSocket (RFC 6455), à mão, só stdlib ----------------

def ws_accept_key(client_key):
    digest = hashlib.sha1((client_key + WS_GUID).encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def recv_frame(rfile):
    b1 = rfile.read(1)
    if not b1:
        return None, None
    b1 = b1[0]
    opcode = b1 & 0x0F
    b2 = rfile.read(1)[0]
    masked = b2 & 0x80
    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack(">H", rfile.read(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", rfile.read(8))[0]
    mask_key = rfile.read(4) if masked else None
    payload = rfile.read(length) if length else b""
    if masked and mask_key:
        payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    return opcode, payload


def encode_frame(opcode, payload):
    header = bytearray()
    header.append(0x80 | opcode)
    length = len(payload)
    if length <= 125:
        header.append(length)
    elif length <= 0xFFFF:
        header.append(126)
        header += struct.pack(">H", length)
    else:
        header.append(127)
        header += struct.pack(">Q", length)
    return bytes(header) + payload


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # silencioso; usar log() acima para os eventos que interessam

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/ws") and self.headers.get("Upgrade", "").lower() == "websocket":
            self.handle_websocket()
            return
        if path == "/audio-manifest.json":
            self.send_json([INTRO_RESOURCE])
            return
        if path.startswith("/audio/"):
            self.serve_fake_audio(path[len("/audio/"):])
            return
        if path == "/debug/send-audio":
            self.debug_send_audio()
            return
        self.serve_static()

    def send_json(self, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def serve_fake_audio(self, resource):
        # Só conhece o recurso da intro (é o único que os testes precisam);
        # qualquer outro pedido dá 404, como faria o bridge a sério.
        if resource != INTRO_RESOURCE:
            self.send_error(404, "not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(_FAKE_WAV)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(_FAKE_WAV)

    def debug_send_audio(self):
        # Só para testes manuais/automatizados: finge o jogo a mandar áudio
        # pela WebSocket, sem precisar do bridge a sério (ver cabeçalho do
        # ficheiro). Parâmetros opcionais na query string.
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        action = params.get("action", ["play"])[0]
        resource = params.get("resource", [INTRO_RESOURCE])[0]
        msg = {"type": "audio", "action": action, "id": 999}
        if action == "play":
            msg["resource"] = resource
            msg["loops"] = -1
        with lock:
            targets = list(clients.values())
        for info in targets:
            info["send"](msg)
        log("debug: mandou audio", msg, "a", len(targets), "cliente(s)")
        self.send_json({"sent_to": len(targets), "message": msg})

    def serve_static(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            path = "/index.html"
        full = os.path.normpath(os.path.join(WEBAPP_DIR, path.lstrip("/")))
        if not full.startswith(WEBAPP_DIR) or not os.path.isfile(full):
            self.send_error(404, "not found")
            return
        ext = os.path.splitext(full)[1]
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def handle_websocket(self):
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self.send_error(400, "sem Sec-WebSocket-Key")
            return
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", ws_accept_key(key))
        self.end_headers()

        client_id = str(uuid.uuid4())[:8]
        send_lock = threading.Lock()

        def send(obj):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            frame = encode_frame(0x1, data)
            try:
                with send_lock:
                    self.wfile.write(frame)
                    self.wfile.flush()
            except OSError:
                pass

        clients[client_id] = {"send": send}
        log(client_id, "ligou")
        send({"type": "config", "input_mode": INPUT_MODE})

        try:
            while True:
                opcode, payload = recv_frame(self.rfile)
                if opcode is None or opcode == 0x8:  # EOF ou close
                    break
                if opcode == 0x9:  # ping -> pong
                    with send_lock:
                        self.wfile.write(encode_frame(0xA, payload))
                        self.wfile.flush()
                    continue
                if opcode != 0x1:
                    continue
                try:
                    msg = json.loads(payload.decode("utf-8"))
                except ValueError:
                    continue
                handle_message(client_id, msg)
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            cleanup_client(client_id)
            log(client_id, "desligou")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--full", action="store_true", help="arranca com os 4 lugares ocupados")
    ap.add_argument("--cycle", type=float, default=5.0, help="segundos entre ciclos automáticos (0 desliga)")
    ap.add_argument("--mode", choices=["web", "sip"], default="web", help="input_mode simulado")
    args = ap.parse_args()

    global INPUT_MODE
    INPUT_MODE = args.mode

    if args.full:
        for i in range(4):
            slots[i] = "__ghost__"

    threading.Thread(target=offer_watchdog, daemon=True).start()
    threading.Thread(target=auto_cycle, args=(args.cycle,), daemon=True).start()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    log("a servir", WEBAPP_DIR, "em http://localhost:%d" % args.port,
        "(4 lugares ocupados de início)" if args.full else "(lugares livres)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
