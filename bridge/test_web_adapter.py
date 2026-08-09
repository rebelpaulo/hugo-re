"""Testes corríveis sem framework: .venv/bin/python bridge/test_web_adapter.py

Liga clientes WebSocket a sério a um servidor aiohttp a sério, em portas
efémeras de 127.0.0.1. O "jogo" é um socket UDP local a sério, escutado pelo
próprio teste. Nada de mocks de rede.
"""

from __future__ import annotations

import asyncio
import json
import socket

from aiohttp import ClientSession, WSMsgType, web

from adapters.web_adapter import create_app
from emitter import UdpEmitter
from slot_manager import SlotManager


def free_udp_listener() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(2.0)
    return sock


async def start_server(manager: SlotManager, **kwargs):
    app, route = create_app(manager, **kwargs)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, route, port


async def test_slots_and_queue_assignment() -> None:
    """6 clientes ligam-se: os 4 primeiros ficam com slots distintos, os
    outros dois ficam na fila nas posições 1 e 2."""
    listener = free_udp_listener()
    emitter = UdpEmitter(*listener.getsockname())
    manager = SlotManager(emitter)
    runner, _route, port = await start_server(manager)
    try:
        async with ClientSession() as session:
            clients = []
            for _ in range(6):
                ws = await session.ws_connect(f"http://127.0.0.1:{port}/ws")
                await ws.send_json({"type": "hello", "mode": "web"})
                message = json.loads((await ws.receive()).data)
                clients.append((ws, message))

            players = set()
            for index in range(4):
                message = clients[index][1]
                assert message["type"] == "slot", message
                players.add(message["player"])
            assert players == {0, 1, 2, 3}, players

            assert clients[4][1] == {"type": "queued", "position": 1, "ahead": 0}, clients[4][1]
            assert clients[5][1] == {"type": "queued", "position": 2, "ahead": 1}, clients[5][1]

            for ws, _ in clients:
                await ws.close()
    finally:
        await runner.cleanup()
        listener.close()


async def test_press_reaches_game() -> None:
    """Um `press` da webapp chega ao jogo por UDP como `press_<tecla>`."""
    listener = free_udp_listener()
    emitter = UdpEmitter(*listener.getsockname())
    manager = SlotManager(emitter)
    runner, _route, port = await start_server(manager)
    try:
        async with ClientSession() as session:
            ws = await session.ws_connect(f"http://127.0.0.1:{port}/ws")
            await ws.send_json({"type": "hello", "mode": "web"})
            slot_message = json.loads((await ws.receive()).data)
            assert slot_message["type"] == "slot", slot_message
            player = slot_message["player"]

            await ws.send_json({"type": "press", "key": "5"})
            loop = asyncio.get_event_loop()
            # O socket UDP também recebe os pacotes "slots" da atribuição do
            # slot (emitidos pelo próprio SlotManager); salta-os até chegar
            # ao evento do "press".
            event = None
            for _ in range(5):
                data, _addr = await loop.run_in_executor(None, listener.recvfrom, 4096)
                candidate = json.loads(data)
                if candidate.get("type") != "slots":
                    event = candidate
                    break
            assert event == {"player": player, "event": "press_5"}, event

            await ws.close()
    finally:
        await runner.cleanup()
        listener.close()


async def test_heartbeat_loss_releases_slot() -> None:
    """Sem `ping` dentro do prazo, o servidor larga o slot sozinho.

    Usa um `heartbeat_timeout` curto (injectável em `create_app`) para não
    obrigar o teste a esperar os 15s reais de produção."""
    listener = free_udp_listener()
    emitter = UdpEmitter(*listener.getsockname())
    manager = SlotManager(emitter)
    runner, _route, port = await start_server(manager, heartbeat_timeout=0.3)
    try:
        async with ClientSession() as session:
            ws = await session.ws_connect(f"http://127.0.0.1:{port}/ws")
            await ws.send_json({"type": "hello", "mode": "web"})
            slot_message = json.loads((await ws.receive()).data)
            player = slot_message["player"]
            assert manager.occupied == [player]

            # Não envia nenhum ping: o servidor tem de largar o slot sozinho.
            closed_msg = await ws.receive()
            assert closed_msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING)
            assert manager.occupied == [], manager.occupied
    finally:
        await runner.cleanup()
        listener.close()


TESTS = [
    test_slots_and_queue_assignment,
    test_press_reaches_game,
    test_heartbeat_loss_releases_slot,
]


def main() -> None:
    for test in TESTS:
        asyncio.run(test())
        print(f"OK {test.__name__}")
    print(f"OK {len(TESTS)} testes")


if __name__ == "__main__":
    main()
