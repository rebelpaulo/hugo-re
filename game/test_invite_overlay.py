"""Auto-teste mínimo do invite_overlay: corre sem display real (dummy
driver do SDL) e verifica que não rebenta com/sem o PNG do QR, e que o
convite muda mesmo alguma coisa no quadrante."""
import os
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import invite_overlay


def _pixels_differ(a, b):
    return pygame.image.tostring(a, "RGBA") != pygame.image.tostring(b, "RGBA")


def demo():
    pygame.init()
    pygame.display.set_mode((640, 480))

    # Todos os cenários usam um QR_PATH privado do teste — nunca o caminho
    # real (resources/images/qr_lobby.png), que outro worker pode estar a
    # escrever ao mesmo tempo. Isto torna o teste independente de esse
    # ficheiro já existir ou não neste ambiente.
    real_path = invite_overlay.QR_PATH
    missing_path = "resources/images/_test_qr_lobby_missing.png"
    tmp_path = "resources/images/_test_qr_lobby.png"
    assert not os.path.isfile(missing_path)

    try:
        invite_overlay.QR_PATH = missing_path

        # Sem QR (ficheiro não existe) — não pode rebentar.
        display = pygame.Surface((640, 480))
        baseline = display.copy()
        invite_overlay.draw(display, (0, 0), elapsed=0.0, queue_len=0)
        assert _pixels_differ(display, baseline), "draw() sem QR devia alterar o quadrante"

        # queue_len > 0 tem de produzir um resultado visualmente diferente de
        # queue_len == 0 (prova social a aparecer).
        display_a = pygame.Surface((640, 480))
        display_b = pygame.Surface((640, 480))
        invite_overlay.draw(display_a, (0, 0), elapsed=1.0, queue_len=0)
        invite_overlay.draw(display_b, (0, 0), elapsed=1.0, queue_len=5)
        assert _pixels_differ(display_a, display_b), "queue_len>0 devia desenhar algo a mais"

        # Simula o QR a aparecer a meio da execução (outro worker acaba de o
        # gerar).
        invite_overlay.QR_PATH = tmp_path
        qr_surf = pygame.Surface((21, 21))
        qr_surf.fill((0, 0, 0))
        pygame.image.save(qr_surf, tmp_path)
        invite_overlay._qr_loaded = False  # força novo load, como no arranque
        display_with_qr = pygame.Surface((640, 480))
        invite_overlay.draw(display_with_qr, (0, 0), elapsed=0.0, queue_len=0)
        assert invite_overlay._qr_image is not None, "devia ter carregado o QR criado agora"

        # mode="sip": convite diferente do de mode="web" (sem QR), mesmo
        # com um QR válido disponível — modo sip nunca o desenha.
        display_web = pygame.Surface((640, 480))
        display_sip = pygame.Surface((640, 480))
        invite_overlay.draw(display_web, (0, 0), elapsed=1.0, queue_len=0, mode="web")
        invite_overlay.draw(display_sip, (0, 0), elapsed=1.0, queue_len=0, mode="sip")
        assert _pixels_differ(display_web, display_sip), \
            "convite sip devia ser visualmente diferente do convite web"

        # mode="sip" também não pode rebentar sem QR nenhum (caso normal:
        # não há QR para gerar de todo quando o evento é só telefones).
        invite_overlay.QR_PATH = missing_path
        invite_overlay._qr_loaded = False
        display_sip_no_qr = pygame.Surface((640, 480))
        baseline_sip = display_sip_no_qr.copy()
        invite_overlay.draw(display_sip_no_qr, (0, 0), elapsed=0.0, queue_len=0, mode="sip")
        assert _pixels_differ(display_sip_no_qr, baseline_sip), "draw() em modo sip devia alterar o quadrante"

        # mode desconhecido ou ausente cai em "web" (retrocompatível) — o
        # próprio default já prova a metade "ausente"; aqui prova-se que um
        # valor não reconhecido também não rebenta e produz o mesmo resultado.
        invite_overlay.QR_PATH = missing_path
        invite_overlay._qr_loaded = False
        display_default = pygame.Surface((640, 480))
        display_unknown = pygame.Surface((640, 480))
        invite_overlay.draw(display_default, (0, 0), elapsed=2.0, queue_len=0)
        invite_overlay.draw(display_unknown, (0, 0), elapsed=2.0, queue_len=0, mode="qualquer-coisa")
        assert not _pixels_differ(display_default, display_unknown), \
            "mode desconhecido devia cair no comportamento de web, tal como a omissão do campo"
    finally:
        if os.path.isfile(tmp_path):
            os.remove(tmp_path)
        invite_overlay.QR_PATH = real_path
        invite_overlay._qr_loaded = False
        invite_overlay._qr_image = None

    pygame.quit()
    print("invite_overlay: OK")


if __name__ == "__main__":
    demo()
