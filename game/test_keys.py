"""Verifica que todas as teclas configuradas resolvem para o jogador certo,
e que nenhuma tecla está atribuída a dois jogadores ou a dois botões."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame
from config import Config

BOTOES = {n: getattr(Config, f"BTN_{n}") for n in
          ["OFF_HOOK", "HUNG_UP", "0","1","2","3","4","5","6","7","8","9"]}

# 1. Todas as entradas são iteráveis (senão `event.key in ...` rebenta)
for nome, lista in BOTOES.items():
    assert len(lista) == 4, f"BTN_{nome} não tem 4 jogadores"
    for i, teclas in enumerate(lista):
        assert hasattr(teclas, "__iter__"), f"BTN_{nome}[{i}] não é iterável: {teclas!r}"
        assert len(teclas) >= 1, f"BTN_{nome}[{i}] está vazio"

# 2. Nenhuma tecla repetida entre jogadores ou botões
vista = {}
for nome, lista in BOTOES.items():
    for i, teclas in enumerate(lista):
        for k in teclas:
            assert k not in vista, (
                f"tecla {pygame.key.name(k)!r} repetida: "
                f"BTN_{nome}[jogador {i+1}] e BTN_{vista[k][0]}[jogador {vista[k][1]+1}]")
            vista[k] = (nome, i)
assert Config.BTN_EXIT not in vista, "BTN_EXIT colide com um botão de jogador"

# 3. O jogador 4 tem de ser jogável sem teclado numérico
NUMERICO = {pygame.K_KP0,pygame.K_KP1,pygame.K_KP2,pygame.K_KP3,pygame.K_KP4,
            pygame.K_KP5,pygame.K_KP6,pygame.K_KP7,pygame.K_KP8,pygame.K_KP9}
for n in ["0","1","2","3","4","5","6","7","8","9"]:
    fora = [k for k in BOTOES[n][3] if k not in NUMERICO]
    assert fora, f"BTN_{n}[jogador 4] só tem teclas do teclado numérico"

print(f"OK: {len(vista)} teclas, sem colisões.")
print("Jogador 4, sem teclado numérico: " + "  ".join(
    f"{n}={'/'.join(pygame.key.name(k) for k in BOTOES[n][3] if k not in NUMERICO)}"
    for n in ["1","2","3","4","5","6","7","8","9","0"]))
