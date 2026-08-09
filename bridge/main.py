"""Arranque do bridge: SlotManager + servidor HTTP/WebSocket + QR do lobby.

    .venv/bin/python bridge/main.py [--config bridge/config.yaml]

Imprime o URL do lobby (com o IP real da máquina na LAN) para apontar o ecrã
lá, gera o QR uma vez, e corre o `tick()` do SlotManager a cada segundo até
receber SIGINT/SIGTERM.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import socket
from pathlib import Path

import yaml
from aiohttp import web

from adapters.web_adapter import create_app
from emitter import UdpEmitter
from qr import generate_qr
from slot_manager import SlotManager


LOGGER = logging.getLogger("bridge.main")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
QR_OUTPUT = REPO_ROOT / "game" / "resources" / "images" / "qr_lobby.png"

TICK_INTERVAL_SECONDS = 1.0


def lan_ip() -> str:
    """Descobre o IP da máquina na LAN sem enviar tráfego real (truque do socket UDP)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


async def periodic_tick(manager: SlotManager, route, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=TICK_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
        if stop_event.is_set():
            break
        await route(manager.tick())


async def run(config_path: Path) -> None:
    with config_path.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file) or {}
    web_config = config.get("web", {})
    host = web_config.get("host", "0.0.0.0")
    port = int(web_config.get("port", 8080))

    emitter = UdpEmitter.from_config(config_path)
    manager = SlotManager.from_config(config_path, emitter)

    ip = lan_ip()
    lobby_url = f"http://{ip}:{port}/"
    width, height = generate_qr(lobby_url, QR_OUTPUT)

    audio_config = config.get("audio")
    audio_mode = (audio_config or {}).get("mode", "desligado")

    banner = "=" * 64
    print(banner)
    print(f"  LOBBY:  {lobby_url}")
    print(f"  QR:     {QR_OUTPUT} ({width}x{height}px)")
    print(f"  JOGO:   UDP {emitter.host}:{emitter.port} (não muda, fica em loopback)")
    print(f"  AUDIO:  modo={audio_mode}")
    print(banner)

    app, route = create_app(manager, audio_config=audio_config)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    tick_task = asyncio.create_task(periodic_tick(manager, route, stop_event))

    await stop_event.wait()
    LOGGER.info("Sinal recebido — a desligar o bridge...")
    tick_task.cancel()
    await asyncio.gather(tick_task, return_exceptions=True)
    await route(manager.end_match())
    await runner.cleanup()
    LOGGER.info("Bridge desligado.")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(description="Bridge do jogo Hugo — HTTP/WS + SlotManager")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.config))


if __name__ == "__main__":
    main()
