"""Testes corríveis sem framework: .venv/bin/python bridge/test_score_flow.py

Ponta a ponta, UDP + WebSocket a sério (aiohttp, portas efémeras de
127.0.0.1), tal como os outros testes do bridge — nada de mocks de rede.
Prova o ciclo completo pedido no ticket: partida termina -> pontuação chega
por UDP (game/score_report.py) -> sessão recebe "finished" (fim de partida
detectado no áudio, ver audio_router.py) -> nome submetido -> top10
devolvido com o nome lá dentro; a corrida entre a pontuação e o "finished"
nas duas ordens; o filtro de nomes; e o bloqueio depois do top10.
"""

from __future__ import annotations

import asyncio
import json
import socket
import tempfile
from pathlib import Path

from aiohttp import ClientSession, web

from adapters.web_adapter import _tv_show_ending_resources, create_app
from emitter import UdpEmitter
from slot_manager import SlotManager

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_PATH = REPO_ROOT.parent / "hugo-assets" / "gold" / "BigFile"
RESOURCES_PATH = REPO_ROOT / "game" / "resources"

assert ASSETS_PATH.is_dir(), (
    f"Assets do jogo não encontrados em {ASSETS_PATH} — ajusta ASSETS_PATH neste teste"
)

ENDING_RESOURCES = _tv_show_ending_resources(REPO_ROOT)
assert ENDING_RESOURCES, "sem recursos de fim de partida derivados do jogo"
ENDING_RESOURCE = sorted(ENDING_RESOURCES)[0]


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


def make_badwords(tmp_dir: Path) -> Path:
    path = tmp_dir / "badwords.txt"
    path.write_text("PUTA\nMERDA\n", encoding="utf-8")
    return path


async def udp_request_async(port: int, payload: dict, timeout: float = 2.0) -> dict:
    """Manda um PLAY fire-and-forget e espera a resposta do AudioRouter —
    mesmo caminho que `game/audio_helper.py` usa a sério."""
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        await loop.run_in_executor(None, sock.sendto, json.dumps(payload).encode("utf-8"), ("127.0.0.1", port))
        data, _addr = await loop.run_in_executor(None, sock.recvfrom, 4096)
        return json.loads(data)
    finally:
        sock.close()


def send_score_udp(port: int, player: int, score: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(json.dumps({"player": player, "score": score}).encode("utf-8"), ("127.0.0.1", port))
    finally:
        sock.close()


async def resposta_util(ws):
    """Lê a próxima mensagem, saltando "config" (ver test_audio_router.py)."""
    while True:
        raw = await ws.receive()
        message = json.loads(raw.data)
        if message.get("type") != "config":
            return message


async def wait_for_type(ws, wanted: str, tries: int = 8) -> dict:
    for _ in range(tries):
        message = await resposta_util(ws)
        if message.get("type") == wanted:
            return message
    raise AssertionError(f"nunca chegou {wanted!r} em {tries} mensagens")


async def start_server(tmp_dir: Path):
    listener = free_udp_listener()
    emitter = UdpEmitter(*listener.getsockname())
    manager = SlotManager(emitter)
    audio_ports = [free_port() for _ in range(4)]
    score_port = free_port()
    cache_dir = tmp_dir / "audio_cache"
    data_dir = tmp_dir / "data"
    audio_config = {
        "mode": "devices",
        "ports": audio_ports,
        "assets_path": str(ASSETS_PATH),
        "resources_path": str(RESOURCES_PATH),
        "cache_dir": str(cache_dir),
    }
    score_config = {
        "host": "127.0.0.1",
        "port": score_port,
        "data_dir": str(data_dir),
        "badwords_path": str(make_badwords(tmp_dir)),
    }
    app, _route = create_app(manager, audio_config=audio_config, score_config=score_config)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    http_port = site._server.sockets[0].getsockname()[1]
    return runner, listener, http_port, audio_ports, score_port


async def enter_and_finish_match(
    session, http_port, audio_ports, listener, *, score_before: int | None, score_after: int | None
):
    """Liga uma sessão web, ocupa o lugar 0, termina a partida (PLAY do som
    de fim de jogo), manda a pontuação antes ou depois disso consoante os
    argumentos. Devolve o WebSocket já depois do "finished" — já com o
    "hungup" sintético do fim de partida (release_player) drenado do socket
    que faz de "jogo", tal como test_audio_router.py já faz."""
    ws = await session.ws_connect(f"http://127.0.0.1:{http_port}/ws")
    await ws.send_json({"type": "hello", "mode": "web"})
    slot_msg = await resposta_util(ws)
    assert slot_msg == {"type": "slot", "player": 0, "color": "blue"}, slot_msg

    if score_before is not None:
        send_score_udp(SCORE_PORT_HOLDER["port"], 0, score_before)
        await asyncio.sleep(0.05)  # dá tempo ao UDP de ser processado antes do PLAY

    response = await udp_request_async(
        audio_ports[0], {"cmd": "PLAY", "resource": ENDING_RESOURCE, "loops": 0, "volume": 1.0}
    )
    assert "instance_id" in response, response

    finished_msg = await wait_for_type(ws, "finished")
    assert finished_msg == {"type": "finished"}, finished_msg

    released_event = await _next_game_event(listener)
    assert released_event == {"player": 0, "event": "hungup"}, released_event

    if score_after is not None:
        send_score_udp(SCORE_PORT_HOLDER["port"], 0, score_after)
        await asyncio.sleep(0.05)  # a corrida: a pontuação chega DEPOIS do "finished"

    return ws


# Pequeno truque para passar a porta de pontuação às funções auxiliares
# acima sem replicar `start_server` inteiro em cada cenário.
SCORE_PORT_HOLDER: dict[str, int] = {}


# ---------------------------------------------------------------------------
# 1 e 2: prova ponta a ponta + prova da corrida nas duas ordens.
# ---------------------------------------------------------------------------

async def test_score_before_finished_reaches_top10() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        runner, listener, http_port, audio_ports, score_port = await start_server(Path(tmp))
        SCORE_PORT_HOLDER["port"] = score_port
        try:
            async with ClientSession() as session:
                ws = await enter_and_finish_match(
                    session, http_port, audio_ports, listener, score_before=4200, score_after=None
                )
                await ws.send_json({"type": "name", "name": "hugo"})
                top10_msg = await wait_for_type(ws, "top10")
                assert top10_msg["own"] == {"name": "HUGO", "score": 4200}, top10_msg
                assert {"name": "HUGO", "score": 4200} in top10_msg["entries"], top10_msg
                await ws.close()
                print(f"OK 1: pontuação ANTES do finished chega ao top10: {top10_msg['own']}")
        finally:
            await runner.cleanup()
            listener.close()


async def test_score_after_finished_reaches_top10() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        runner, listener, http_port, audio_ports, score_port = await start_server(Path(tmp))
        SCORE_PORT_HOLDER["port"] = score_port
        try:
            async with ClientSession() as session:
                ws = await enter_and_finish_match(
                    session, http_port, audio_ports, listener, score_before=None, score_after=3100
                )
                await ws.send_json({"type": "name", "name": "ana"})
                top10_msg = await wait_for_type(ws, "top10")
                assert top10_msg["own"] == {"name": "ANA", "score": 3100}, top10_msg
                await ws.close()
                print(f"OK 2: pontuação DEPOIS do finished também chega ao top10: {top10_msg['own']}")
        finally:
            await runner.cleanup()
            listener.close()


# ---------------------------------------------------------------------------
# 3: prova do filtro — um nome da lista é substituído, um nome válido passa.
# ---------------------------------------------------------------------------

async def test_badword_name_becomes_placeholder() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        runner, listener, http_port, audio_ports, score_port = await start_server(Path(tmp))
        SCORE_PORT_HOLDER["port"] = score_port
        try:
            async with ClientSession() as session:
                ws = await enter_and_finish_match(
                    session, http_port, audio_ports, listener, score_before=1000, score_after=None
                )
                await ws.send_json({"type": "name", "name": "xputax"})
                top10_msg = await wait_for_type(ws, "top10")
                assert top10_msg["own"] == {"name": "???", "score": 1000}, top10_msg
                await ws.close()
                print("OK 3a: nome da lista de filtro vira '???'")
        finally:
            await runner.cleanup()
            listener.close()


async def test_valid_name_passes_unchanged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        runner, listener, http_port, audio_ports, score_port = await start_server(Path(tmp))
        SCORE_PORT_HOLDER["port"] = score_port
        try:
            async with ClientSession() as session:
                ws = await enter_and_finish_match(
                    session, http_port, audio_ports, listener, score_before=2500, score_after=None
                )
                await ws.send_json({"type": "name", "name": "hugo re"})
                top10_msg = await wait_for_type(ws, "top10")
                assert top10_msg["own"] == {"name": "HUGO RE", "score": 2500}, top10_msg
                await ws.close()
                print("OK 3b: nome válido passa sem alterações (maiúsculas)")
        finally:
            await runner.cleanup()
            listener.close()


# ---------------------------------------------------------------------------
# 4: sem patch do jogo (pontuação nunca chega) — degrada, não parte.
# ---------------------------------------------------------------------------

async def test_missing_score_degrades_gracefully() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        runner, listener, http_port, audio_ports, score_port = await start_server(Path(tmp))
        SCORE_PORT_HOLDER["port"] = score_port
        try:
            async with ClientSession() as session:
                ws = await enter_and_finish_match(
                    session, http_port, audio_ports, listener, score_before=None, score_after=None
                )
                await ws.send_json({"type": "name", "name": "hugo"})
                top10_msg = await wait_for_type(ws, "top10")
                assert top10_msg["own"] is None, top10_msg
                assert top10_msg["entries"] == [], top10_msg
                await ws.close()
                print("OK 4: sem pontuação (jogo sem patch), top10 aparece na mesma sem entrada própria")
        finally:
            await runner.cleanup()
            listener.close()


# ---------------------------------------------------------------------------
# 5: prova do bloqueio — depois do top10 a sessão não volta a jogar; uma
#    ligação nova entra na fila/lugar normalmente.
# ---------------------------------------------------------------------------

async def _next_game_event(listener: socket.socket) -> dict:
    loop = asyncio.get_running_loop()
    for _ in range(10):
        data, _addr = await loop.run_in_executor(None, listener.recvfrom, 4096)
        event = json.loads(data)
        if event.get("type") != "slots":
            return event
    raise AssertionError("só chegaram mensagens 'slots'")


async def test_blocked_after_top10_new_session_plays_normally() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        runner, listener, http_port, audio_ports, score_port = await start_server(Path(tmp))
        SCORE_PORT_HOLDER["port"] = score_port
        try:
            async with ClientSession() as session:
                ws = await enter_and_finish_match(
                    session, http_port, audio_ports, listener, score_before=1500, score_after=None
                )
                await ws.send_json({"type": "name", "name": "bloq"})
                await wait_for_type(ws, "top10")

                # A sessão bloqueada não consegue voltar a jogar.
                await ws.send_json({"type": "press", "key": "5"})
                try:
                    stray = await asyncio.wait_for(_next_game_event(listener), timeout=0.3)
                except asyncio.TimeoutError:
                    stray = None
                assert stray is None, f"tecla de sessão já terminada chegou ao jogo: {stray}"
                print("OK 5a: depois do top10, teclas dessa sessão já não chegam ao jogo")

                # Uma ligação nova entra no lugar libertado, normalmente.
                ws2 = await session.ws_connect(f"http://127.0.0.1:{http_port}/ws")
                await ws2.send_json({"type": "hello", "mode": "web"})
                slot_msg2 = await resposta_util(ws2)
                assert slot_msg2 == {"type": "slot", "player": 0, "color": "blue"}, slot_msg2
                print("OK 5b: uma sessão nova entra no lugar libertado, normalmente")

                await ws.close()
                await ws2.close()
        finally:
            await runner.cleanup()
            listener.close()


async def main() -> None:
    await test_score_before_finished_reaches_top10()
    await test_score_after_finished_reaches_top10()
    await test_badword_name_becomes_placeholder()
    await test_valid_name_passes_unchanged()
    await test_missing_score_degrades_gracefully()
    await test_blocked_after_top10_new_session_plays_normally()
    print("OK 6 grupos de testes")


if __name__ == "__main__":
    asyncio.run(main())
