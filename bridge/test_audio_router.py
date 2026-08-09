"""Testes corríveis sem framework: .venv/bin/python bridge/test_audio_router.py

Sockets UDP e servidor aiohttp a sério em portas efémeras de 127.0.0.1 — nada
de mocks de rede, tal como os outros testes do bridge. Usa ficheiros reais de
`hugo-assets/gold/BigFile` para provar a conversão de áudio.
"""

from __future__ import annotations

import asyncio
import json
import socket
import tempfile
import time
import wave
from pathlib import Path

from aiohttp import ClientSession, web

from adapters.web_adapter import build_audio_manifest, create_app
from audio_router import AudioRouter
from emitter import UdpEmitter
from slot_manager import SlotManager


REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_PATH = REPO_ROOT.parent / "hugo-assets" / "gold" / "BigFile"

assert ASSETS_PATH.is_dir(), (
    f"Assets do jogo não encontrados em {ASSETS_PATH} — ajusta ASSETS_PATH neste teste"
)


def free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def free_udp_listener() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(2.0)
    return sock


def udp_request(port: int, payload: dict, timeout: float = 2.0) -> tuple[dict, float]:
    """Manda um comando UDP ao router e mede o tempo até à resposta — o mesmo
    que `game/audio_helper.py:24` mede com o seu `settimeout(1.0)`.

    Bloqueante de propósito: é exactamente o que o jogo faz (num processo
    separado). Chamar isto directamente dentro de uma coroutine do MESMO
    processo pararia o loop de eventos e nunca chegaria a resposta — por isso
    os testes correm-no sempre via `run_in_executor` (ver `udp_request_async`)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        start = time.monotonic()
        sock.sendto(json.dumps(payload).encode("utf-8"), ("127.0.0.1", port))
        data, _ = sock.recvfrom(4096)
        elapsed = time.monotonic() - start
        return json.loads(data.decode("utf-8")), elapsed
    finally:
        sock.close()


async def udp_request_async(port: int, payload: dict, timeout: float = 2.0) -> tuple[dict, float]:
    """`udp_request` correndo num thread do executor, para não bloquear o
    próprio loop de eventos que serve o `AudioRouter` sob teste."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, udp_request, port, payload, timeout)


async def start_server(manager: SlotManager, audio_config: dict):
    app, route = create_app(manager, audio_config=audio_config)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, route, port


def new_manager() -> SlotManager:
    listener = free_udp_listener()
    emitter = UdpEmitter(*listener.getsockname())
    return SlotManager(emitter)


# ---------------------------------------------------------------------------
# Prova: o jogo não bloqueia — mesmo sem nenhuma sessão ligada, a resposta é
# em milissegundos, não 1 segundo (game/audio_helper.py:24, settimeout(1.0)).
# ---------------------------------------------------------------------------

async def test_play_without_session_is_fast() -> None:
    ports = [free_port() for _ in range(4)]

    async def dispatch_never_delivers(player: int, message: dict) -> bool:
        return False  # como se não houvesse ninguém ligado naquele quadrante

    router = AudioRouter(ports, dispatch_never_delivers, mode="devices")
    await router.start()
    try:
        response, elapsed = await udp_request_async(
            ports[0],
            {"cmd": "PLAY", "resource": "ForestData/speaks/005-01.wav", "loops": 0, "volume": 1.0},
        )
        assert "instance_id" in response, response
        assert elapsed < 0.05, f"PLAY demorou {elapsed * 1000:.1f}ms — devia ser ms, não 1s"
        print(f"OK test_play_without_session_is_fast ({elapsed * 1000:.2f}ms)")
    finally:
        await router.stop()


async def test_stop_without_session_is_fast() -> None:
    ports = [free_port() for _ in range(4)]

    async def dispatch_never_delivers(player: int, message: dict) -> bool:
        return False

    router = AudioRouter(ports, dispatch_never_delivers, mode="devices")
    await router.start()
    try:
        response, elapsed = await udp_request_async(
            ports[0], {"cmd": "STOP", "instance_id": 42, "duration": 0}
        )
        assert response.get("success") is True, response
        assert elapsed < 0.05, f"STOP demorou {elapsed * 1000:.1f}ms — devia ser ms, não 1s"
        print(f"OK test_stop_without_session_is_fast ({elapsed * 1000:.2f}ms)")
    finally:
        await router.stop()


# ---------------------------------------------------------------------------
# Prova ponta a ponta: PLAY na porta do jogador 0 chega à sessão WebSocket
# ligada como jogador 0, com o recurso certo.
# ---------------------------------------------------------------------------

async def test_end_to_end_play_reaches_websocket() -> None:
    manager = new_manager()
    audio_ports = [free_port() for _ in range(4)]
    with tempfile.TemporaryDirectory() as cache_dir:
        audio_config = {
            "mode": "devices",
            "ports": audio_ports,
            "assets_path": str(ASSETS_PATH),
            "cache_dir": cache_dir,
        }
        runner, _route, http_port = await start_server(manager, audio_config)
        try:
            async with ClientSession() as session:
                ws = await session.ws_connect(f"http://127.0.0.1:{http_port}/ws")
                await ws.send_json({"type": "hello", "mode": "web"})
                slot_msg = json.loads((await ws.receive()).data)
                assert slot_msg == {"type": "slot", "player": 0, "color": "blue"}, slot_msg

                response, elapsed = await udp_request_async(
                    audio_ports[0],
                    {"cmd": "PLAY", "resource": "ForestData/speaks/005-01.wav", "loops": 0, "volume": 1.0},
                )
                assert "instance_id" in response, response

                audio_msg = json.loads((await ws.receive()).data)
                assert audio_msg == {
                    "type": "audio",
                    "action": "play",
                    "resource": "ForestData/speaks/005-01.wav",
                    "loops": 0,
                    "id": response["instance_id"],
                }, audio_msg
                await ws.close()
            print(
                f"OK test_end_to_end_play_reaches_websocket "
                f"(resposta UDP em {elapsed * 1000:.2f}ms, mensagem: {audio_msg})"
            )
        finally:
            await runner.cleanup()


# ---------------------------------------------------------------------------
# Prova: os sons são servidos convertidos — 16 bits, mono, 44.1kHz — mesmo
# partindo de um `pcm_u8` a 22050Hz (o caso de risco apontado no ticket).
# ---------------------------------------------------------------------------

async def test_audio_http_serves_converted_pcm16() -> None:
    manager = new_manager()
    with tempfile.TemporaryDirectory() as cache_dir:
        audio_config = {
            "mode": "devices",
            "ports": [free_port() for _ in range(4)],
            "assets_path": str(ASSETS_PATH),
            "cache_dir": cache_dir,
        }
        runner, _route, http_port = await start_server(manager, audio_config)
        try:
            resource = "ForestData/sfx/atmos-lp.wav"  # original: pcm_u8, 22050Hz
            async with ClientSession() as session:
                resp = await session.get(f"http://127.0.0.1:{http_port}/audio/{resource}")
                assert resp.status == 200, resp.status
                body = await resp.read()

            cached_path = (Path(cache_dir) / resource).with_suffix(".wav")
            assert cached_path.is_file(), "conversão não ficou em cache"
            with wave.open(str(cached_path), "rb") as wav_file:
                assert wav_file.getsampwidth() == 2, f"esperava 16 bits, veio {wav_file.getsampwidth() * 8} bits"
                assert wav_file.getframerate() == 44100, f"esperava 44100Hz, veio {wav_file.getframerate()}"
                assert wav_file.getnchannels() == 1, f"esperava mono, veio {wav_file.getnchannels()} canais"
            print(f"OK test_audio_http_serves_converted_pcm16 ({len(body)} bytes servidos)")

            mtime_before = cached_path.stat().st_mtime
            async with ClientSession() as session:
                resp2 = await session.get(f"http://127.0.0.1:{http_port}/audio/{resource}")
                assert resp2.status == 200
            assert cached_path.stat().st_mtime == mtime_before, "reconverteu em vez de reusar a cache"
            print("OK test_audio_http_cache_not_repeated")
        finally:
            await runner.cleanup()


# ---------------------------------------------------------------------------
# Prova: o interruptor de recurso ("pa") também nunca bloqueia o jogo, mesmo
# com o audio-server local em baixo.
# ---------------------------------------------------------------------------

async def test_pa_mode_falls_back_without_blocking() -> None:
    ports = [free_port() for _ in range(4)]
    pa_ports = [free_port() for _ in range(4)]  # ninguém a escutar aqui de propósito

    async def dispatch_unused(player: int, message: dict) -> bool:
        raise AssertionError("modo pa não devia chamar dispatch (não vai para telemóveis)")

    router = AudioRouter(
        ports, dispatch_unused, mode="pa", pa_ports=pa_ports, pa_timeout=0.2
    )
    await router.start()
    try:
        response, elapsed = await udp_request_async(
            ports[0],
            {"cmd": "PLAY", "resource": "ForestData/speaks/005-01.wav", "loops": 0, "volume": 1.0},
            timeout=1.0,
        )
        assert "error" in response, response
        assert elapsed < 0.5, f"modo pa demorou {elapsed * 1000:.1f}ms com o audio-server em baixo"
        print(f"OK test_pa_mode_falls_back_without_blocking ({elapsed * 1000:.2f}ms)")
    finally:
        await router.stop()


# ---------------------------------------------------------------------------
# Prova: o manifesto de pré-carga cobre os dois minijogos implementados.
# ---------------------------------------------------------------------------

async def test_manifest_lists_forest_and_cave_resources() -> None:
    manifest = build_audio_manifest(REPO_ROOT)
    assert any(r.startswith("ForestData/") for r in manifest), manifest
    assert any(r.startswith("RopeOutroData/") for r in manifest), manifest
    assert len(manifest) == len(set(manifest)), "manifesto tem duplicados"
    total_bytes = sum((ASSETS_PATH / r).stat().st_size for r in manifest)
    print(
        f"OK test_manifest_lists_forest_and_cave_resources "
        f"({len(manifest)} recursos, {total_bytes / 1e6:.2f} MB no original)"
    )


async def main() -> None:
    await test_play_without_session_is_fast()
    await test_stop_without_session_is_fast()
    await test_end_to_end_play_reaches_websocket()
    await test_audio_http_serves_converted_pcm16()
    await test_pa_mode_falls_back_without_blocking()
    await test_manifest_lists_forest_and_cave_resources()
    print("OK 6 grupos de testes")


if __name__ == "__main__":
    asyncio.run(main())
