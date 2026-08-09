import pygame


class Config:
    TITLE = "Hugo - Into the Multiverse"
    SCR_WIDTH = 640
    SCR_HEIGHT = 480
    SCR_FULLSCREEN = False

    GOD_MODE = False

    EFFECT_DURATION_SPLAT = 2.5
    EFFECT_DURATION_ORB = 0.5
    EFFECT_DURATION_INVERT = 3
    INSTRUCTIONS_TIMEOUT = 3
    ARGENTINE_VERSION = True

    # Nota para o Mac: as teclas F só chegam ao jogo se estiver ligado
    # "Usar F1, F2, etc. como teclas de função padrão" nas Definições do
    # Sistema; caso contrário é preciso carregar em Fn ao mesmo tempo.
    BTN_OFF_HOOK = [(pygame.K_F1,), (pygame.K_F3,), (pygame.K_F5,), (pygame.K_F7,)]
    BTN_HUNG_UP = [(pygame.K_F2,), (pygame.K_F4,), (pygame.K_F6,), (pygame.K_F8,)]
    # Não há tecla de saída. Havia F12 (`BTN_EXIT`), e o upstream fechava
    # também a qualquer clique esquerdo — num evento, com o ecrã ao alcance
    # de toda a gente, é fechar o jogo à frente da sala. Fecha-se por Cmd+Q,
    # por fechar a janela, ou parando o supervisor.

    # Cada jogador tem um tuplo de teclas aceites para o mesmo botão.
    #
    # O jogador 4 usava só o teclado numérico, que não existe num MacBook — o
    # quarto quadrante ficava impossível de jogar. O teclado numérico mantém-se
    # (para um teclado externo no evento) e junta-se-lhe um conjunto que existe
    # em qualquer teclado: setas para as direções, e letras livres para o resto.
    BTN_1 = [(pygame.K_1,), (pygame.K_4,), (pygame.K_7,), (pygame.K_KP1, pygame.K_v)]
    BTN_2 = [(pygame.K_2,), (pygame.K_5,), (pygame.K_8,), (pygame.K_KP2, pygame.K_UP)]
    BTN_3 = [(pygame.K_3,), (pygame.K_6,), (pygame.K_9,), (pygame.K_KP3, pygame.K_p)]
    BTN_4 = [(pygame.K_q,), (pygame.K_r,), (pygame.K_u,), (pygame.K_KP4, pygame.K_LEFT)]
    BTN_5 = [(pygame.K_w,), (pygame.K_t,), (pygame.K_i,), (pygame.K_KP5, pygame.K_m)]
    BTN_6 = [(pygame.K_e,), (pygame.K_y,), (pygame.K_o,), (pygame.K_KP6, pygame.K_RIGHT)]
    BTN_7 = [(pygame.K_a,), (pygame.K_f,), (pygame.K_j,), (pygame.K_KP7, pygame.K_COMMA)]
    BTN_8 = [(pygame.K_s,), (pygame.K_g,), (pygame.K_k,), (pygame.K_KP8, pygame.K_DOWN)]
    BTN_9 = [(pygame.K_d,), (pygame.K_h,), (pygame.K_l,), (pygame.K_KP9, pygame.K_n)]
    BTN_0 = [(pygame.K_z,), (pygame.K_x,), (pygame.K_c,), (pygame.K_KP0, pygame.K_b)]

    COUNTRIES = ["pt1", "pt2", "pt3", "pt4"]

    # Os 4 quadrantes precisam de chaves distintas em COUNTRIES para que os
    # dicionários de recursos em TvShowResources (indexados por país) lhes
    # dêem objetos Video/áudio independentes. Este mapa diz a cada chave qual
    # a pasta de assets a carregar — os quatro quadrantes PT apontam para a
    # mesma pasta "pt", mas cada um fica com o seu próprio Video.
    COUNTRY_ASSETS = {"pt1": "pt", "pt2": "pt", "pt3": "pt", "pt4": "pt"}

    GAMES = {
        "Forest": {
            "name": "Selva",
        }
    }

    FOREST_BG_SPEED_MULTIPLIER = 1.0
    FOREST_GROUND_SPEED = 75
    FOREST_MAX_TIME = 45
