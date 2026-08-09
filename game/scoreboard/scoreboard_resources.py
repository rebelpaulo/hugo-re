import os

import pygame

from resource import Resource


class ScoreboardResources:
    available = False

    background = None

    hugo_side = None

    icon_sack = None
    icon_finish = None
    icon_golden_sack = None

    icon_total = None

    icon_obstacle_catapult = None
    icon_obstacle_trap = None
    icon_obstacle_rock = None
    icon_obstacle_branch = None
    icon_death_bg = None

    icon_negative = None

    score_font = None

    score_counter = None

    @staticmethod
    def init():
        try:
            asset = "scores/sprite1.png"
            sprite1 = Resource.load_surface_res("scores/sprite1.png")
            asset = "scores/sprite2.png"
            sprite2 = Resource.load_surface_res("scores/sprite2.png")
        except FileNotFoundError:
            filename = "resources/" + asset
            print(f"Aviso: scoreboard indisponível; falta o ficheiro '{filename}', esperado em '{os.path.abspath(filename)}'.")
            ScoreboardResources.available = False
            return

        bg_crop = sprite1.subsurface(pygame.Rect(464, 144, 320, 256))
        ScoreboardResources.background = pygame.transform.scale(bg_crop, (300, 240))

        ScoreboardResources.hugo_side = []
        for row_y in [40, 134, 228, 322]:
            for col_x in [17, 129, 241, 353]:
                ScoreboardResources.hugo_side.append(sprite1.subsurface(pygame.Rect(col_x, row_y, 93, 77)))

        ScoreboardResources.icon_sack = sprite1.subsurface(pygame.Rect(465, 35, 62, 52))
        ScoreboardResources.icon_golden_sack = sprite1.subsurface(pygame.Rect(538, 39, 42, 48))
        ScoreboardResources.icon_finish = sprite1.subsurface(pygame.Rect(471, 91, 52, 50))

        ScoreboardResources.icon_total = sprite1.subsurface(pygame.Rect(592, 108, 73, 15))

        ScoreboardResources.icon_obstacle_catapult = sprite2.subsurface(pygame.Rect(165, 149, 38, 38))
        ScoreboardResources.icon_obstacle_trap = sprite2.subsurface(pygame.Rect(117, 149, 38, 38))
        ScoreboardResources.icon_obstacle_rock = sprite2.subsurface(pygame.Rect(69, 149, 38, 38))
        ScoreboardResources.icon_obstacle_branch = sprite2.subsurface(pygame.Rect(69, 149, 38, 38))
        ScoreboardResources.icon_death_bg = sprite1.subsurface(pygame.Rect(592, 41, 50, 46))

        ScoreboardResources.icon_negative = sprite1.subsurface(pygame.Rect(675, 92, 15, 24))

        ScoreboardResources.score_font = Resource.load_surfaces("RopeOutroData", "SCORE.cgf", 0, 9)

        ScoreboardResources.score_counter = Resource.load_sfx("RopeOutroData", "COUNTER.WAV")
        ScoreboardResources.available = True
