import os
import random
import platform

import pygame
import pygame.freetype
import moderngl
import time
from array import array

from cave.cave_resources import CaveResources
from config import Config
from effects.splat import Splat
from forest.forest_resources import ForestResources
from game_data import GameData
from post_processing import PostProcessing
from scoreboard.scoreboard_resources import ScoreboardResources
from scores.scores import Scores
from tv_show.tv_show_parent import TvShowParent
from phone_events import PhoneEvents
from tv_show.tv_show_resources import TvShowResources
from tween import Tween
from udp_input import UdpInput
import fullscreen_button
import global_state
import invite_overlay

# Segundos que o cursor e o botão de ecrã inteiro ficam à vista depois de o
# rato parar. Curto o suficiente para não ficar pousado no LED wall, longo o
# suficiente para dar tempo de apontar e carregar.
POINTER_LINGER = 3.0

class Game:
    positions = [
        (0, 0),
        (320, 0),
        (0, 240),
        (320, 240),
    ]

    scores = Scores()
    start_time = time.time()
    waviness = 0
    tv_shows = []
    post_processing = None
    pos_by_country = {}
    effective_attacks = []

    with open("resources/shaders/main.vert", "r") as f:
        vert_shader = f.read()

    with open("resources/shaders/main.frag", "r") as f:
        frag_shader = f.read()

    if platform.system() == "Darwin":
        vert_shader = vert_shader.replace("#version 300 es", "#version 330 core")
        frag_shader = frag_shader.replace("#version 300 es", "#version 330 core")

    def run(self):
        pygame.init()

        # Em macOS é preciso pedir explicitamente o perfil OpenGL core. Tem de ser
        # depois do pygame.init() e antes do set_mode(): no corpo da classe o
        # subsistema de vídeo ainda não existe e isto rebenta logo no import.
        if platform.system() == "Darwin":
            pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)

        fs = pygame.FULLSCREEN if Config.SCR_FULLSCREEN or "FULLSCREEN" in os.environ else 0
        fs |= pygame.OPENGL | pygame.DOUBLEBUF
        # Em ecrã inteiro pede-se a resolução do ambiente de trabalho ((0,0) em
        # SDL2), não 640x480: o quadro é sempre desenhado numa Surface de
        # 640x480 e é o shader que a estica até à janela, portanto o que muda
        # aqui é só o tamanho do alvo.
        pygame.display.set_mode((0, 0) if fs & pygame.FULLSCREEN
                                else (Config.SCR_WIDTH, Config.SCR_HEIGHT), fs)
        display = pygame.Surface((Config.SCR_WIDTH, Config.SCR_HEIGHT))
        ctx = moderngl.create_context(310)

        self.fullscreen = bool(fs & pygame.FULLSCREEN)
        self._fit_viewport(ctx)

        quad_buffer = ctx.buffer(data=array('f', [
            -1.0, 1.0, 0.0, 0.0,
            1.0, 1.0, 1.0, 0.0,
            -1.0, -1.0, 0.0, 1.0,
            1.0, -1.0, 1.0, 1.0,
        ]))

        program = ctx.program(vertex_shader=self.vert_shader, fragment_shader=self.frag_shader)
        render_object = ctx.vertex_array(program, [(quad_buffer, '2f 2f', 'vert', 'texcoord')])
        self.post_processing = PostProcessing()

        loading = pygame.image.load("resources/images/loading.png").convert_alpha()
        display.blit(loading, (0, 0))
        global_state.frame_time = time.time()
        self.render_frame(ctx, display, program, render_object, False)

        pygame.mouse.set_visible(False)
        # Instante até ao qual o cursor e o botão de ecrã inteiro ficam à
        # vista; renovado a cada movimento do rato (ver o ciclo de eventos).
        self.pointer_until = 0.0
        pygame.display.set_caption(Config.TITLE)
        pygame.font.init()

        phone_icons = [pygame.image.load("resources/images/phone" + str(phone_index) + "_small.png").convert_alpha() for phone_index in range(4)]
        phone_icons_active = [pygame.image.load("resources/images/phone" + str(phone_index) + "_small_active.png").convert_alpha() for phone_index in range(4)]
        screens = [pygame.Surface((320, 240)) for _ in range(4)]

        CaveResources.init()
        ForestResources.init()
        ScoreboardResources.init()
        TvShowResources.init()
        Splat.init()

        # O áudio é separado por jogador para chegar ao respetivo telemóvel
        # (webapp) ou auscultador (SIP), cada um através da sua própria porta.
        country_to_port = {
            "ar": 9001, "cl": 9002, "dn": 9003, "fr": 9004,
            "pt1": 9001, "pt2": 9002, "pt3": 9003, "pt4": 9004,
        }
        self.tv_shows = [TvShowParent(GameData(country, country_to_port.get(country, 9001), 0, 0, 0, [], [], [], False, 0, 0)) for country in Config.COUNTRIES]
        self.pos_by_country = {tv_show.country: self.positions[idx] for idx, tv_show in enumerate(self.tv_shows)}

        clock = pygame.time.Clock()
        udp_input = UdpInput()

        running = True
        while running:
            phone_events = [PhoneEvents() for _ in range(4)]

            for event in pygame.event.get():
                # Rato parado é rato escondido: o botão de ecrã inteiro e o
                # cursor só aparecem enquanto alguém está mesmo a mexer, para
                # não ficarem pousados no LED wall durante o evento.
                if event.type == pygame.MOUSEMOTION:
                    self.pointer_until = global_state.frame_time + POINTER_LINGER
                    pygame.mouse.set_visible(True)

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if fullscreen_button.hit(self._surface_pos(event.pos)):
                        self._toggle_fullscreen(ctx)
                        self.pointer_until = global_state.frame_time + POINTER_LINGER
                        continue  # este clique é do botão, não é para sair
                    running = False

                if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == Config.BTN_EXIT):
                    running = False

                if event.type == pygame.KEYDOWN:
                    for i in range(4):
                        if event.key in Config.BTN_OFF_HOOK[i]:
                            phone_events[i].offhook = True
                        if event.key in Config.BTN_HUNG_UP[i]:
                            phone_events[i].hungup = True
                        if event.key in Config.BTN_0[i]:
                            phone_events[i].press_0 = True
                        if event.key in Config.BTN_1[i]:
                            phone_events[i].press_1 = True
                        if event.key in Config.BTN_2[i]:
                            phone_events[i].press_2 = True
                        if event.key in Config.BTN_3[i]:
                            phone_events[i].press_3 = True
                        if event.key in Config.BTN_4[i]:
                            phone_events[i].press_4 = True
                        if event.key in Config.BTN_5[i]:
                            phone_events[i].press_5 = True
                        if event.key in Config.BTN_6[i]:
                            phone_events[i].press_6 = True
                        if event.key in Config.BTN_7[i]:
                            phone_events[i].press_7 = True
                        if event.key in Config.BTN_8[i]:
                            phone_events[i].press_8 = True
                        if event.key in Config.BTN_9[i]:
                            phone_events[i].press_9 = True

            udp_input.drain_into(phone_events)

            pre_render = time.time()

            global_state.frame_time = time.time()

            global_state.any_playing = False
            for tv_show in self.tv_shows:
                if tv_show.is_playing():
                    global_state.any_playing = True

            for tv_show in self.tv_shows:
                index = self.tv_shows.index(tv_show)
                tv_show.handle_events(phone_events[index])
                tv_show.render(screens[index])

            post_render = time.time()

            self.post_processing.handle_events()

            for attack in global_state.attacks:
                global_state.attacks.remove(attack)
                current_country = attack[0]
                effect = attack[1]
                start_time = attack[2]
                valid_shows = [tv_show for tv_show in self.tv_shows if tv_show.country != current_country and tv_show.is_playing()]
                if len(valid_shows) == 0:
                    continue
                random_player = random.choice(valid_shows)
                random_player.external_effect(effect)
                self.effective_attacks.append((current_country, random_player.country, start_time))

            for i in range(4):
                display.blit(screens[i], self.positions[i])

            # Quem está sem jogador e o que a fila vai dizendo. O modo
            # (web/sip) vem do bridge na própria mensagem "slots" (ver
            # udp_input.py); sem bridge a correr, "mode" nem existe e o
            # convite web com QR é a degradação certa.
            slots = udp_input.get_slots()
            occupied = set(slots["occupied"]) if slots else set()
            queue_len = slots["queue_len"] if slots else 0
            mode = slots["mode"] if slots else "web"

            # O cartaz "Hugo / Revenge of the 90s / Liga-te já e joga"
            # (resources/images/logo.png) deixou de ser desenhado. É um véu
            # cinzento a 50% sobre o ecrã inteiro — 80% da imagem está a alpha
            # 128 — e por isso deslavava os quatro vídeos de attract em vez de
            # os tapar de vez, o que dava um ar de ecrã avariado. O ecrã de
            # espera passa a ser o próprio jogo a mexer, com os convites e o QR
            # por cima. A marca já vem dentro dos vídeos.
            if global_state.any_playing:
                for i in range(4):
                    if phone_events[i].any_set():
                        display.blit(phone_icons_active[i], self.positions[i])
                    else:
                        display.blit(phone_icons[i], self.positions[i])

                # Render orbs
                if self.effective_attacks:
                    curr_time = time.time()

                    for attack in self.effective_attacks:
                        pos_0 = self.pos_by_country[attack[0]]
                        pos_1 = self.pos_by_country[attack[1]]
                        dt = curr_time - attack[2]
                        orb_x = Tween.map_ease_in(dt, 0, Config.EFFECT_DURATION_ORB, pos_0[0]+70, pos_1[0]+70)
                        orb_y = Tween.map_ease_in(dt, 0, Config.EFFECT_DURATION_ORB, pos_0[1]+70, pos_1[1]+70)
                        display.blit(Splat.orb, (orb_x, orb_y))
                        if dt > Config.EFFECT_DURATION_ORB:
                            self.effective_attacks.remove(attack)

            if global_state.frame_time < self.pointer_until:
                fullscreen_button.draw(display, self.fullscreen)
            elif pygame.mouse.get_visible():
                pygame.mouse.set_visible(False)

            # Convite nos quadrantes sem jogador — por cima de tudo, para
            # nunca ficar escondido (os `slots` já foram lidos acima).
            for i in range(4):
                if i not in occupied:
                    invite_overlay.draw(display, self.positions[i], global_state.frame_time - self.start_time, queue_len, mode)

            self.render_frame(ctx, display, program, render_object, global_state.any_playing)
            post_shader = time.time()

            render_time = (post_render - pre_render) * 1000
            shader_time = (post_shader - post_render) * 1000
            caption = f"Render: {render_time:06.2f} ms, Shader: {shader_time:06.2f} ms"
            pygame.display.set_caption(caption)

            clock.tick(30)

        # Cleanup all tv shows to stop any playing sounds
        for tv_show in self.tv_shows:
            tv_show.cleanup()

        pygame.quit()

    @staticmethod
    def surf_to_texture(ctx, surf):
        tex = ctx.texture(surf.get_size(), 4)
        tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        tex.swizzle = 'BGRA'
        tex.write(surf.get_view('1'))
        return tex

    def _fit_viewport(self, ctx):
        """Caixa 4:3 centrada na janela, com barras aos lados.

        Sem isto o shader estica os 640x480 até encher a janela e num painel
        16:9 o Hugo sai gordo — num LED wall nota-se de longe. Chamada ao
        arrancar e outra vez sempre que se entra ou sai de ecrã inteiro.

        `get_window_size()` é a medida boa: em ecrã inteiro o
        `get_surface().get_size()` continua a dizer 640x480 (é o tamanho
        lógico pedido), e o viewport do moderngl também não se actualiza
        sozinho.
        """
        win_w, win_h = pygame.display.get_window_size()
        scale = min(win_w / Config.SCR_WIDTH, win_h / Config.SCR_HEIGHT)
        view_w, view_h = int(Config.SCR_WIDTH * scale), int(Config.SCR_HEIGHT * scale)
        self.viewport = ((win_w - view_w) // 2, (win_h - view_h) // 2, view_w, view_h)
        ctx.viewport = self.viewport

    def _surface_pos(self, window_pos):
        """Ponto da janela -> ponto da superfície 640x480 do jogo.

        O rato dá coordenadas da janela; o que está desenhado vive numa caixa
        centrada mais pequena. Sem esta conversão o botão não estaria onde
        parece estar em ecrã inteiro. (A caixa é centrada, portanto a margem
        de cima é igual à de baixo e não é preciso lidar com o eixo Y do
        OpenGL estar ao contrário do da janela.)
        """
        view_x, view_y, view_w, view_h = self.viewport
        return ((window_pos[0] - view_x) * Config.SCR_WIDTH / view_w,
                (window_pos[1] - view_y) * Config.SCR_HEIGHT / view_h)

    def _toggle_fullscreen(self, ctx):
        pygame.display.toggle_fullscreen()
        self.fullscreen = not self.fullscreen
        self._fit_viewport(ctx)

    def render_frame(self, ctx, display, program, render_object, any_playing):
        # Limpa fora da caixa 4:3 — senão as barras ficam com lixo do buffer
        # anterior em vez de pretas.
        ctx.clear(0.0, 0.0, 0.0)
        frame_tex = self.surf_to_texture(ctx, display)
        frame_tex.use(0)
        program['tex'] = 0
        program['time'] = global_state.frame_time - self.start_time
        self.post_processing.apply(program, any_playing)
        render_object.render(mode=moderngl.TRIANGLE_STRIP)
        pygame.display.flip()
        frame_tex.release()

if __name__ == "__main__":
    Game().run()
