"""Testa udp_input.py sem sockets reais: chama _handle_packet diretamente e
verifica o efeito em phone_events / last_slots. Sem frameworks, só asserts."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from phone_events import PhoneEvents
from udp_input import UdpInput


def make_input():
    # Não queremos abrir socket real nem thread para este teste — construímos
    # a instância "à mão" contornando __init__, já que o que testamos é a
    # lógica de _handle_packet / drain_into, não o bind UDP em si.
    obj = UdpInput.__new__(UdpInput)
    import threading
    obj._lock = threading.Lock()
    obj._pending = []
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

# 4. JSON inválido não levanta exceção
ui = make_input()
for lixo in [b"{nao e json", b"", b"null", b"42", b'"string solta"', b"\xff\xfe\x00bad", b"[1,2,3]"]:
    ui._handle_packet(lixo)  # não pode rebentar
assert ui._pending == [], "lixo não devia produzir eventos"
print("OK 4: JSON inválido/lixo não derruba nada")

# 5. mensagem slots é guardada e não tratada como input
ui = make_input()
ui._handle_packet(b'{"type": "slots", "occupied": [0, 2], "queue_len": 5}')
assert ui.last_slots == {"occupied": [0, 2], "queue_len": 5}
assert ui._pending == [], "slots não é input, não pode ir para a fila de phone_events"
print("OK 5: mensagem slots guardada, não tratada como input")

# 5b. slots malformado não rebenta e não corrompe last_slots anterior por lixo novo
ui._handle_packet(b'{"type": "slots", "occupied": "nao e lista", "queue_len": 5}')
assert ui.last_slots == {"occupied": [0, 2], "queue_len": 5}, "slots malformado não devia substituir o estado válido"
print("OK 5b: slots malformado ignorado sem corromper o último estado válido")

# 6. missing field / campo em falta é ignorado
ui = make_input()
ui._handle_packet(b'{"player": 2}')  # falta "event"
ui._handle_packet(b'{"event": "press_1"}')  # falta "player"
assert ui._pending == [], "mensagens com campo em falta não deviam entrar na fila"
print("OK 6: campo em falta ignorado")

print("\nTodos os testes de udp_input passaram.")
