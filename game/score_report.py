"""Envia a pontuação final do jogador ao bridge, fire-and-forget.

Disparado uma vez por partida, em `Ending.on_enter` (`tv_show/ending.py`),
quando o jogo entra no estado final — nesse momento `context.forest_score`
já é a pontuação completa: a Floresta soma sacos (`forest/playing.py`) e o
scoreboard consolida tudo em `forest_score` (`tv_show/in_scoreboard.py`); a
Caverna nunca soma pontos próprios, só mostra `forest_score` a subir
(`cave/cave_game.py:14,44-45`) — excepto o multiplicador da corda
(`cave/going_rope.py:45,49,53`, `forest_score *= 2/3/4`), que já correu bem
antes de `cave.ended` ficar True (só os estados terminais `FamilyHappy`/
`LostSpring` o põem True, e ambos vêm depois de `GoingRope` na máquina de
estados da caverna).

Contrato UDP com o bridge (porta nova — NÃO a 9100, que é a entrada de
teclas do jogo, `game/udp_input.py`, nem 9001-9004, que são o áudio por
jogador, `game/audio_helper.py`):

    {"player": 0..3, "score": N}

"player" é o índice do quadrante, derivado da porta de áudio do próprio
jogador (`context.audio_port`, 9001..9004 — ver `game/game.py:101-105` e
`bridge/audio_router.py`, que usa o mesmo índice), não um campo à parte no
`GameData`.

Sem resposta esperada, sem retry, sem thread nova. Um `socket.socket(...,
SOCK_DGRAM)` não ligado nunca bloqueia num `sendto` de um pacote deste
tamanho — não há histórico de bloqueio aqui como houve com o `settimeout(1.0)`
+ `recvfrom` de `audio_helper.py` (bug já medido: 2087ms/frame com um sendto
mal posto a render). Qualquer falha (bridge desligado, porta fechada, jogo
antigo sem rede) é engolida em silêncio — o jogo não pode nem notar que o
bridge existe.
"""
from __future__ import annotations

import json
import logging
import os
import socket

LOGGER = logging.getLogger(__name__)

BRIDGE_HOST = "127.0.0.1"

# 9102 foi a porta sugerida inicialmente, mas colide com
# `bridge/config.yaml: audio.pa_ports` (9101-9104, usados pelo
# `audio-server` local em modo "pa" — ver `bridge/audio_router.py`). Para
# nunca arriscar a mesma porta que o áudio em palco, o valor por omissão
# aqui é 9110; `HUGO_SCORE_PORT` no ambiente substitui-o (produção pode
# mudar a porta sem tocar em código, tal como o resto da configuração do
# bridge, ver `bridge/config.yaml: score.port`).
BRIDGE_SCORE_PORT = int(os.environ.get("HUGO_SCORE_PORT", "9110"))

# Mesmo mapeamento de `game/game.py:101-105` e `bridge/audio_router.py`
# (`ports=[9001, 9002, 9003, 9004]`, índice = jogador).
_FIRST_AUDIO_PORT = 9001
_LAST_AUDIO_PORT = 9004

_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_sock.setblocking(False)


def player_for_audio_port(audio_port: int) -> int | None:
    """Traduz a porta de áudio do jogador (9001..9004) para o índice de
    quadrante (0..3). Fora de gama devolve None em vez de rebentar — chamado
    sempre a partir de `context.audio_port`, que é sempre uma destas quatro
    portas, mas nunca se assume isso sem verificar."""
    if not _FIRST_AUDIO_PORT <= audio_port <= _LAST_AUDIO_PORT:
        return None
    return audio_port - _FIRST_AUDIO_PORT


def send_score(audio_port: int, score: int) -> None:
    """Fire-and-forget: nunca bloqueia, nunca lança, nunca abranda o loop de
    render. `audio_port` é `context.audio_port` (ver `Ending.on_enter`)."""
    player = player_for_audio_port(audio_port)
    if player is None:
        LOGGER.debug("audio_port %r fora de 9001..9004 — pontuação não enviada", audio_port)
        return
    try:
        payload = json.dumps({"player": player, "score": int(score)}).encode("utf-8")
        _sock.sendto(payload, (BRIDGE_HOST, BRIDGE_SCORE_PORT))
    except OSError:
        # Bridge desligado, porta fechada, o que for — o jogo não pode nem
        # notar que o bridge existe (ver bridge/README.md: é one-way).
        LOGGER.debug("Não foi possível enviar a pontuação ao bridge (bridge desligado?)")
