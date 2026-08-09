"""Prova sem framework: `score_report.py` + `Ending.on_enter` mandam a
pontuação final ao bridge, fire-and-forget, sem bloquear o loop de render.

Corre com: cd game && ../.venv/bin/python test_score_report.py
"""
import json
import socket
import time

import audio_helper
import global_state
import score_report
import tv_show.ending as ending_module
from game_data import GameData
from tv_show.ending import Ending
from tv_show.tv_show_resources import TvShowResources


class FakeVideo:
    """Dobre de `pyvidplayer2.Video` — só o que `VideoState.on_enter` toca."""

    def __init__(self):
        self.active = False
        self.restart_calls = 0

    def restart(self):
        self.restart_calls += 1
        self.active = True


def make_context(audio_port, forest_score):
    return GameData(
        country="pt1",
        audio_port=audio_port,
        forest_score=forest_score,
        forest_lives=0,
        forest_parallax_pos=0,
        forest_sacks=[],
        forest_obstacles=[],
        forest_leaves=[],
        forest_controls_inverted=False,
    )


# 1. Mapeamento porta de áudio -> jogador (ver game/game.py:101-105).
for port, expected in [(9001, 0), (9002, 1), (9003, 2), (9004, 3)]:
    got = score_report.player_for_audio_port(port)
    assert got == expected, f"porta {port} devia mapear para {expected}, deu {got}"
assert score_report.player_for_audio_port(9100) is None
assert score_report.player_for_audio_port(9999) is None
print("OK 1: mapeamento porta de áudio -> jogador")

# 2. send_score nunca bloqueia, com ou sem bridge à escuta.
start = time.time()
score_report.send_score(9999, 12345)  # porta fora de gama: sai logo, sem enviar nada
elapsed = time.time() - start
assert elapsed < 0.05, f"send_score(porta inválida) demorou {elapsed * 1000:.0f}ms"
print(f"OK 2a: send_score(porta inválida) devolve-se em {elapsed * 1000:.2f}ms")

start = time.time()
score_report.send_score(9001, 500)  # porta válida, quase de certeza sem bridge a ouvir aqui
elapsed = time.time() - start
assert elapsed < 0.05, f"send_score(sem bridge) demorou {elapsed * 1000:.0f}ms"
print(f"OK 2b: send_score(sem bridge a ouvir) devolve-se em {elapsed * 1000:.2f}ms")

# 3. Um socket UDP real a ouvir na porta de pontuação recebe o formato certo.
listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
listener.bind(("127.0.0.1", 0))
listener.settimeout(1.0)
old_port = score_report.BRIDGE_SCORE_PORT
score_report.BRIDGE_SCORE_PORT = listener.getsockname()[1]
try:
    score_report.send_score(9003, 777)
    data, _addr = listener.recvfrom(4096)
finally:
    score_report.BRIDGE_SCORE_PORT = old_port
    listener.close()
msg = json.loads(data)
assert msg == {"player": 2, "score": 777}, msg
print("OK 3: pacote UDP chega ao bridge com {'player','score'}")

# 4. Ending.on_enter manda a pontuação final uma vez, sem bloquear — vídeo e
# áudio substituídos por dobres para não depender de ficheiros da BigFile
# nem de um audio-server a sério a responder ao PLAY (AudioHelper.play tem
# settimeout(1.0), ver audio_helper.py — não é o que se está a testar aqui).
sent = []
# `tv_show/ending.py` faz `from score_report import send_score` — o nome
# fica ligado no módulo `tv_show.ending`, não em `score_report`; é aí que
# se substitui, senão o dobre nunca é chamado.
original_send_score = ending_module.send_score
ending_module.send_score = lambda audio_port, score: sent.append((audio_port, score))

original_play = audio_helper.AudioHelper.play
audio_helper.AudioHelper.play = staticmethod(lambda resource, port, loops=0: None)

TvShowResources.videos_ending["pt1"] = FakeVideo()
TvShowResources.audio_ending["pt1"] = "audio_for_videos/pt1/you_lost.wav"

try:
    global_state.frame_time = 100.0
    ctx = make_context(audio_port=9001, forest_score=4200)
    ending = Ending(ctx)
    start = time.time()
    ending.on_enter()
    elapsed = time.time() - start
finally:
    ending_module.send_score = original_send_score
    audio_helper.AudioHelper.play = original_play

assert sent == [(9001, 4200)], sent
assert ending.video.restart_calls == 1, "on_enter tem de reiniciar o vídeo como sempre fez"
assert elapsed < 0.05, f"Ending.on_enter demorou {elapsed * 1000:.0f}ms"
print(f"OK 4: Ending.on_enter mandou a pontuação final {sent[0]} em {elapsed * 1000:.2f}ms")

print("Todos os cenários passaram.")
