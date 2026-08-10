"""O QR do convite tem de acompanhar o ficheiro em disco.

    ../.venv/bin/python test_invite_overlay.py     (a partir de game/)

Porque isto existe: o supervisor arranca o JOGO primeiro e o bridge a seguir
(`scripts/macos/supervisor.sh`), e o bridge só escreve o QR uns 30 segundos
depois de arrancar — o tempo de levantar o túnel e de o endereço propagar
(`bridge/tunnel.py`). Uma leitura única no jogo fixava o QR da sessão
anterior, de um túnel já morto, e punha-o no ecrã grande a noite inteira.
Ninguém dava por isso a não ser um convidado a queixar-se de que "o código não
faz nada".
"""
import os
import sys
import tempfile

import pygame

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
pygame.init()
pygame.display.set_mode((640, 480))

import invite_overlay as ov  # noqa: E402  (precisa do display já criado)


def escreve_qr(caminho, cor):
    """Um PNG pequeno de cor sólida a fazer de QR — o que se está a testar é a
    releitura, não o código de barras."""
    superficie = pygame.Surface((60, 60))
    superficie.fill(cor)
    pygame.image.save(superficie, caminho)


def cor_do_meio(imagem):
    return tuple(imagem.get_at((ov.QR_SIZE // 2, ov.QR_SIZE // 2))[:3])


def repoe_estado():
    ov._qr_image = None
    ov._qr_signature = None
    ov._qr_next_check = 0.0


with tempfile.TemporaryDirectory() as tmp:
    caminho = os.path.join(tmp, "qr_lobby.png")
    ov.QR_PATH = caminho
    relogio = 1000.0

    # 1. Sem ficheiro nenhum: devolve None e NÃO fixa essa ausência.
    repoe_estado()
    assert ov._load_qr(now=relogio) is None, "sem ficheiro devia devolver None"
    print("OK 1: sem ficheiro em disco, devolve None sem rebentar")

    # 2. O bridge escreve o QR depois de o jogo já estar a desenhar.
    escreve_qr(caminho, (255, 0, 0))
    relogio += ov.QR_RECHECK_SECONDS
    imagem = ov._load_qr(now=relogio)
    assert imagem is not None, "não apanhou o QR que apareceu depois do arranque"
    assert cor_do_meio(imagem) == (255, 0, 0), cor_do_meio(imagem)
    print("OK 2: QR que aparece DEPOIS do arranque do jogo é apanhado")

    # 3. Entre verificações não se toca no disco — é o que evita ler a imagem
    #    a 30 fps vezes 4 quadrantes.
    escreve_qr(caminho, (0, 0, 255))
    imagem = ov._load_qr(now=relogio + ov.QR_RECHECK_SECONDS / 2)
    assert cor_do_meio(imagem) == (255, 0, 0), "releu antes do tempo"
    print("OK 3: entre verificações não relê (poupa I/O por frame)")

    # 4. O caso que motivou tudo: o bridge reescreve o QR (endereço novo do
    #    túnel) e o ecrã grande tem de passar a mostrar esse.
    relogio += ov.QR_RECHECK_SECONDS * 2
    imagem = ov._load_qr(now=relogio)
    assert cor_do_meio(imagem) == (0, 0, 255), cor_do_meio(imagem)
    print("OK 4: QR reescrito pelo bridge substitui o antigo no ecrã")

    # 5. Ficheiro apagado a meio: volta a None, e reaparece quando voltar.
    os.remove(caminho)
    relogio += ov.QR_RECHECK_SECONDS
    assert ov._load_qr(now=relogio) is None
    escreve_qr(caminho, (0, 255, 0))
    relogio += ov.QR_RECHECK_SECONDS
    assert cor_do_meio(ov._load_qr(now=relogio)) == (0, 255, 0)
    print("OK 5: ficheiro apagado e reposto — acompanha nos dois sentidos")

    # 6. O convite desenha-se com e sem QR, sem levantar excepção.
    ecra = pygame.Surface((640, 480), pygame.SRCALPHA)
    ov.draw(ecra, (0, 0), 1.0, queue_len=3, mode="web")
    ov.draw(ecra, (320, 0), 1.0, queue_len=0, mode="sip")
    os.remove(caminho)
    ov._qr_next_check = 0.0
    ov.draw(ecra, (0, 240), 1.0, queue_len=1, mode="web")
    print("OK 6: desenha com QR, sem QR, e em modo sip")

print("Todos os cenários passaram.")
