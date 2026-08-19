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
from adapters.web_adapter import VALID_INPUT_MODES, create_app, load_input_mode
from control import DEFAULT_HOST as CONTROL_HOST
from control import DEFAULT_PORT as CONTROL_PORT
from control import start_control_listener
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

    def set_mode(self, mode: str) -> None:
        """Muda o modo carimbado a partir da próxima mensagem.

        Existe porque o modo deixou de ser decidido só no arranque: o
        operador troca-o no ecrã grande com o evento a decorrer (ver
        `bridge/control.py`).
        """
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
    web_bridge = app["web_bridge"]
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
    # Apaga o QR da sessão anterior ANTES de levantar o túnel. Enquanto o
    # endereço novo não existe, o ficheiro em disco aponta para o túnel da
    # última vez, que já morreu — e o jogo, que arranca antes do bridge
    # (`scripts/macos/supervisor.sh`), mostrava-o no ecrã grande durante esses
    # ~30 segundos. Sem ficheiro, o convite aparece sem QR (o overlay aguenta
    # isso) e apanha o novo assim que ele for escrito, porque relê o ficheiro
    # quando muda (ver `game/invite_overlay.py`). Melhor um convite sem código
    # do que um código que não leva a lado nenhum.
    QR_OUTPUT.unlink(missing_ok=True)

    ip = lan_ip()
    local_url = f"http://{ip}:{port}/"

    # Os handlers de sinal vão ANTES de arrancar o túnel, não depois. O
    # `tunnel.start()` pode demorar mais de um minuto entre a espera do DNS e
    # as sondagens; com os handlers instalados só a seguir, um Ctrl-C nesse
    # intervalo matava o bridge pela acção por omissão do sinal e deixava o
    # cloudflared vivo, órfão. Repetir arranques ia acumulando túneis.
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    tunnel: QuickTunnel | None = None
    public_url: str | None = None
    if tunnel_config.get("enabled", False):
        tunnel = QuickTunnel(
            port,
            timeout=float(tunnel_config.get("timeout_seconds", 60)),
            dns_grace=float(tunnel_config.get("dns_grace_seconds", 20)),
        )
        # O arranque do túnel pode levar mais de um minuto (espera de DNS mais
        # sondagens). Se chegar um sinal a meio, não basta o handler marcar o
        # `stop_event` — é preciso interromper esta espera, senão o bridge fica
        # cá dentro até ela acabar e o cloudflared pode sobreviver-lhe.
        tarefa_tunel = asyncio.create_task(tunnel.start())
        tarefa_parar = asyncio.create_task(stop_event.wait())
        feitas, _ = await asyncio.wait(
            {tarefa_tunel, tarefa_parar}, return_when=asyncio.FIRST_COMPLETED
        )
        if tarefa_parar in feitas:
            LOGGER.info("Sinal recebido durante o arranque do túnel — a desistir dele.")
            tarefa_tunel.cancel()
            await asyncio.gather(tarefa_tunel, return_exceptions=True)
            await tunnel.stop()
            await runner.cleanup()
            LOGGER.info("Bridge desligado.")
            return
        tarefa_parar.cancel()
        public_url = tarefa_tunel.result()
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
    print(f"  MODO:   {input_mode}  (troca-se no botão do ecrã grande, sem reiniciar)")
    print(
        f"  SIP:    ESL {sip_config.get('esl_host', '127.0.0.1')}:"
        f"{sip_config.get('esl_port', 8021)} (contexto {sip_config.get('context', 'hugo-lan')})"
    )
    print(banner)

    # Em input_mode=sip liga-se também o adaptador SIP — o servidor
    # HTTP/WebSocket acima continua a correr sempre (é o que a webapp
    # legada, se lá alguém cair, precisa para mostrar o aviso), mas quem
    # traz os telefones para o SlotManager é este.
    # O adaptador SIP passa a poder ligar-se e desligar-se com o bridge a
    # andar. Antes o modo era decidido uma vez, no arranque, e trocá-lo
    # obrigava a editar o config.yaml e reiniciar tudo — com o jogo e o túnel
    # atrás, quase um minuto de ecrã parado. Agora é um botão no ecrã grande
    # (ver game/mode_button.py e bridge/control.py).
    modo_actual = input_mode
    sip_adapter: SipAdapter | None = None
    sip_task: asyncio.Task | None = None

    async def sip_route(decisions: list[Decision]) -> None:
        # Ainda sem áudio para o auscultador (ver bridge/README.md) — por
        # agora só regista; o desenho não fecha a porta a encaminhar isto
        # para lá quando o áudio SIP existir.
        for decision in decisions:
            LOGGER.debug("SIP decision: %s", decision)

    async def ligar_sip() -> None:
        nonlocal sip_adapter, sip_task
        if sip_adapter is not None:
            return
        sip_adapter = SipAdapter(
            manager,
            sip_route,
            host=sip_config.get("esl_host", "127.0.0.1"),
            port=int(sip_config.get("esl_port", 8021)),
            password=sip_config.get("esl_password", "ClueCon"),
            context=sip_config.get("context", "hugo-lan"),
        )
        sip_task = asyncio.create_task(sip_adapter.run())

    async def desligar_sip() -> None:
        nonlocal sip_adapter, sip_task
        if sip_adapter is None:
            return
        adaptador, tarefa = sip_adapter, sip_task
        sip_adapter = None
        sip_task = None
        await adaptador.stop()
        if tarefa is not None:
            # `stop()` fecha o writer, mas se o `run()` estiver preso a abrir a
            # ligação ao ESL ainda não há writer nenhum para fechar — e o
            # esperar por ele ficava à mercê do TCP desistir sozinho. Com o
            # FreeSWITCH em loopback isso é imediato; com o ESL a meio do
            # handshake, não é, e ficava presa a troca de modo E o
            # encerramento do bridge.
            try:
                await asyncio.wait_for(tarefa, timeout=5)
            except asyncio.TimeoutError:
                LOGGER.warning("O adaptador SIP não parou em 5s — cancelado.")
                tarefa.cancel()
                await asyncio.gather(tarefa, return_exceptions=True)
            except Exception:
                LOGGER.debug("O adaptador SIP terminou com erro", exc_info=True)

    # Serializa as trocas de modo. Sem isto, dois pedidos ao mesmo tempo
    # entrelaçavam-se e deixavam o sistema partido de duas maneiras medidas:
    # em modo web com o adaptador SIP a correr (telefones e telemóveis ao
    # mesmo tempo), ou em modo sip sem adaptador nenhum (o botão a dizer
    # TELEFONES com o ESL morto).
    troca_de_modo = asyncio.Lock()

    async def mudar_modo(novo: str) -> None:
        nonlocal modo_actual
        if novo not in VALID_INPUT_MODES:
            LOGGER.warning("Pedido de modo inválido (%r) — ignorado", novo)
            return
        async with troca_de_modo:
            # A comparação vive DENTRO do cadeado de propósito: cá fora, dois
            # pedidos seguidos comparavam-se ambos contra o valor antigo, e o
            # segundo saía sem fazer nada — o operador pedia web e ficava sip.
            if novo == modo_actual:
                return
            # Quem está a jogar sai. O input com que entrou deixou de contar, e
            # deixá-lo com um teclado que já não faz nada é pior do que tirá-lo:
            # pelo menos assim o telemóvel diz-lhe o que se passa.
            await route(manager.end_match())
            if novo == "sip":
                await ligar_sip()
            else:
                await desligar_sip()
            # `modo_actual` só muda depois de os efeitos estarem feitos. Com
            # ele actualizado no início, uma excepção a meio deixava o bridge a
            # afirmar o modo novo sem nada disto feito — e o clique seguinte,
            # a pedir o mesmo alvo, era ignorado pela comparação acima. O botão
            # ficava morto até alguém reiniciar o bridge.
            emitter.set_mode(novo)
            modo_actual = novo
            await web_bridge.set_input_mode(novo)
            # O jogo aprende o modo pela mensagem `slots`. Forçar uma agora
            # evita que o ecrã grande fique até um tick inteiro a anunciar o
            # modo antigo — e é justamente nesse segundo que alguém está a
            # olhar para ele à espera de ver se o botão funcionou.
            emitter.send_slots(manager.occupied, manager.queue_len)
            print(f"  MODO:   {novo}", flush=True)

    if modo_actual == "sip":
        await ligar_sip()

    control_config = config.get("control") or {}
    control_transport = await start_control_listener(
        mudar_modo,
        host=control_config.get("host", CONTROL_HOST),
        port=int(control_config.get("port", CONTROL_PORT)),
    )

    # Uma mensagem `slots` logo no arranque, antes de haver jogadores. O
    # SlotManager só emite quando algo muda, portanto num evento que comece em
    # `sip` e onde ninguém tenha ainda ligado, o jogo nunca ouvia falar do modo
    # e ficava no que assume por omissão — a mostrar o QR num evento de
    # telefones (`game/udp_input.py`: sem campo, "web"). Custa um datagrama.
    emitter.send_slots(manager.occupied, manager.queue_len)

    tick_task = asyncio.create_task(periodic_tick(manager, route, stop_event))
    tunnel_task: asyncio.Task | None = None
    if tunnel is not None:
        tunnel_task = asyncio.create_task(
            vigiar_tunel(tunnel, local_url, stop_event)
        )

    try:
        await stop_event.wait()
        LOGGER.info("Sinal recebido — a desligar o bridge...")
    finally:
        # `finally` e não a seguir ao `await`: se algo aqui rebentar, ou se
        # a tarefa for cancelada, o cloudflared tem de morrer na mesma. Já
        # deixámos túneis órfãos por não haver isto.
        tick_task.cancel()
        await asyncio.gather(tick_task, return_exceptions=True)
        if tunnel_task is not None:
            tunnel_task.cancel()
            await asyncio.gather(tunnel_task, return_exceptions=True)
        control_transport.close()
        await desligar_sip()
        await route(manager.end_match())
        if tunnel is not None:
            await tunnel.stop()
        await runner.cleanup()
        LOGGER.info("Bridge desligado.")


async def vigiar_tunel(tunnel: QuickTunnel, local_url: str, stop_event: asyncio.Event) -> None:
    """Levanta outro túnel se o cloudflared cair, e refaz o QR.

    Sem isto, um túnel que morra às 23h deixa o ecrã grande com um QR que já
    não leva a lado nenhum e mais ninguém entra — e nada o denuncia, porque o
    bridge continua vivo e o supervisor só vigia processos.

    O endereço novo é outro, e é por isso que o jogo relê o ficheiro do QR
    quando ele muda (ver `game/invite_overlay.py`): o ecrã grande passa a
    mostrar o código certo sozinho, sem reiniciar nada. Quem já estava a jogar
    perde a ligação — o endereço antigo morreu com o túnel — mas quem chegar a
    seguir entra.
    """
    while not stop_event.is_set():
        await tunnel.wait_until_dead()
        if stop_event.is_set():
            return
        LOGGER.error("O cloudflared caiu — o QR no ecrã já não serve. A levantar outro túnel.")
        # Fora o QR morto primeiro: durante a recuperação é melhor o ecrã não
        # ter código nenhum do que ter um que dá erro.
        QR_OUTPUT.unlink(missing_ok=True)
        novo = await tunnel.restart()
        if novo is None:
            LOGGER.error(
                "Não consegui levantar outro túnel. Fica o endereço local (%s) — "
                "só entra quem estiver na mesma Wi-Fi.",
                local_url,
            )
            generate_qr(local_url, QR_OUTPUT)
            return
        novo = novo.rstrip("/") + "/"
        generate_qr(novo, QR_OUTPUT)
        LOGGER.info("Túnel de pé outra vez: %s (QR do ecrã já actualizado)", novo)


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
