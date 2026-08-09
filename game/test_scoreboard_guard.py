import sys

sys.argv.append(".")

import pygame

from resource import Resource
from scoreboard.scoreboard_resources import ScoreboardResources


original_load_surface_res = Resource.__dict__["load_surface_res"]
original_load_surfaces = Resource.__dict__["load_surfaces"]
original_load_sfx = Resource.__dict__["load_sfx"]

try:
    def missing_sprite(name):
        raise FileNotFoundError("asset em falta")

    Resource.load_surface_res = staticmethod(missing_sprite)
    ScoreboardResources.init()
    assert ScoreboardResources.available is False

    sprite1 = pygame.Surface((784, 400), pygame.SRCALPHA)
    sprite2 = pygame.Surface((203, 187), pygame.SRCALPHA)
    Resource.load_surface_res = staticmethod(
        lambda name: sprite1 if name == "scores/sprite1.png" else sprite2
    )
    Resource.load_surfaces = staticmethod(lambda game, name, start, end: [object()] * 10)
    Resource.load_sfx = staticmethod(lambda game, name: game + "/SFX/" + name)

    ScoreboardResources.init()
    assert ScoreboardResources.available is True
    assert ScoreboardResources.background.get_size() == (300, 240)
    assert len(ScoreboardResources.hugo_side) == 16
    assert ScoreboardResources.icon_sack.get_size() == (62, 52)
    assert ScoreboardResources.icon_obstacle_catapult.get_size() == (38, 38)
    assert len(ScoreboardResources.score_font) == 10
finally:
    Resource.load_surface_res = original_load_surface_res
    Resource.load_surfaces = original_load_surfaces
    Resource.load_sfx = original_load_sfx

print("OK: scoreboard ausente é ignorado e os recortes continuam a ser montados")
