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
import sys
from pathlib import Path

import yaml
from aiohttp import web

from adapters.sip_adapter import SipAdapter
from adapters.web_adapter import create_app, load_input_mode
from emitter import UdpEmitter
from qr import generate_qr
from tunnel import QuickTunnel
from slot_manager import Decision, SlotManager


LOGGER = logging.getLogger("bridge.main")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
QR_OUTPUT = REPO_ROOT / "game" / "resources" / "images" / "qr_lobby.png"

TICK_INTERVAL_SECONDS = 1.0


class _ModeStampedEmitter(UdpEmitter):
    """`UdpEmitter` que acrescenta `"mode"` às mensagens `slots` que o
    `SlotManager` já envia (ver `slot_manager.py:555`), para o jogo saber se
    está em `input_mode=web` ou `sip` sem precisar de ler `config.yaml` ele
    próprio (`game/udp_input.py` — sem o campo, assume "web").

    Só a serialização final ganha o campo novo — não mexe em
    `emitter.py` nem em `slot_manager.py`."""

    def __init__(self, *args, mode: str, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._mode = mode

    def _send(self, payload):
        if payload.get("type") == "slots":
            payload = {**payload, "mode": self._mode}
        return super()._send(payload)


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

    # Uma só leitura de input_mode, a partir do --config efectivamente usado
    # (não do bridge/config.yaml por omissão) — emissor e webapp têm de
    # concordar sempre no mesmo modo.
    input_mode = load_input_mode(config_path)
    game_config = config.get("game") or {}
    emitter = _ModeStampedEmitter(
        host=game_config.get("host", "127.0.0.1"),
        port=int(game_config.get("port", 9100)),
        mode=input_mode,
    )
    manager = SlotManager.from_config(config_path, emitter)

    audio_config = config.get("audio")
    audio_mode = (audio_config or {}).get("mode", "desligado")
    score_config = config.get("score")
    sip_config = config.get("sip") or {}
    tunnel_config = config.get("tunnel") or {}

    app, route = create_app(
        manager, audio_config=audio_config, input_mode=input_mode, score_config=score_config
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    # O túnel só arranca depois de o servidor estar a escutar, e o QR só se
    # gera depois de sabermos o endereço — senão punha-se no ecrã um QR para
    # um sítio que ainda não responde. Sem túnel (desligado, cloudflared em
    # falta, rede em baixo) cai-se no endereço da rede local, que é o que
    # havia antes; o servidor escuta em 0.0.0.0, portanto esse caminho
    # funciona sempre, com ou sem túnel.
    ip = lan_ip()
    local_url = f"http://{ip}:{port}/"
    tunnel: QuickTunnel | None = None
    public_url: str | None = None
    if tunnel_config.get("enabled", False):
        tunnel = QuickTunnel(
            port,
            timeout=float(tunnel_config.get("timeout_seconds", 60)),
            dns_grace=float(tunnel_config.get("dns_grace_seconds", 20)),
        )
        public_url = await tunnel.start()
        if public_url is None:
            tunnel = None
        else:
            # O cloudflared anuncia sem barra final; o endereço local tem-na.
            # Uniformiza-se para os dois lados do banner (e o QR) dizerem a
            # mesma coisa.
            public_url = public_url.rstrip("/") + "/"

    lobby_url = public_url or local_url
    width, height = generate_qr(lobby_url, QR_OUTPUT)

    banner = "=" * 64
    print(banner)
    print(f"  LOBBY:  {lobby_url}")
    if public_url:
        print(f"  LOCAL:  {local_url}  (continua a servir quem estiver na mesma WiFi)")
    elif tunnel_config.get("enabled", False):
        print("  TÚNEL:  não subiu — só funciona para quem estiver na mesma WiFi")
    print(f"  QR:     {QR_OUTPUT} ({width}x{height}px)")
    print(f"  JOGO:   UDP {emitter.host}:{emitter.port} (não muda, fica em loopback)")
    print(f"  AUDIO:  modo={audio_mode}")
    if score_config:
        print(f"  SCORE:  UDP {score_config.get('host', '127.0.0.1')}:{score_config.get('port', 9110)} · top10 em /top10")
    if input_mode == "sip":
        print(
            f"  SIP:    ESL {sip_config.get('esl_host', '127.0.0.1')}:"
            f"{sip_config.get('esl_port', 8021)} (contexto {sip_config.get('context', 'hugo-lan')})"
        )
        print("          ver scripts/macos/run-sip.sh para arrancar o FreeSWITCH")
    print(banner)

    # Em input_mode=sip liga-se também o adaptador SIP — o servidor
    # HTTP/WebSocket acima continua a correr sempre (é o que a webapp
    # legada, se lá alguém cair, precisa para mostrar o aviso), mas quem
    # traz os telefones para o SlotManager é este.
    sip_adapter: SipAdapter | None = None
    sip_task: asyncio.Task | None = None
    if input_mode == "sip":

        async def sip_route(decisions: list[Decision]) -> None:
            # Ainda sem áudio para o auscultador (ver bridge/README.md) —
            # por agora só regista; o desenho não fecha a porta a
            # encaminhar isto para lá quando o áudio SIP existir.
            for decision in decisions:
                LOGGER.debug("SIP decision: %s", decision)

        sip_adapter = SipAdapter(
            manager,
            sip_route,
            host=sip_config.get("esl_host", "127.0.0.1"),
            port=int(sip_config.get("esl_port", 8021)),
            password=sip_config.get("esl_password", "ClueCon"),
            context=sip_config.get("context", "hugo-lan"),
        )
        sip_task = asyncio.create_task(sip_adapter.run())

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    tick_task = asyncio.create_task(periodic_tick(manager, route, stop_event))

    await stop_event.wait()
    LOGGER.info("Sinal recebido — a desligar o bridge...")
    tick_task.cancel()
    await asyncio.gather(tick_task, return_exceptions=True)
    if sip_adapter is not None and sip_task is not None:
        await sip_adapter.stop()
        await asyncio.gather(sip_task, return_exceptions=True)
    await route(manager.end_match())
    if tunnel is not None:
        await tunnel.stop()
    await runner.cleanup()
    LOGGER.info("Bridge desligado.")


def main() -> None:
    # O supervisor manda a saída para um ficheiro de log, e aí o `print` fica
    # em buffer de bloco: o banner com o endereço do lobby só aparecia quando
    # o processo terminasse. Quem está a montar o evento precisa de o ver
    # agora, não no fim.
    sys.stdout.reconfigure(line_buffering=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(description="Bridge do jogo Hugo — HTTP/WS + SlotManager")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.config))


if __name__ == "__main__":
    main()
