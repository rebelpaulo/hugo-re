"""Som do jogo dentro da chamada do telefone.

O que faltava: em modo telemóveis o áudio vai por WebSocket até ao browser
de cada pessoa; um telefone SIP não tem WebSocket nenhuma, portanto a
entrega falhava em silêncio e quem estava ao telefone jogava sem ouvir
nada. Ver `web_adapter.dispatch_audio` — procura uma sessão WebSocket pelo
lugar do jogador e desiste se não houver.

Como se resolve: `uuid_displace ... mux` mete um ficheiro por cima do áudio
da chamada, misturado com o que já lá estiver. É isso que permite ter a
música e uma voz ao mesmo tempo, que é o que o jogo faz — e foi o primeiro
a ser confirmado numa chamada a sério antes de se escrever isto.

Os ficheiros vão como estão, sem conversão: os `.wav` da BigFile são PCM
16 bits mono a 22050 Hz e o mod_sndfile do FreeSWITCH lê-os directamente,
com o núcleo a reamostrar para o codec da chamada (G722, 16 kHz). Não há
cache nem pipeline de conversão para manter — ao contrário do caminho web,
que precisa de AAC para o browser.

LIGAÇÃO SEPARADA, e é de propósito: os comandos vão numa segunda ligação ao
ESL, não na que o `SipAdapter` usa para receber eventos. Na mesma ligação, a
resposta a um `api` entrava no meio do fluxo de eventos e o leitor do
adaptador tomava-a por um evento — a corrida é silenciosa e só se manifesta
com carga, que é como dizer "no dia do evento".
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

LOGGER = logging.getLogger("bridge.sip_audio")

_TIMEOUT = 5.0


class EslCommands:
    """Ligação ao ESL só para mandar comandos (`api ...`)."""

    def __init__(self, host: str, port: int, password: str) -> None:
        self.host = host
        self.port = port
        self.password = password
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        # Uma ordem de cada vez: o protocolo é pedido-resposta na mesma
        # ligação, e dois comandos ao mesmo tempo trocavam as respostas.
        self._lock = asyncio.Lock()

    async def _ligar(self) -> None:
        from adapters.sip_adapter import _read_frame, _send  # evita import circular

        reader, writer = await asyncio.open_connection(self.host, self.port)
        headers, _ = await _read_frame(reader)
        if headers.get("Content-Type") != "auth/request":
            writer.close()
            raise ConnectionError(f"ESL não pediu autenticação: {headers!r}")
        await _send(writer, f"auth {self.password}")
        headers, _ = await _read_frame(reader)
        if not headers.get("Reply-Text", "").startswith("+OK"):
            writer.close()
            raise ConnectionError(f"ESL recusou a palavra-passe: {headers.get('Reply-Text')!r}")
        self._reader, self._writer = reader, writer
        LOGGER.info("Ligação de comandos ao ESL aberta em %s:%d", self.host, self.port)

    async def api(self, comando: str) -> Optional[str]:
        """Corre `api <comando>`. Devolve a resposta, ou None se falhar.

        Nunca levanta: um som que não toca não pode derrubar uma partida.
        """
        from adapters.sip_adapter import _read_frame, _send

        async with self._lock:
            for tentativa in (1, 2):
                try:
                    if self._writer is None or self._writer.is_closing():
                        await self._ligar()
                    assert self._reader is not None and self._writer is not None
                    await _send(self._writer, f"api {comando}")
                    _, corpo = await asyncio.wait_for(
                        _read_frame(self._reader), timeout=_TIMEOUT
                    )
                    return corpo.decode("utf-8", "replace").strip()
                except Exception as erro:
                    # Primeira falha: quase sempre a ligação que caiu entre
                    # comandos. Fecha-se e tenta-se outra vez, uma só.
                    LOGGER.debug("Comando ESL %r falhou (%s)", comando, erro)
                    await self.close()
                    if tentativa == 2:
                        LOGGER.warning("Comando ESL %r falhou duas vezes — desisto", comando)
                        return None
            return None

    async def close(self) -> None:
        writer, self._writer, self._reader = self._writer, None, None
        if writer is None:
            return
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


def resolve_resource(resource: str, source_paths: tuple[Path, ...]) -> Optional[Path]:
    """Traduz o nome do recurso num ficheiro real, ou None.

    Mesma disciplina do `audio_handler` do caminho web: a verificação de
    travessia é feita por cada raiz, ANTES de se olhar se o ficheiro existe.
    Aqui o caminho vai parar a uma linha de comando do FreeSWITCH, portanto
    um `..` que escapasse dava-lhe a ler ficheiros fora dos assets.
    """
    for root in source_paths:
        candidato = (root / resource).resolve()
        try:
            candidato.relative_to(root)
        except ValueError:
            continue
        if candidato.is_file():
            return candidato
    return None


class SipAudio:
    """Encaminha o áudio de um jogador para a chamada dele."""

    def __init__(self, comandos: EslCommands, source_paths: tuple[Path, ...]) -> None:
        self.comandos = comandos
        self.source_paths = source_paths
        # instância do jogo -> (uuid da chamada, ficheiro). O jogo manda parar
        # por número de instância; o FreeSWITCH pára por caminho de ficheiro.
        self._instancias: dict[int, tuple[str, Path]] = {}

    async def play(self, uuid: str, resource: str, instance_id: int) -> bool:
        caminho = resolve_resource(resource, self.source_paths)
        if caminho is None:
            LOGGER.warning("Recurso de áudio não encontrado: %r", resource)
            return False
        resposta = await self.comandos.api(f"uuid_displace {uuid} start {caminho} 0 mux")
        if resposta is None or not resposta.startswith("+OK"):
            LOGGER.warning("uuid_displace start falhou para %s: %r", resource, resposta)
            return False
        self._instancias[instance_id] = (uuid, caminho)
        return True

    async def stop(self, instance_id: int) -> bool:
        registo = self._instancias.pop(instance_id, None)
        if registo is None:
            return False
        uuid, caminho = registo
        # ponytail: pára-se por caminho, que é o que o FreeSWITCH aceita. Se o
        # MESMO ficheiro estiver a tocar duas vezes na mesma chamada, isto
        # cala as duas. Acontece com efeitos repetidos, não com a música; se
        # um dia importar, o caminho é copiar o ficheiro para um nome por
        # instância, não emendar isto.
        resposta = await self.comandos.api(f"uuid_displace {uuid} stop {caminho}")
        return resposta is not None and resposta.startswith("+OK")

    async def stop_all_for(self, uuid: str) -> None:
        """Cala tudo o que estiver a tocar numa chamada (fim de partida, desligar)."""
        for instance_id, (call_uuid, _) in list(self._instancias.items()):
            if call_uuid == uuid:
                self._instancias.pop(instance_id, None)
        await self.comandos.api(f"uuid_break {uuid} all")


def demo() -> None:
    """Auto-teste do que dá para testar sem FreeSWITCH: a resolução de caminhos."""
    import tempfile

    with tempfile.TemporaryDirectory() as pasta:
        raiz = Path(pasta).resolve()
        (raiz / "sub").mkdir()
        (raiz / "sub" / "som.wav").write_bytes(b"RIFF")
        fora = Path(pasta).parent / "fora.wav"
        fora.write_bytes(b"RIFF")
        try:
            assert resolve_resource("sub/som.wav", (raiz,)) == raiz / "sub" / "som.wav"
            assert resolve_resource("nao-existe.wav", (raiz,)) is None
            # O que interessa: um caminho que sai da raiz não passa, mesmo
            # existindo — senão dava-se ao FreeSWITCH um ficheiro qualquer do
            # disco para ler em voz alta.
            assert resolve_resource(f"../{fora.name}", (raiz,)) is None
            assert resolve_resource("../../../../etc/passwd", (raiz,)) is None
        finally:
            fora.unlink(missing_ok=True)
    print("sip_audio: resolução de recursos ok")


if __name__ == "__main__":
    demo()
