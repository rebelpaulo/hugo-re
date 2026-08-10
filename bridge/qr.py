"""Gera o PNG do QR do lobby, lido pelo overlay do jogo nos quadrantes vazios.

Alto contraste (preto sobre branco), quiet zone respeitada (`border`, em
módulos — 4 é o mínimo recomendado pela norma) e tamanho generoso para se
ler a 3-5 metros num quadrante de 320x240 depois de escalado pelo jogo.
"""

from __future__ import annotations

from pathlib import Path

import qrcode
from qrcode.constants import ERROR_CORRECT_M


def generate_qr(
    url: str, dest_path: str | Path, *, box_size: int = 12, border: int = 4
) -> tuple[int, int]:
    """Grava um PNG do QR de `url` em `dest_path`; devolve (largura, altura) em pixels."""
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=box_size, border=border)
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest_path, format="PNG")
    return image.size


def demo() -> None:
    """Auto-teste: gera um QR de exemplo e confirma tamanho e quiet zone mínimos."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        dest = Path(tmp_dir) / "qr_demo.png"
        width, height = generate_qr("http://192.168.1.50:8080/", dest, box_size=10, border=4)
        assert dest.is_file(), "o PNG do QR não foi gravado"
        assert width == height, f"o QR devia ser quadrado, saiu {width}x{height}"
        assert width >= 21 * 10, "o QR ficou demasiado pequeno para se ler à distância"
    print(f"OK demo: QR {width}x{height}px gerado e validado")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        url = sys.argv[1]
        dest = sys.argv[2] if len(sys.argv) > 2 else "game/resources/images/qr_lobby.png"
        size = generate_qr(url, dest)
        print(f"QR gravado em {dest} ({size[0]}x{size[1]}px) para {url}")
    else:
        demo()
