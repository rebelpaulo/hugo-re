"""
Prova sem framework: compara o forest_score final nos dois caminhos possíveis
quando a floresta acaba —

  a) scoreboard disponível  -> ScoreboardGame calcula tudo e no fim atribui
     self.total_score a context.forest_score (ver scoreboard_game.py:120).
  b) scoreboard indisponível (sprites em falta) -> InScoreboard salta a
     apresentação, mas agora chama ScoreboardGame.compute_total_score() para
     que o forest_score fique igual ao caminho (a).

Corre com: cd game && ../.venv/bin/python test_forest_score.py
"""
import sys

# Resource.DATA_DIR exige um argv[1]; não é lido a sério neste teste porque
# nunca chamamos ScoreboardResources.init() nem TvShowResources.init().
if len(sys.argv) < 2:
    sys.argv.append("/Users/mac/Claude code/hugo-assets/gold/BigFile")

from game_data import GameData  # noqa: E402
from scoreboard.scoreboard_game import ScoreboardGame  # noqa: E402
from scoreboard.scoreboard_resources import ScoreboardResources  # noqa: E402
from tv_show.in_scoreboard import InScoreboard  # noqa: E402


def make_context(normal_sacks, golden_sacks, reached_end, lives_lost):
    return GameData(
        country="pt",
        audio_port=0,
        forest_score=0,
        forest_lives=3 - lives_lost,
        forest_parallax_pos=0,
        forest_sacks=[],
        forest_obstacles=[],
        forest_leaves=[],
        forest_controls_inverted=False,
        forest_normal_sacks_collected=normal_sacks,
        forest_golden_sacks_collected=golden_sacks,
        forest_reached_end=reached_end,
    )


def score_with_scoreboard(ctx):
    """Caminho (a): o que o scoreboard atribuiria a context.forest_score no fim (linha 120)."""
    return ScoreboardGame(ctx).total_score


def score_without_scoreboard(ctx):
    """Caminho (b): o que o InScoreboard produz quando os sprites faltam."""
    was_available = ScoreboardResources.available
    ScoreboardResources.available = False
    try:
        InScoreboard(ctx)  # o __init__ já atribui context.forest_score no caminho de salto
    finally:
        ScoreboardResources.available = was_available
    return ctx.forest_score


scenarios = [
    # (nome, sacos normais, sacos dourados, fim alcançado, vidas perdidas, total esperado)
    ("repro do ticket", 5, 1, True, 1, 2150),
    ("vidas perdidas diferente", 5, 1, True, 3, 1950),
]

for name, normal, golden, reached_end, lives_lost, expected in scenarios:
    with_sb = score_with_scoreboard(make_context(normal, golden, reached_end, lives_lost))
    without_sb = score_without_scoreboard(make_context(normal, golden, reached_end, lives_lost))

    assert with_sb == expected, f"[{name}] scoreboard disponível deu {with_sb}, esperava {expected}"
    assert without_sb == expected, f"[{name}] scoreboard indisponível deu {without_sb}, esperava {expected}"
    assert with_sb == without_sb, f"[{name}] os dois caminhos divergem: {with_sb} != {without_sb}"

    print(f"OK [{name}]: disponível={with_sb} indisponível={without_sb} (esperado {expected})")

print("Todos os cenários passaram.")
