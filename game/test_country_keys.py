"""
Prova sem framework de que 4 quadrantes com o mesmo país (COUNTRIES = ["pt1",
"pt2","pt3","pt4"] + COUNTRY_ASSETS a mapear todas para "pt") deixam de
partilhar recursos -- o problema descrito no ticket: TvShowResources guarda
tudo em dicionários indexados pela chave de país, por isso chaves repetidas
faziam os 4 quadrantes colidir no mesmo objeto Video, na mesma posição de
ecrã e esvaziavam a lista de alvos de ataque (game.py:157-162).

Corre com: cd game && ../.venv/bin/python test_country_keys.py "<BigFile>"
"""
import os
import sys

if len(sys.argv) < 2:
    sys.argv.append("/Users/mac/Claude code/hugo-assets/gold/BigFile")

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((640, 480))

from config import Config  # noqa: E402
from game_data import GameData  # noqa: E402
from tv_show.tv_show_resources import TvShowResources  # noqa: E402
from tv_show.tv_show_parent import TvShowParent  # noqa: E402

POSITIONS = [(0, 0), (320, 0), (0, 240), (320, 240)]

RESOURCE_DICTS = (
    "videos_attract", "videos_initial", "videos_press_5", "videos_going_scylla",
    "videos_ending", "videos_have_luck", "audio_attract", "audio_initial",
    "audio_press_5", "audio_going_scylla", "audio_ending", "audio_have_luck",
)


def reset_resources():
    """TvShowResources é preenchido por .init(); limpa os dicionários entre
    cenários para não comparar lixo de uma corrida anterior."""
    for name in RESOURCE_DICTS:
        getattr(TvShowResources, name).clear()


def build_tv_shows(countries):
    """Réplica de game.py:98-100 (não alterado por este teste)."""
    country_to_port = {"ar": 9001, "cl": 9002, "dn": 9003, "fr": 9004}
    tv_shows = [
        TvShowParent(GameData(country, country_to_port.get(country, 9001),
                               0, 0, 0, [], [], [], False, 0, 0))
        for country in countries
    ]
    pos_by_country = {tv_show.country: POSITIONS[idx] for idx, tv_show in enumerate(tv_shows)}
    return tv_shows, pos_by_country


def check_scenario(countries, label):
    reset_resources()
    Config.COUNTRIES = countries
    TvShowResources.init()

    # 1. Os 4 Video de attract têm de ser objetos distintos (não o mesmo
    #    objeto partilhado por colisão de chaves).
    video_ids = {id(TvShowResources.videos_attract[c]) for c in countries}
    assert len(video_ids) == 4, f"[{label}] videos_attract partilha objeto(s): {video_ids}"

    # 1b. E cada um tem de ter mesmo aberto o ficheiro da pasta de assets
    #     mapeada (prova de que os 4 quadrantes carregam os clips certos).
    for c in countries:
        expected_folder = Config.COUNTRY_ASSETS.get(c, c)
        actual_path = TvShowResources.videos_attract[c].path
        assert actual_path == f"resources/videos/{expected_folder}/attract_demo.avi", (
            f"[{label}] {c} carregou {actual_path!r}, esperava a pasta {expected_folder!r}")

    # 2. pos_by_country (game.py:100) tem de ter 4 entradas com 4 posições
    #    distintas.
    tv_shows, pos_by_country = build_tv_shows(countries)
    assert len(pos_by_country) == 4, f"[{label}] pos_by_country colidiu: {pos_by_country}"
    assert len(set(pos_by_country.values())) == 4, f"[{label}] posições repetidas: {pos_by_country}"

    # 3. O filtro de alvos de ataque (game.py:162) não pode ficar vazio.
    #    Um TvShowParent recém-criado começa em Attract (is_playing()==False);
    #    simula-se "a jogar" trocando o estado interno, tal como
    #    handle_events() faria ao mudar de estado.
    for tv_show in tv_shows:
        tv_show._state = object()  # deixa de ser Attract -> is_playing() == True

    current_country = tv_shows[0].country
    valid_targets = [tv_show for tv_show in tv_shows
                     if tv_show.country != current_country and tv_show.is_playing()]
    assert len(valid_targets) == 3, (
        f"[{label}] lista de alvos devia ter 3 jogadores, tem {len(valid_targets)}: "
        f"{[t.country for t in valid_targets]}")

    print(f"OK [{label}]: 4 Video distintos, {len(pos_by_country)} posições distintas, "
          f"{len(valid_targets)} alvos de ataque válidos.")


check_scenario(list(Config.COUNTRIES), "config atual (game/config.py)")
check_scenario(["ar", "cl", "dn", "fr"], "países originais (upstream, sem COUNTRY_ASSETS)")

print("Todos os cenários passaram.")
