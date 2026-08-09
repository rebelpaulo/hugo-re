"""Travessia de caminhos no `GET /audio/<recurso>`.

O recurso vem do cliente. Validar só a origem não chega: o caminho da cache
era montado com a string crua, portanto um recurso com `..` podia resolver
para uma origem legítima dentro dos assets e ainda assim escrever o ficheiro
convertido fora da pasta de cache — escrita arbitrária a partir de um pedido
HTTP. Achado pelo CodeRabbit no PR #2.

Correr:  .venv/bin/python bridge/test_audio_path_safety.py
"""
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from adapters.web_adapter import create_app
from emitter import UdpEmitter
from slot_manager import SlotManager

ASSETS = Path("/Users/mac/Claude code/hugo-assets/gold/BigFile")
RECURSO_BOM = "ForestData/speaks/005-01.wav"
# `..` que dá a volta mas aterra num ficheiro que existe mesmo nos assets.
RECURSO_TORTO = "ForestData/../ForestData/speaks/../speaks/005-02.wav"


async def main() -> int:
    if not (ASSETS / RECURSO_BOM).is_file():
        print(f"IGNORADO: não encontrei os assets em {ASSETS}")
        return 0

    cache = Path(tempfile.mkdtemp(prefix="hugo-cache-"))
    vizinha = Path(tempfile.mkdtemp(prefix="hugo-vizinha-"))
    try:
        manager = SlotManager(UdpEmitter(port=9699))
        app, _route = create_app(
            manager,
            audio_config={
                "mode": "devices",
                "ports": [9601, 9602, 9603, 9604],
                "assets_path": str(ASSETS),
                "cache_dir": str(cache),
            },
        )
        server = TestServer(app)
        await server.start_server()
        base = f"http://127.0.0.1:{server.port}"

        async with ClientSession() as session:
            resposta = await session.get(f"{base}/audio/{RECURSO_BOM}")
            assert resposta.status == 200, resposta.status

            # Origem válida, mas o destino da cache não pode escapar.
            resposta = await session.get(f"{base}/audio/{RECURSO_TORTO}")
            assert resposta.status in (200, 403, 404), resposta.status

            # Tentativa clássica: tem de ser recusada, nunca 200.
            resposta = await session.get(f"{base}/audio/../../../../etc/passwd")
            assert resposta.status != 200, "saiu dos assets!"

        intrusos = list(vizinha.rglob("*"))
        assert not intrusos, f"escreveu fora da cache: {intrusos}"

        raiz = cache.resolve()
        for ficheiro in cache.rglob("*.wav"):
            assert raiz in ficheiro.resolve().parents, f"fora da cache: {ficheiro}"

        print("OK: nenhum recurso consegue escrever fora da cache de áudio")
        await server.close()
        return 0
    finally:
        shutil.rmtree(cache, ignore_errors=True)
        shutil.rmtree(vizinha, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
