"""Canal de controlo local: mudar o modo de entrada com o bridge a andar.

Porque é UDP preso ao loopback e não uma rota HTTP: o servidor web escuta em
`0.0.0.0` e, com o túnel levantado, qualquer pessoa que leia o QR lhe chega.
Uma rota que mudasse o modo de entrada seria um botão de "desligar o evento"
ao alcance do público. E filtrar por `request.remote` não resolvia nada — o
cloudflared entrega tudo como 127.0.0.1, portanto o tráfego do túnel é
indistinguível do local. Um socket preso a 127.0.0.1 não é alcançável pelo
túnel de todo, que é a única garantia que não depende de eu me lembrar de a
manter.

Protocolo, uma linha de JSON por datagrama:

    {"cmd": "input_mode", "mode": "sip"}    # ou "web"

Sem resposta: quem manda fica a saber que resultou porque o modo novo aparece
na mensagem `slots` que o bridge já emite para o jogo.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

LOGGER = logging.getLogger("bridge.control")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9111


class _ControlProtocol(asyncio.DatagramProtocol):
    def __init__(self, aplicar: Callable[[str], Awaitable[None]]) -> None:
        self._aplicar = aplicar
        self._tarefas: set[asyncio.Task] = set()

    def datagram_received(self, data: bytes, addr) -> None:
        try:
            mensagem = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            LOGGER.debug("Datagrama de controlo ilegível de %s", addr)
            return
        if not isinstance(mensagem, dict) or mensagem.get("cmd") != "input_mode":
            return
        modo = mensagem.get("mode")
        if not isinstance(modo, str):
            return
        # Guardar a referência: sem isto o garbage collector pode levar a
        # tarefa a meio e a mudança de modo perde-se sem deixar rasto.
        tarefa = asyncio.get_running_loop().create_task(self._aplicar(modo))
        self._tarefas.add(tarefa)
        tarefa.add_done_callback(self._terminou)

    def _terminou(self, tarefa: asyncio.Task) -> None:
        self._tarefas.discard(tarefa)
        if tarefa.cancelled():
            return
        erro = tarefa.exception()
        if erro is not None:
            # Sem isto o asyncio limitava-se a escrever "Task exception was
            # never retrieved" quando lhe apetecesse, e quem está a montar o
            # evento não via nada — o botão simplesmente não fazia efeito.
            LOGGER.error("A troca de modo falhou: %s", erro, exc_info=erro)


async def start_control_listener(
    aplicar: Callable[[str], Awaitable[None]],
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> asyncio.DatagramTransport:
    """Põe o canal de controlo à escuta. `aplicar` recebe o modo pedido."""
    if host not in ("127.0.0.1", "::1", "localhost"):
        # Não é uma preferência de estilo: fora do loopback isto fica exposto
        # à rede do evento, e a rede do evento tem convidados.
        raise ValueError(
            f"canal de controlo só pode escutar em loopback, não em {host!r}"
        )
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: _ControlProtocol(aplicar), local_addr=(host, port)
    )
    LOGGER.info("Canal de controlo à escuta em %s:%d", host, port)
    return transport
