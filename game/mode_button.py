"""Botão de modo de entrada no canto superior esquerdo do ecrã.

Para que serve: a sala pode estar montada com os telemóveis dos convidados
(QR + webapp) ou com os telefones físicos, e até agora trocar entre os dois
era editar `bridge/config.yaml` e reiniciar tudo — com o jogo e o túnel
atrás, quase um minuto de ecrã parado à frente das pessoas. Agora é um
clique.

O que o botão mostra é o modo que o BRIDGE diz estar a usar (vem no campo
`mode` da mensagem `slots`, ver `game/udp_input.py`), nunca o que nós
pedimos. Se o bridge estiver em baixo, clicar não muda o rótulo — que é a
resposta certa: o modo não mudou mesmo. Para não parecer que o clique se
perdeu, o botão fica com ar de "à espera" durante uns segundos depois de um
pedido; se a confirmação não chegar, volta ao que estava.

Só é desenhado enquanto o rato esteve a mexer há pouco, tal como o botão de
ecrã inteiro (que fica no canto oposto) — num LED wall, botões parados nos
cantos durante três horas são ruído.
"""
import json
import os
import socket
import time

import pygame
import pygame.freetype

import fullscreen_button

_ALTURA = 22
_LARGURA = 96

# Canto superior ESQUERDO. Começou colado ao botão de ecrã inteiro, à direita,
# e em ecrã inteiro no LED wall ficava escondido: o canto direito é onde o
# macOS e o resto do ambiente de trabalho põem as suas próprias coisas por
# cima, e o rótulo aparecia cortado a meio. À esquerda está sozinho.
RECT = pygame.Rect(fullscreen_button.RECT.y, fullscreen_button.RECT.y, _LARGURA, _ALTURA)

# Mesma disciplina do `game/score_report.py`: loopback, porta por omissão
# igual à de `bridge/config.yaml: control.port`, substituível pelo ambiente
# para a produção poder mudar sem tocar em código.
BRIDGE_HOST = "127.0.0.1"
BRIDGE_CONTROL_PORT = int(os.environ.get("HUGO_CONTROL_PORT", "9111"))

# Quanto tempo o botão fica com ar de "à espera" depois de um pedido.
_ESPERA_SEGUNDOS = 4.0

_BG = (10, 8, 30, 190)
_EDGE = (255, 221, 0, 220)      # o mesmo amarelo do convite
_EDGE_ESPERA = (150, 140, 90, 200)
_TEXTO = (255, 255, 255, 235)
_TEXTO_ESPERA = (170, 165, 150, 220)
_PONTO_WEB = (90, 220, 140)
_PONTO_SIP = (255, 170, 60)

_ROTULOS = {"web": "TELEMÓVEIS", "sip": "TELEFONES"}

_fonte = None
_pedido = None          # (modo_pedido, instante) enquanto se espera confirmação

# Não ligado e não bloqueante, como o score_report: um `sendto` deste tamanho
# nunca prende o fio de render, e o jogo não pode sequer notar se o bridge
# existe.
_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_sock.setblocking(False)


def outro_modo(modo):
    """O modo para onde o botão salta a partir do actual."""
    return "web" if modo == "sip" else "sip"


def hit(pos):
    """`pos` em coordenadas da superfície 640x480 (já convertido)."""
    return RECT.collidepoint(pos)


def pedir(modo, agora=None):
    """Pede ao bridge que passe a `modo`. Fire-and-forget, nunca levanta."""
    global _pedido
    _pedido = (modo, time.monotonic() if agora is None else agora)
    dados = json.dumps({"cmd": "input_mode", "mode": modo}).encode("utf-8")
    try:
        _sock.sendto(dados, (BRIDGE_HOST, BRIDGE_CONTROL_PORT))
    except OSError:
        # Bridge em baixo, porta fechada, rede a arder: o rótulo não muda e é
        # isso que o operador tem de ver.
        pass


def a_espera(modo, agora=None):
    """Há um pedido por confirmar? Serve o desenho e o teste."""
    global _pedido
    if _pedido is None:
        return False
    pedido, quando = _pedido
    agora = time.monotonic() if agora is None else agora
    if modo == pedido or agora - quando > _ESPERA_SEGUNDOS:
        _pedido = None
        return False
    return True


def draw(surface, modo, agora=None):
    """Desenha o botão sobre a superfície 640x480 do jogo."""
    global _fonte
    if _fonte is None:
        _fonte = pygame.freetype.SysFont("Arial", 9, bold=True)

    espera = a_espera(modo, agora)
    plate = pygame.Surface(RECT.size, pygame.SRCALPHA)
    pygame.draw.rect(plate, _BG, plate.get_rect(), border_radius=5)
    pygame.draw.rect(
        plate, _EDGE_ESPERA if espera else _EDGE, plate.get_rect(), width=1, border_radius=5
    )

    # Ponto de cor: verde para telemóveis, laranja para telefones. Num ecrã
    # grande e de longe, a cor chega-se antes das letras.
    cor_ponto = _PONTO_SIP if modo == "sip" else _PONTO_WEB
    pygame.draw.circle(plate, cor_ponto, (10, _ALTURA // 2), 4)

    rotulo = _ROTULOS.get(modo, "TELEMÓVEIS")
    if espera:
        rotulo += " …"
    rect_texto = _fonte.get_rect(rotulo)
    _fonte.render_to(
        plate,
        (19, (_ALTURA - rect_texto.height) // 2),
        rotulo,
        _TEXTO_ESPERA if espera else _TEXTO,
    )

    surface.blit(plate, RECT.topleft)


def demo():
    """Auto-teste: `../.venv/bin/python mode_button.py` (não precisa de ecrã)."""
    global _pedido
    assert outro_modo("web") == "sip" and outro_modo("sip") == "web"
    assert hit(RECT.center) and not hit((0, 0))
    # Não pode montar em cima do botão de ecrã inteiro — os dois vivem no mesmo
    # canto e um clique tem de ser de um só.
    assert not RECT.colliderect(fullscreen_button.RECT)
    assert RECT.x >= 0 and RECT.right <= 640

    _pedido = None
    assert not a_espera("web"), "sem pedido não há espera"
    pedir("sip", agora=100.0)
    assert a_espera("web", agora=100.5), "pedido feito, ainda por confirmar"
    assert not a_espera("sip", agora=100.5), "confirmado pelo bridge, acabou a espera"
    pedir("sip", agora=200.0)
    assert not a_espera("web", agora=200.0 + _ESPERA_SEGUNDOS + 0.1), "desiste ao fim do prazo"
    # E depois de desistir não volta a marcar espera sozinho.
    assert not a_espera("web", agora=300.0)
    print("mode_button: todos os cenários passaram.")


if __name__ == "__main__":
    demo()
