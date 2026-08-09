"""Convite para quadrantes sem jogador — um por `input_mode` (ver
bridge/config.yaml e game/udp_input.py).

Um quadrante sem jogador deixa de ser só o vídeo de attract a correr — passa
a ter, por cima, um convite a piscar. É o principal canal de recrutamento do
ecrã: quem passa vê convites, não vídeo parado.

    mode="web" (omissão) — "À ESPERA DE JOGADOR · LIGA-TE JÁ!" com QR. É o
    convite de sempre; QR geral, aponta para o lobby, não para este
    quadrante específico.
    mode="sip" — o evento é só telefones físicos da sala (não há QR nenhum
    no ecrã grande neste modo, ninguém haveria de o escanear): "À ESPERA DE
    JOGADOR · PEGA NUM TELEFONE", sem QR nenhum.

O QR é gerado por outro processo para resources/images/qr_lobby.png. Este
módulo tem de aguentar-se sem esse ficheiro (ainda pode não ter sido
gerado), tal como o resto do jogo se aguenta sem sprites do scoreboard:
mostra o convite na mesma, sem QR.

Legibilidade a 3-5 metros manda sobre tudo: texto grande, contraste alto,
zona neutra à volta do QR quando existe. A animação de pulsar é só um brilho
subtil — em modo web à volta do QR, em modo sip à volta do próprio texto —
o texto e o QR ficam sempre nítidos e parados, para não estorvar quem está a
jogar ao lado nem prejudicar a leitura do código.
"""
import math
import os

import pygame
import pygame.freetype

QUAD_W, QUAD_H = 320, 240

QR_PATH = "resources/images/qr_lobby.png"
QR_SIZE = 150  # pedido: pelo menos ~140px no quadrante 320x240

# Placa por trás do texto. Não é fundo de quadrante: o vídeo de attract corre
# por trás e tem de continuar a ver-se (ver `_plate`). Mais opaca do que o
# antigo fundo de ecrã cheio, porque agora só tem de garantir contraste na
# faixa onde há letras — e a letra por cima de vídeo a mexer precisa disso.
_PLATE_COLOR = (10, 8, 30, 205)
_TITLE_COLOR = (255, 221, 0)     # amarelo néon, ar de noventista
_SUB_COLOR = (255, 255, 255)
_QUEUE_COLOR = (0, 229, 255)     # ciano
_GLOW_COLOR = (255, 221, 0)
_QUIET_ZONE_COLOR = (255, 255, 255)

_title_font = None
_sub_font = None
_queue_font = None
_qr_image = None
_qr_loaded = False


def _load_fonts():
    global _title_font, _sub_font, _queue_font
    if _title_font is not None:
        return
    # "Impact" dá o ar de letreiro noventista; se não existir no sistema o
    # pygame cai sozinho para um substituto — não rebenta.
    _title_font = pygame.freetype.SysFont("Impact,Arial", 21, bold=True)
    _sub_font = pygame.freetype.SysFont("Arial", 14, bold=True)
    _queue_font = pygame.freetype.SysFont("Arial", 15, bold=True)


def _load_qr():
    """Carrega o QR uma única vez. Devolve None se o ficheiro ainda não
    existir (outro worker está a gerá-lo) — sem rebentar."""
    global _qr_image, _qr_loaded
    if _qr_loaded:
        return _qr_image
    _qr_loaded = True
    if os.path.isfile(QR_PATH):
        try:
            img = pygame.image.load(QR_PATH).convert_alpha()
            _qr_image = pygame.transform.smoothscale(img, (QR_SIZE, QR_SIZE))
        except pygame.error:
            _qr_image = None
    return _qr_image


def _plate(surface, rect, pad_x=10, pad_y=6):
    """Placa escura arredondada por trás de um bocado de texto.

    Antes o convite pintava o quadrante todo de escuro; agora só escurece a
    faixa que tem letras, para o vídeo de attract continuar visível à volta.
    """
    plate = pygame.Rect(rect.x - pad_x, rect.y - pad_y,
                        rect.width + pad_x * 2, rect.height + pad_y * 2)
    surf = pygame.Surface(plate.size, pygame.SRCALPHA)
    pygame.draw.rect(surf, _PLATE_COLOR, surf.get_rect(), border_radius=8)
    surface.blit(surf, plate.topleft)


def _draw_centered(surface, font, text, color, y):
    rect = font.get_rect(text)
    x = (QUAD_W - rect.width) // 2
    _plate(surface, pygame.Rect(x, y, rect.width, rect.height))
    font.render_to(surface, (x, y), text, color)
    return rect.height


def draw(display, position, elapsed, queue_len=0, mode="web"):
    """Desenha o convite sobre o quadrante 320x240 em `position` de `display`.

    elapsed: segundos monótonos desde o arranque, só para a animação.
    queue_len: se > 0, mostra "N NA FILA" (prova social; só existe fila web).
    mode: "web" (omissão) desenha o convite de sempre, com QR. "sip" desenha
    o convite sem QR (evento só com telefones da sala) — qualquer outro
    valor cai em "web", o mesmo comportamento de sempre.
    """
    _load_fonts()

    # Superfície transparente: o que fica escuro é só o que se pinta por baixo
    # do texto e do QR (ver `_plate`). O vídeo de attract vê-se em todo o
    # resto do quadrante.
    panel = pygame.Surface((QUAD_W, QUAD_H), pygame.SRCALPHA)

    if mode == "sip":
        _draw_sip_invite(panel, elapsed)
    else:
        _draw_web_invite(panel, elapsed, queue_len)

    display.blit(panel, position)


def _draw_web_invite(panel, elapsed, queue_len):
    """Convite de sempre: título, "LIGA-TE JÁ!" e o QR do lobby (se já
    tiver sido gerado)."""
    qr = _load_qr()

    y = 10
    y += _draw_centered(panel, _title_font, "À ESPERA DE JOGADOR", _TITLE_COLOR, y) + 4
    y += _draw_centered(panel, _sub_font, "LIGA-TE JÁ!", _SUB_COLOR, y) + 10

    qr_y = y
    if qr is not None:
        qr_x = (QUAD_W - QR_SIZE) // 2

        # Brilho pulsante devagar (~2.4s de período) à volta do QR — chama a
        # atenção sem mexer no texto nem no próprio QR, que ficam parados.
        pulse = (math.sin(elapsed * 2.6) + 1) / 2
        glow_pad = 8
        glow_rect = pygame.Rect(qr_x - glow_pad, qr_y - glow_pad,
                                 QR_SIZE + glow_pad * 2, QR_SIZE + glow_pad * 2)
        glow_surf = pygame.Surface(glow_rect.size, pygame.SRCALPHA)
        pygame.draw.rect(glow_surf, (*_GLOW_COLOR, int(80 + 90 * pulse)),
                          glow_surf.get_rect(), border_radius=10)
        panel.blit(glow_surf, glow_rect.topleft)

        # Zona neutra branca à volta do QR — sem ela um scanner pode falhar.
        quiet_pad = 10
        quiet_rect = pygame.Rect(qr_x - quiet_pad, qr_y - quiet_pad,
                                  QR_SIZE + quiet_pad * 2, QR_SIZE + quiet_pad * 2)
        pygame.draw.rect(panel, _QUIET_ZONE_COLOR, quiet_rect, border_radius=6)
        panel.blit(qr, (qr_x, qr_y))
        y = qr_y + QR_SIZE + 14
    else:
        # Sem QR ainda — o convite continua legível sem ele.
        y = qr_y + 6

    if queue_len > 0:
        _draw_centered(panel, _queue_font, f"{queue_len} NA FILA", _QUEUE_COLOR, y)


def _draw_sip_invite(panel, elapsed):
    """Convite sem QR: o evento é só telefones físicos da sala, não há QR
    nenhum no ecrã grande neste modo — o brilho que no convite web pulsa à
    volta do QR pulsa aqui à volta do próprio texto, para continuar a
    chamar a atenção de quem passa."""
    y = 60
    y += _draw_centered(panel, _title_font, "À ESPERA DE JOGADOR", _TITLE_COLOR, y) + 20

    sub_text = "PEGA NUM TELEFONE"
    sub_rect = _sub_font.get_rect(sub_text)
    sub_x = (QUAD_W - sub_rect.width) // 2

    pulse = (math.sin(elapsed * 2.6) + 1) / 2
    glow_pad = 14
    glow_rect = pygame.Rect(sub_x - glow_pad, y - glow_pad,
                             sub_rect.width + glow_pad * 2, sub_rect.height + glow_pad * 2)
    glow_surf = pygame.Surface(glow_rect.size, pygame.SRCALPHA)
    pygame.draw.rect(glow_surf, (*_GLOW_COLOR, int(70 + 80 * pulse)),
                      glow_surf.get_rect(), border_radius=10)
    panel.blit(glow_surf, glow_rect.topleft)

    # Placa por baixo do brilho: sem fundo de quadrante, isto é o que garante
    # que a letra se lê por cima do vídeo de attract a mexer.
    _plate(panel, pygame.Rect(sub_x, y, sub_rect.width, sub_rect.height))
    _sub_font.render_to(panel, (sub_x, y), sub_text, _SUB_COLOR)
