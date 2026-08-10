"""Testa udp_input.py com asserts, incluindo a sobrevivência do socket real."""
import os
import socket
import sys
import threading
import time
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from phone_events import PhoneEvents
from udp_input import MAX_PENDING_EVENTS, UdpInput


def make_input():
    # Não queremos abrir socket real nem thread para este teste — construímos
    # a instância "à mão" contornando __init__, já que o que testamos é a
    # lógica de _handle_packet / drain_into, não o bind UDP em si.
    obj = UdpInput.__new__(UdpInput)
    import threading
    obj._lock = threading.Lock()
    obj._pending = []
    obj._queue_limit_warned = False
    obj._packet_error_types = set()
    obj.last_slots = None
    return obj


def fresh_events():
    return [PhoneEvents() for _ in range(4)]


# 1. Evento válido chega ao jogador certo
ui = make_input()
ui._handle_packet(b'{"player": 0, "event": "press_5"}')
events = fresh_events()
ui.drain_into(events)
assert events[0].press_5 is True, "press_5 devia estar True no jogador 0"
assert not events[1].any_set() and not events[2].any_set() and not events[3].any_set(), \
    "outros jogadores não deviam ter sido tocados"
assert ui._pending == [], "fila devia ficar vazia depois do drain"
print("OK 1: evento válido aplicado ao jogador certo")

# 2. player fora de gama é ignorado
ui = make_input()
ui._handle_packet(b'{"player": 4, "event": "press_5"}')
ui._handle_packet(b'{"player": -1, "event": "press_5"}')
assert ui._pending == [], "player fora de 0-3 não devia entrar na fila"
print("OK 2: player fora de gama ignorado")

# 3. event desconhecido é ignorado
ui = make_input()
ui._handle_packet(b'{"player": 1, "event": "press_hash"}')
ui._handle_packet(b'{"player": 1, "event": "explode"}')
assert ui._pending == [], "evento desconhecido não devia entrar na fila"
print("OK 3: event desconhecido ignorado")

# 3b. event tem de ser string e player não pode ser booleano
ui = make_input()
ui._handle_packet(b'{"player": 0, "event": ["press_5"]}')
ui._handle_packet(b'{"player": true, "event": "press_5"}')
assert ui._pending == [], "event não-string e player booleano deviam ser rejeitados"
print("OK 3b: event não-string e player booleano rejeitados")

# 4. JSON inválido não levanta exceção
ui = make_input()
for lixo in [b"{nao e json", b"", b"null", b"42", b'"string solta"', b"\xff\xfe\x00bad", b"[1,2,3]"]:
    ui._handle_packet(lixo)  # não pode rebentar
assert ui._pending == [], "lixo não devia produzir eventos"
print("OK 4: JSON inválido/lixo não derruba nada")

# 5. mensagem slots é guardada e não tratada como input; sem "mode" assume "web"
ui = make_input()
ui._handle_packet(b'{"type": "slots", "occupied": [0, 2], "queue_len": 5}')
assert ui.last_slots == {"occupied": [0, 2], "queue_len": 5, "mode": "web"}
assert ui._pending == [], "slots não é input, não pode ir para a fila de phone_events"
print("OK 5: mensagem slots guardada, não tratada como input, mode omisso -> web")

# 5b. slots malformado não rebenta e não corrompe last_slots anterior por lixo novo
ui._handle_packet(b'{"type": "slots", "occupied": "nao e lista", "queue_len": 5}')
assert ui.last_slots == {"occupied": [0, 2], "queue_len": 5, "mode": "web"}, "slots malformado não devia substituir o estado válido"
print("OK 5b: slots malformado ignorado sem corromper o último estado válido")

# 5c. valida integralmente jogadores, repetições e comprimento da fila
for invalido in [
    b'{"type":"slots","occupied":[99,-1],"queue_len":0}',
    b'{"type":"slots","occupied":[0,0],"queue_len":0}',
    b'{"type":"slots","occupied":[true],"queue_len":0}',
    b'{"type":"slots","occupied":[0],"queue_len":-5}',
    b'{"type":"slots","occupied":[0],"queue_len":true}',
]:
    ui._handle_packet(invalido)
assert ui.last_slots == {"occupied": [0, 2], "queue_len": 5, "mode": "web"}, (
    "slots inválido não devia substituir o estado válido")
print("OK 5c: slots fora de gama, repetidos, booleanos ou negativos rejeitados")

# 5d. mode explícito "sip" é aceite e guardado
ui = make_input()
ui._handle_packet(b'{"type":"slots","occupied":[0],"queue_len":2,"mode":"sip"}')
assert ui.last_slots == {"occupied": [0], "queue_len": 2, "mode": "sip"}
print("OK 5d: mode=sip explícito guardado")

# 5e. mode inválido (string desconhecida, booleano, número) reprova a mensagem inteira
ui = make_input()
ui._handle_packet(b'{"type":"slots","occupied":[0],"queue_len":2,"mode":"web"}')
for invalido in [
    b'{"type":"slots","occupied":[1],"queue_len":9,"mode":"both"}',
    b'{"type":"slots","occupied":[1],"queue_len":9,"mode":true}',
    b'{"type":"slots","occupied":[1],"queue_len":9,"mode":1}',
    b'{"type":"slots","occupied":[1],"queue_len":9,"mode":null}',
    b'{"type":"slots","occupied":[1],"queue_len":9,"mode":["web"]}',
]:
    ui._handle_packet(invalido)
assert ui.last_slots == {"occupied": [0], "queue_len": 2, "mode": "web"}, (
    "mode inválido (tipo errado ou string desconhecida) não devia substituir o estado válido")
print("OK 5e: mode inválido (tipo errado ou 'both') rejeitado sem derrubar nada")

# 6. missing field / campo em falta é ignorado
ui = make_input()
ui._handle_packet(b'{"player": 2}')  # falta "event"
ui._handle_packet(b'{"event": "press_1"}')  # falta "player"
assert ui._pending == [], "mensagens com campo em falta não deviam entrar na fila"
print("OK 6: campo em falta ignorado")

# 7. a fila tem limite e rejeita o excesso
ui = make_input()
for _ in range(MAX_PENDING_EVENTS + 10):
    ui._handle_packet(b'{"player":0,"event":"press_5"}')
assert len(ui._pending) == MAX_PENDING_EVENTS, (
    f"fila devia ficar limitada a {MAX_PENDING_EVENTS}, tem {len(ui._pending)}")
print(f"OK 7: fila limitada a {len(ui._pending)} eventos; excesso rejeitado")

# 8. prova do P0 no ciclo real: bom, malformado, bom
ui = UdpInput(port=0)
sender = None
mode = "UDP/IP"
if ui._sock is None:
    sender, receiver = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
    receiver.settimeout(0.5)
    ui = make_input()
    ui._sock = receiver
    ui._thread = threading.Thread(target=ui._recv_loop, daemon=True)
    ui._thread.start()
    mode = "datagrama local (sandbox sem bind UDP/IP)"
else:
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def send_packet(payload):
    if mode == "UDP/IP":
        sender.sendto(payload, ui._sock.getsockname())
    else:
        sender.send(payload)


try:
    send_packet(b'{"player":0,"event":"press_5"}')
    deadline = time.monotonic() + 1
    while len(ui._pending) < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    events = fresh_events()
    ui.drain_into(events)
    assert events[0].press_5 is True, "o primeiro pacote bom devia funcionar"

    send_packet(b'{"player":0,"event":["press_5"]}')
    send_packet(b'{"player":1,"event":"press_5"}')
    deadline = time.monotonic() + 1
    while len(ui._pending) < 1 and time.monotonic() < deadline:
        time.sleep(0.01)
    events = fresh_events()
    ui.drain_into(events)
    assert events[1].press_5 is True, "o pacote bom após o malformado devia funcionar"
    assert ui._thread.is_alive(), "a thread UDP devia continuar viva"
    print(f"OK 8: bom -> malformado -> bom; terceiro funciona e thread continua viva ({mode})")
finally:
    sender.close()
    ui._sock.close()
    ui._thread.join(1)

# 9. se o bind falhar, a ausência de UDP não altera os eventos do teclado
with mock.patch("udp_input.socket.socket", side_effect=OSError("porta ocupada")):
    ui = UdpInput()
events = fresh_events()
events[2].press_5 = True  # atualização feita pelo caminho de teclado de game.py
ui.drain_into(events)
assert events[2].press_5 is True, "o teclado devia continuar funcional sem socket UDP"
assert ui._sock is None and ui._thread is None
print("OK 9: bind falhou e o teclado continuou a atualizar phone_events")

print("\nTodos os testes de udp_input passaram.")
