from game_data import GameData
from phone_events import PhoneEvents
from score_report import send_score
from tv_show.tv_show_resources import TvShowResources
from tv_show.video_state import VideoState


class Ending(VideoState):
    def __init__(self, context: GameData):
        super().__init__(context, TvShowResources.videos_ending[context.country], False, TvShowResources.audio_ending[context.country])

    def on_enter(self) -> None:
        super().on_enter()
        # Único sítio: só se chega aqui a partir de `tv_show/in_cave.py`
        # quando `cave.ended` (ver cabeçalho de `game/score_report.py` para
        # a prova de que `context.forest_score` já está completo nesse
        # momento). Fire-and-forget — se o bridge não estiver a correr, ou
        # estiver a correr sem sessão para este jogador, o jogo não nota.
        send_score(self.context.audio_port, self.context.forest_score)

    def process_events(self, phone_events: PhoneEvents):
        super().process_events(phone_events)
        from tv_show.attract import Attract

        if phone_events.hungup:
            return Attract

        return None