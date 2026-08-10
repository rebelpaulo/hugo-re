"""Botão de ecrã inteiro no canto do ecrã.

Existe porque o operador precisa de pôr o jogo em ecrã inteiro no dia sem ir
buscar o teclado nem relançar com `FULLSCREEN=1` — clica, fica cheio; clica
outra vez, volta à janela.

Só é desenhado enquanto o rato esteve a mexer há pouco (ver `game.py`): num
LED wall à frente de gente, uma seta e um botão parados no canto durante duas
horas são ruído. Quem precisa dele mexe o rato e ele aparece.

O rectângulo é em coordenadas da superfície do jogo (640x480), não da janela.
Em ecrã inteiro o quadro é desenhado numa caixa 4:3 centrada com barras aos
lados, portanto o clique tem de ser convertido de volta antes de bater aqui —
é o que `Game._surface_pos` faz.
"""
import pygame

from config import Config

_SIZE = 22
_MARGIN = 6

# Canto superior direito. Fica sobre o quadrante 1, mas são 22px num
# quadrante de 320x240 e só aparece com o rato a mexer.
RECT = pygame.Rect(Config.SCR_WIDTH - _SIZE - _MARGIN, _MARGIN, _SIZE, _SIZE)

_BG = (10, 8, 30, 190)
_EDGE = (255, 221, 0, 220)   # o mesmo amarelo do convite
_MARK = (255, 255, 255, 235)


def hit(pos):
    """`pos` em coordenadas da superfície 640x480 (já convertido)."""
    return RECT.collidepoint(pos)


def draw(surface, is_fullscreen):
    """Desenha o botão sobre `surface` (a superfície 640x480 do jogo)."""
    plate = pygame.Surface(RECT.size, pygame.SRCALPHA)
    pygame.draw.rect(plate, _BG, plate.get_rect(), border_radius=5)
    pygame.draw.rect(plate, _EDGE, plate.get_rect(), width=1, border_radius=5)

    # Quatro cantos em L: para fora quando está em janela (vai encher), para
    # dentro quando já está cheio (vai encolher).
    arm, inset = 5, 5
    far = _SIZE - inset
    for cx, sx in ((inset, 1), (far, -1)):
        for cy, sy in ((inset, 1), (far, -1)):
            if is_fullscreen:
                # Setas viradas para dentro: o L arranca do canto e aponta ao centro.
                pygame.draw.line(plate, _MARK, (cx + sx * arm, cy), (cx + sx * arm, cy + sy * arm), 2)
                pygame.draw.line(plate, _MARK, (cx, cy + sy * arm), (cx + sx * arm, cy + sy * arm), 2)
            else:
                pygame.draw.line(plate, _MARK, (cx, cy), (cx + sx * arm, cy), 2)
                pygame.draw.line(plate, _MARK, (cx, cy), (cx, cy + sy * arm), 2)

    surface.blit(plate, RECT.topleft)
