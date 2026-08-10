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
import os
import signal
import subprocess
import logging
import re
import shutil
from pathlib import Path
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
        pid_path: "Path | None" = None,
    ) -> None:
        self.port = port
        self.host = host
        self.timeout = timeout
        self.dns_grace = dns_grace
        self.probe_interval = probe_interval
        # Onde fica escrito que o cloudflared em curso é nosso. Em
        # bridge/data/, que já está fora do versionamento.
        self.pid_path = pid_path or (Path(__file__).resolve().parent / "data" / "cloudflared.pid")
        self.url: Optional[str] = None
        self._proc: asyncio.subprocess.Process | None = None
        self._drain_task: asyncio.Task | None = None
        # Fica marcado quando o cloudflared termina por si. Serve para quem
        # nos usa poder reagir — um túnel morto a meio do evento é um QR no
        # ecrã que já não leva a lado nenhum, e nada nisto se nota sozinho.
        self._morreu = asyncio.Event()

    def _identidade_do_processo(self, pid: int) -> Optional[str]:
        """Hora de arranque + linha de comando de um PID, ou None se já não existir.

        O PID sozinho não identifica nada: o sistema reaproveita-o. A linha de
        comando também não chega — nada impede que o PID reaproveitado seja
        outro `cloudflared tunnel --url` para a mesma porta, aberto pelo
        operador. O que não se repete é o par (hora de arranque, comando):
        um processo com o mesmo PID nascido noutro instante é outro processo.
        Tudo numa só chamada ao `ps`, para os dois campos virem do mesmo
        processo e não de dois momentos diferentes.
        """
        try:
            saida = subprocess.run(
                ["ps", "-p", str(pid), "-o", "lstart=,command="],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        linha = " ".join(saida.stdout.split())
        return linha or None

    def _registar_dono(self, pid: int) -> None:
        """Deixa escrito que este cloudflared é nosso, e qual é."""
        identidade = self._identidade_do_processo(pid) or ""
        try:
            self.pid_path.parent.mkdir(parents=True, exist_ok=True)
            self.pid_path.write_text(
                f"{pid}\n{self._assinatura_comando()}\n{identidade}\n", encoding="utf-8"
            )
        except OSError as erro:
            LOGGER.debug("Não consegui registar o PID do cloudflared: %s", erro)

    def _esquecer_dono(self) -> None:
        try:
            self.pid_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _assinatura_comando(self) -> str:
        return f"cloudflared tunnel --url http://{self.host}:{self.port}"

    def _varrer_orfaos(self) -> int:
        """Mata um cloudflared NOSSO que tenha sobrado de um arranque anterior.

        Em macOS não há forma de pedir ao sistema que mate um filho quando o
        pai morre (o PR_SET_PDEATHSIG do Linux não existe cá). Se o bridge
        levar SIGKILL, ou rebentar, o cloudflared fica vivo — medido, não
        suposto. Ao longo de uma noite de reinícios isso acumula túneis a
        apontar para a mesma porta, todos menos um sem ninguém a saber deles.

        A propriedade vem de um ficheiro que escrevemos ao arrancar, não de
        adivinhar pela linha de comando: um `cloudflared tunnel --url` para a
        mesma porta pode ser de outra coisa que o operador tenha aberto, e
        matá-lo seria estragar-lhe o trabalho. Antes de mandar o sinal
        confirma-se que o PID ainda existe E que continua a ser o mesmo
        processo — mesma hora de arranque, mesmo comando. Só o comando não
        chegava: um PID reaproveitado por OUTRO cloudflared para a mesma porta
        passava o teste e levava com o sinal. Sem identidade guardada (o `ps`
        falhou ao arrancar) não se mata nada: deixar um túnel a mais é menos
        mau do que fechar o processo de outra pessoa.
        """
        try:
            registo = self.pid_path.read_text(encoding="utf-8").split("\n")
        except (OSError, ValueError):
            return 0
        self._esquecer_dono()
        try:
            pid = int(registo[0].strip())
        except (IndexError, ValueError):
            return 0
        assinatura = registo[1].strip() if len(registo) > 1 else ""
        if assinatura != self._assinatura_comando():
            return 0
        identidade = registo[2].strip() if len(registo) > 2 else ""
        if not identidade:
            return 0

        agora = self._identidade_do_processo(pid)
        if agora is None:
            return 0  # já morreu, nada a fazer
        if agora != identidade:
            LOGGER.debug(
                "PID %d já não é o nosso cloudflared (é %r) — deixado em paz", pid, agora[:60]
            )
            return 0
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return 0
        LOGGER.warning(
            "Ficou um cloudflared nosso (PID %d) de um arranque anterior — fechado.", pid
        )
        return 1

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

        self._varrer_orfaos()

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

        self._registar_dono(self._proc.pid)

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
                        # Um 5xx aqui é a Cloudflare a dizer que ela própria
                        # não chega à origem — 502 e 530 são o que ela devolve
                        # enquanto o túnel ainda não está montado de ponta a
                        # ponta. Dar isso por bom seria pôr no ecrã um QR que
                        # leva a uma página de erro, exactamente o que esta
                        # espera existe para evitar. Abaixo de 500 serve: quem
                        # responde é a nossa app, e o que se está a provar é
                        # que o caminho de fora até cá está aberto, não que a
                        # rota "/" devolve 200.
                        if resposta.status >= 500:
                            LOGGER.info(
                                "túnel devolveu %s à tentativa %d — ainda não está montado",
                                resposta.status,
                                tentativa,
                            )
                            await asyncio.sleep(self.probe_interval)
                            continue
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
        """Lê e deita fora o resto da saída, para o pipe nunca encher.

        O fim da saída é também como se sabe que o cloudflared morreu — daí
        marcar `_morreu` à saída, em qualquer dos caminhos."""
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
        finally:
            self._morreu.set()

    async def wait_until_dead(self) -> None:
        """Devolve-se quando o cloudflared terminar por si.

        Quem chama isto é o vigia em `main.py`: sem ele, um túnel que caia às
        23h deixa o QR do ecrã grande a apontar para o vazio e mais ninguém
        entra — e o supervisor não dá por nada, porque o bridge continua vivo.
        """
        await self._morreu.wait()

    async def restart(self) -> Optional[str]:
        """Fecha o que resta e levanta um túnel novo. Endereço novo, portanto
        quem chama tem de voltar a gerar o QR."""
        await self.stop()
        self._morreu = asyncio.Event()
        self.url = None
        return await self.start()

    async def stop(self) -> None:
        if self._drain_task is not None:
            self._drain_task.cancel()
            await asyncio.gather(self._drain_task, return_exceptions=True)
            self._drain_task = None
        proc = self._proc
        self._proc = None
        if proc is None or proc.returncode is not None:
            self._morreu.set()
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        self._esquecer_dono()
        self._morreu.set()


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
