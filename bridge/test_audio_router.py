"""Testes corríveis sem framework: .venv/bin/python bridge/test_audio_router.py

Sockets UDP e servidor aiohttp a sério em portas efémeras de 127.0.0.1 — nada
de mocks de rede, tal como os outros testes do bridge. Usa ficheiros reais de
`hugo-assets/gold/BigFile` para provar a conversão de áudio.
"""

from __future__ import annotations

import asyncio
import io
import json
import socket
import tempfile
import time
import wave
from pathlib import Path

from aiohttp import ClientSession, web

from adapters.web_adapter import _tv_show_ending_resources, build_audio_manifest, create_app
from audio_router import AudioRouter
from emitter import UdpEmitter
from slot_manager import SlotManager


async def resposta_util(ws):
    """Lê a próxima mensagem, saltando o {"type":"config"} que o servidor
    envia logo na ligação. O modo de entrada é definido pela produção antes
    do evento, por isso chega antes de qualquer hello."""
    while True:
        raw = await ws.receive()
        message = json.loads(raw.data)
        if message.get("type") != "config":
            return message



REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_PATH = REPO_ROOT.parent / "hugo-assets" / "gold" / "BigFile"
RESOURCES_PATH = REPO_ROOT / "game" / "resources"

assert ASSETS_PATH.is_dir(), (
    f"Assets do jogo não encontrados em {ASSETS_PATH} — ajusta ASSETS_PATH neste teste"
)
assert RESOURCES_PATH.is_dir(), f"Recursos do jogo não encontrados em {RESOURCES_PATH}"


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


async def start_server(manager: SlotManager, audio_config: dict | None = None):
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
            "resources_path": str(RESOURCES_PATH),
            "cache_dir": cache_dir,
        }
        runner, _route, http_port = await start_server(manager, audio_config)
        try:
            async with ClientSession() as session:
                ws = await session.ws_connect(f"http://127.0.0.1:{http_port}/ws")
                await ws.send_json({"type": "hello", "mode": "web"})
                slot_msg = await resposta_util(ws)
                assert slot_msg == {"type": "slot", "player": 0, "color": "blue"}, slot_msg

                response, elapsed = await udp_request_async(
                    audio_ports[0],
                    {"cmd": "PLAY", "resource": "ForestData/speaks/005-01.wav", "loops": 0, "volume": 1.0},
                )
                assert "instance_id" in response, response

                audio_msg = await resposta_util(ws)
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
            "resources_path": str(RESOURCES_PATH),
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

            # A segunda raiz é o áudio que acompanha os vídeos do programa
            # de TV. A resposta HTTP, e não só o ficheiro na árvore, tem de
            # ser um WAV que o browser consiga descodificar.
            tv_resource = "audio_for_videos/pt/attract_demo.wav"
            async with ClientSession() as session:
                tv_resp = await session.get(f"http://127.0.0.1:{http_port}/audio/{tv_resource}")
                assert tv_resp.status == 200, tv_resp.status
                tv_body = await tv_resp.read()
            with wave.open(io.BytesIO(tv_body), "rb") as wav_file:
                assert wav_file.getsampwidth() == 2
                assert wav_file.getframerate() == 44100
                assert wav_file.getnchannels() == 1
            print(f"OK test_audio_http_serves_tv_show_resource ({len(tv_body)} bytes, WAV válido)")
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
# Prova: o manifesto de pré-carga cobre os minijogos e o programa de TV.
# ---------------------------------------------------------------------------

async def test_manifest_lists_all_game_audio_resources() -> None:
    manifest = build_audio_manifest(REPO_ROOT)
    assert any(r.startswith("ForestData/") for r in manifest), manifest
    assert any(r.startswith("RopeOutroData/") for r in manifest), manifest
    tv_show_resources = [r for r in manifest if r.startswith("audio_for_videos/pt/")]
    assert len(tv_show_resources) == 6, tv_show_resources
    assert len(manifest) == len(set(manifest)), "manifesto tem duplicados"
    total_bytes = sum(
        ((RESOURCES_PATH if r.startswith("audio_for_videos/") else ASSETS_PATH) / r).stat().st_size
        for r in manifest
    )
    print(
        f"OK test_manifest_lists_all_game_audio_resources "
        f"({len(manifest)} recursos, 6 do programa de TV, {total_bytes / 1e6:.2f} MB no original)"
    )


async def _next_game_event(listener: socket.socket) -> dict:
    """Lê do socket que faz de "jogo" para eventos de jogador (ver
    `new_manager()`), saltando as mensagens `slots` que o `SlotManager`
    também manda para lá — mesmo canal, mesmo espírito de
    `test_web_adapter.py:test_press_reaches_game`."""
    loop = asyncio.get_running_loop()
    for _ in range(10):
        data, _addr = await loop.run_in_executor(None, listener.recvfrom, 4096)
        event = json.loads(data)
        if event.get("type") != "slots":
            return event
    raise AssertionError("só chegaram mensagens 'slots' — nenhum evento de jogador")


# ---------------------------------------------------------------------------
# Prova do P0: uma sessão que desaparece sem `hungup` explícito (página
# fechada à bruta, sem `{"type":"hangup"}`) tinha de repor o quadrante na
# mesma — sem isso o jogo fica preso a meio da partida anterior e o lugar
# seguinte apanha um quadrante bloqueado (ver bridge/slot_manager.py,
# `_release_active`, e o relato do cliente no ticket).
#
# Honestidade sobre "o jogo a correr": o jogo real (`game/game.py`) só ouve
# UDP em 127.0.0.1:9100, porta fixa no código (`game/udp_input.py`, sem
# argumento para mudar) — e está já ocupada por uma sessão real em curso
# nesta máquina (supervisor.sh + telemóvel ligado, ver `ps`), que não se
# tocou. Por isso "o jogo" aqui é o mesmo duplo usado em todo o resto deste
# ficheiro e em `test_web_adapter.py` (`test_press_reaches_game`): um socket
# UDP real, a escutar a sério — não um mock — exactamente onde o jogo real
# escutaria.
# ---------------------------------------------------------------------------

async def test_disconnect_without_hangup_resets_quadrant_via_synthetic_hungup() -> None:
    listener = free_udp_listener()
    emitter = UdpEmitter(*listener.getsockname())
    manager = SlotManager(emitter)
    runner, _route, http_port = await start_server(manager)
    try:
        async with ClientSession() as session:
            ws1 = await session.ws_connect(f"http://127.0.0.1:{http_port}/ws")
            await ws1.send_json({"type": "hello", "mode": "web"})
            slot_msg = await resposta_util(ws1)
            assert slot_msg == {"type": "slot", "player": 0, "color": "blue"}, slot_msg

            await ws1.send_json({"type": "offhook"})
            event = await _next_game_event(listener)
            assert event == {"player": 0, "event": "offhook"}, event

            # Fecha a sessão à bruta: nunca manda {"type":"hangup"}.
            await ws1.close()

            hungup_event = await _next_game_event(listener)
            assert hungup_event == {"player": 0, "event": "hungup"}, hungup_event
            print(f"OK P0: jogo recebeu {hungup_event} sem hangup explícito da sessão")

            # Sessão nova no mesmo lugar consegue jogar.
            ws2 = await session.ws_connect(f"http://127.0.0.1:{http_port}/ws")
            await ws2.send_json({"type": "hello", "mode": "web"})
            slot_msg2 = await resposta_util(ws2)
            assert slot_msg2 == {"type": "slot", "player": 0, "color": "blue"}, slot_msg2

            await ws2.send_json({"type": "offhook"})
            event2 = await _next_game_event(listener)
            assert event2 == {"player": 0, "event": "offhook"}, event2
            print("OK P0: sessão nova no lugar 0 joga normalmente")

            await ws2.close()
    finally:
        await runner.cleanup()
        listener.close()


# ---------------------------------------------------------------------------
# Prova do fim de partida: um PLAY do som de fim (`you_lost.wav`, derivado do
# código do jogo — nunca escrito à mão aqui) na porta de um jogador liberta o
# lugar, avisa a sessão com `{"type":"finished"}`, e a partir daí as teclas
# dessa sessão deixam de chegar ao jogo.
# ---------------------------------------------------------------------------

async def test_match_end_detected_via_you_lost_audio() -> None:
    ending_resources = _tv_show_ending_resources(REPO_ROOT)
    assert ending_resources, "sem recursos de fim de partida derivados do jogo — ver _tv_show_ending_resources"
    ending_resource = sorted(ending_resources)[0]
    assert ending_resource.endswith("you_lost.wav"), ending_resource

    listener = free_udp_listener()
    emitter = UdpEmitter(*listener.getsockname())
    manager = SlotManager(emitter)
    audio_ports = [free_port() for _ in range(4)]
    with tempfile.TemporaryDirectory() as cache_dir:
        audio_config = {
            "mode": "devices",
            "ports": audio_ports,
            "assets_path": str(ASSETS_PATH),
            "resources_path": str(RESOURCES_PATH),
            "cache_dir": cache_dir,
        }
        runner, _route, http_port = await start_server(manager, audio_config)
        try:
            async with ClientSession() as session:
                ws = await session.ws_connect(f"http://127.0.0.1:{http_port}/ws")
                await ws.send_json({"type": "hello", "mode": "web"})
                slot_msg = await resposta_util(ws)
                assert slot_msg == {"type": "slot", "player": 0, "color": "blue"}, slot_msg

                # Simula o jogo a tocar o som de fim de partida no jogador 0
                # (game/tv_show/ending.py — toca uma única vez, só ao entrar
                # no estado de fim de jogo).
                response, _elapsed = await udp_request_async(
                    audio_ports[0],
                    {"cmd": "PLAY", "resource": ending_resource, "loops": 0, "volume": 1.0},
                )
                assert "instance_id" in response, response

                seen_types = set()
                finished_msg = None
                for _ in range(5):
                    message = await resposta_util(ws)
                    seen_types.add(message.get("type"))
                    if message.get("type") == "finished":
                        finished_msg = message
                        break
                assert finished_msg == {"type": "finished"}, (finished_msg, seen_types)
                assert "audio" in seen_types, (
                    f"o som de fim de partida em si tem de chegar também: {seen_types}"
                )
                print(f"OK fim de partida detectado a partir de {ending_resource}: {finished_msg}")

                assert manager.occupied == [], manager.occupied
                # release_player usa o mesmo caminho do P0 (_release_active):
                # o mesmo canal UDP do "jogo" recebe o hungup sintético que
                # repõe o quadrante — drena-o antes de procurar teclas soltas.
                released_event = await _next_game_event(listener)
                assert released_event == {"player": 0, "event": "hungup"}, released_event
                print(f"OK lugar libertado, quadrante reposto: jogo recebeu {released_event}")

                # As teclas desta sessão (já "idle" no SlotManager) deixam de passar.
                await ws.send_json({"type": "press", "key": "5"})
                try:
                    stray = await asyncio.wait_for(_next_game_event(listener), timeout=0.3)
                except asyncio.TimeoutError:
                    stray = None
                assert stray is None, f"tecla de sessão já terminada chegou ao jogo: {stray}"
                print("OK teclas da sessão terminada já não chegam ao jogo")

                # Uma sessão nova entra normalmente no lugar libertado.
                ws2 = await session.ws_connect(f"http://127.0.0.1:{http_port}/ws")
                await ws2.send_json({"type": "hello", "mode": "web"})
                slot_msg2 = await resposta_util(ws2)
                assert slot_msg2 == {"type": "slot", "player": 0, "color": "blue"}, slot_msg2
                print("OK sessão nova entra no lugar libertado pelo fim de partida")

                await ws.close()
                await ws2.close()
        finally:
            await runner.cleanup()
            listener.close()


async def main() -> None:
    await test_play_without_session_is_fast()
    await test_stop_without_session_is_fast()
    await test_end_to_end_play_reaches_websocket()
    await test_audio_http_serves_converted_pcm16()
    await test_pa_mode_falls_back_without_blocking()
    await test_manifest_lists_all_game_audio_resources()
    await test_disconnect_without_hangup_resets_quadrant_via_synthetic_hungup()
    await test_match_end_detected_via_you_lost_audio()
    print("OK 8 grupos de testes")


if __name__ == "__main__":
    asyncio.run(main())
