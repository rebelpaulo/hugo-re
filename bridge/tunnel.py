"""Túnel Cloudflare: põe o lobby acessível de fora da rede local.

Porque isto existe: o QR no ecrã grande apontava para o IP do Mac na rede
local, o que obriga toda a gente que o lê a estar na mesma WiFi. Num evento
isso não acontece — as pessoas estão no 4G delas.

Usa-se um *quick tunnel* (`cloudflared tunnel --url ...`): não pede conta, não
pede domínio, não custa nada, e — ao contrário do plano grátis do ngrok — não
mete página de aviso entre o QR e o jogo. Medido contra este bridge: a app
chega em 0,35s e a ida-e-volta do WebSocket fica em ~102ms, metade disso por
sentido.

O preço é o endereço mudar a cada arranque. Aqui isso não custa nada, porque o
QR é gerado a cada arranque também (ver `bridge/qr.py` e `main.py`) e vive no
ecrã, não em papel. O que custa mesmo é um reinício a meio do evento: quem já
estava ligado fica com um endereço morto e tem de voltar a ler o QR. Para o
evitar é preciso um túnel nomeado, que precisa de um domínio na conta
Cloudflare — o desenho aqui não fecha essa porta.

REGRA que manda em tudo isto: o túnel nunca pode impedir o jogo de arrancar.
Sem `cloudflared` instalado, com a rede em baixo, ou se a Cloudflare demorar
demasiado, desiste-se e usa-se o endereço da rede local — que é exactamente o
que havia antes. O servidor continua a escutar em 0.0.0.0, portanto o caminho
local funciona sempre, com ou sem túnel.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from typing import Optional

LOGGER = logging.getLogger("bridge.tunnel")

# cloudflared anuncia o endereço numa linha do stderr, dentro de uma moldura
# ASCII. Chega procurar o próprio endereço.
_URL_PATTERN = re.compile(rb"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")

DEFAULT_TIMEOUT_SECONDS = 60.0
# Silêncio antes da primeira pergunta pelo endereço novo — ver
# `_wait_until_reachable`, onde está a medição que justifica isto.
DEFAULT_DNS_GRACE_SECONDS = 20.0
DEFAULT_PROBE_INTERVAL_SECONDS = 5.0


class QuickTunnel:
    """Um `cloudflared tunnel --url` a apontar para o porto local do lobby."""

    def __init__(
        self,
        port: int,
        *,
        host: str = "127.0.0.1",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        dns_grace: float = DEFAULT_DNS_GRACE_SECONDS,
        probe_interval: float = DEFAULT_PROBE_INTERVAL_SECONDS,
    ) -> None:
        self.port = port
        self.host = host
        self.timeout = timeout
        self.dns_grace = dns_grace
        self.probe_interval = probe_interval
        self.url: Optional[str] = None
        self._proc: asyncio.subprocess.Process | None = None
        self._drain_task: asyncio.Task | None = None

    async def start(self) -> Optional[str]:
        """Arranca o túnel e devolve o endereço público, ou None se não deu.

        Nunca levanta excepção: qualquer falha aqui é degradação para o
        endereço da rede local, não um arranque falhado.
        """
        if shutil.which("cloudflared") is None:
            LOGGER.warning(
                "cloudflared não está instalado — o QR vai apontar para a rede local. "
                "Instala com: brew install cloudflared"
            )
            return None

        try:
            self._proc = await asyncio.create_subprocess_exec(
                "cloudflared",
                "tunnel",
                "--url",
                f"http://{self.host}:{self.port}",
                "--no-autoupdate",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as erro:
            LOGGER.warning("Não consegui arrancar o cloudflared (%s) — fica o endereço local", erro)
            return None

        try:
            self.url = await asyncio.wait_for(self._read_url(), timeout=self.timeout)
        except asyncio.TimeoutError:
            LOGGER.warning(
                "O cloudflared não anunciou endereço em %.0fs — fica o endereço local", self.timeout
            )
            await self.stop()
            return None

        if self.url is None:
            # O processo morreu antes de anunciar seja o que for.
            LOGGER.warning("O cloudflared terminou sem dar endereço — fica o endereço local")
            await self.stop()
            return None

        # A partir daqui é preciso continuar a consumir a saída do processo:
        # um pipe cheio bloqueia o cloudflared, e com ele o túnel todo.
        self._drain_task = asyncio.create_task(self._drain())

        # O cloudflared anuncia o endereço antes de ele resolver no DNS —
        # apanhado no auto-teste, que falhou com "nodename nor servname
        # provided" contra um túnel acabado de abrir. Se púséssemos o QR no
        # ecrã já, quem o lesse nos primeiros segundos apanhava um erro de
        # DNS. Espera-se que o endereço responda mesmo antes de o dar por bom.
        if not await self._wait_until_reachable():
            LOGGER.warning(
                "O túnel %s nunca respondeu — fica o endereço local", self.url
            )
            self.url = None
            await self.stop()
            return None

        LOGGER.info("Túnel Cloudflare de pé: %s", self.url)
        return self.url

    async def _wait_until_reachable(self) -> bool:
        """Bate à porta do endereço público até ele responder, ou desiste.

        A espera antes da primeira tentativa não é folga: é o que faz isto
        funcionar. Medido nesta máquina, com dois túneis acabados de abrir —
        a insistir de segundo a segundo desde o início, o nome não resolveu em
        20s; a esperar 20s calado, resolveu à primeira pergunta. Perguntar por
        um nome que ainda não existe faz o resolvedor fixar o "não existe", e
        ficamos presos a essa resposta mesmo depois de o registo aparecer.
        Daí: calar-se primeiro, e depois perguntar devagar.
        """
        from aiohttp import ClientError, ClientSession, ClientTimeout

        LOGGER.info(
            "Túnel anunciado em %s — a aguardar %.0fs pela propagação do DNS "
            "(perguntar cedo de mais só atrasa, ver comentário no código)",
            self.url,
            self.dns_grace,
        )
        await asyncio.sleep(self.dns_grace)

        loop = asyncio.get_running_loop()
        limite = loop.time() + self.timeout
        tentativa = 0
        async with ClientSession(timeout=ClientTimeout(total=8)) as session:
            while loop.time() < limite:
                tentativa += 1
                try:
                    async with session.get(f"{self.url}/") as resposta:
                        # Qualquer resposta HTTP serve: o que se está a provar
                        # é que o caminho de fora até aqui está aberto, não
                        # que a rota "/" devolve 200.
                        LOGGER.debug(
                            "túnel respondeu %s à tentativa %d", resposta.status, tentativa
                        )
                        return True
                except (ClientError, asyncio.TimeoutError, OSError) as erro:
                    LOGGER.info(
                        "túnel ainda não responde (tentativa %d): %s", tentativa, erro
                    )
                    await asyncio.sleep(self.probe_interval)
        return False

    async def _read_url(self) -> Optional[str]:
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                return None  # processo terminou
            found = _URL_PATTERN.search(line)
            if found:
                return found.group(0).decode()

    async def _drain(self) -> None:
        """Lê e deita fora o resto da saída, para o pipe nunca encher."""
        assert self._proc is not None and self._proc.stdout is not None
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    return
                LOGGER.debug("cloudflared: %s", line.decode(errors="replace").rstrip())
        except asyncio.CancelledError:
            raise
        except Exception:  # nunca derrubar o bridge por causa do log do túnel
            LOGGER.exception("Falha a ler a saída do cloudflared")

    async def stop(self) -> None:
        if self._drain_task is not None:
            self._drain_task.cancel()
            await asyncio.gather(self._drain_task, return_exceptions=True)
            self._drain_task = None
        proc = self._proc
        self._proc = None
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()


async def _demo() -> int:
    """Auto-teste: levanta um servidor mínimo, abre o túnel, e confirma que o
    que chega de fora é mesmo o que o servidor serve.

    Correr:  .venv/bin/python bridge/tunnel.py
    """
    from aiohttp import ClientSession, web

    marca = "hugo-tunnel-demo-ok"

    async def raiz(_request: web.Request) -> web.Response:
        return web.Response(text=marca)

    app = web.Application()
    app.router.add_get("/", raiz)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 18799)
    await site.start()

    tunnel = QuickTunnel(18799)
    url = await tunnel.start()
    try:
        if url is None:
            print("IGNORADO: sem túnel (cloudflared em falta ou sem rede)")
            return 0
        assert url.startswith("https://"), url
        async with ClientSession() as session:
            async with session.get(url + "/", timeout=30) as resposta:
                corpo = await resposta.text()
        assert resposta.status == 200, resposta.status
        assert marca in corpo, f"veio outra coisa: {corpo[:120]!r}"
        print(f"OK demo: {url} devolveu o conteúdo do servidor local")
        return 0
    finally:
        await tunnel.stop()
        await runner.cleanup()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_demo()))
