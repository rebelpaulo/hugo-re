"""Servidor HTTP + WebSocket do bridge.

Serve a webapp (estática), o QR do lobby, os sons do jogo, e liga cada ligação
WebSocket a uma sessão no `SlotManager`. Não sabe nada de SIP/ARI — isso é o B3.

Contrato WebSocket (`/ws`), fixo com a webapp:

    Cliente -> servidor:
        {"type":"hello","mode":"web"}
        {"type":"press","key":"5"}          key em 0-9, "*", "#"
        {"type":"offhook"} / {"type":"hangup"} / {"type":"confirm"} / {"type":"ping"}
        {"type":"name","name":"HUGO"}       só depois de "finished", uma vez (ver secção "Pontuação")

    Servidor -> cliente:
        {"type":"config","input_mode":"web"}        enviado logo na ligação, antes de tudo
        {"type":"slot","player":2,"color":"red"}
        {"type":"queued","position":3,"ahead":2}
        {"type":"your_turn","player":2,"seconds":15}
        {"type":"released"}
        {"type":"finished"}
        {"type":"top10","entries":[{"name":"HUGO","score":4200},...],"own":{"name":"HUGO","score":4200}|null}
        {"type":"pong"}
        {"type":"audio","action":"play","resource":"...","loops":0,"id":7}
        {"type":"audio","action":"stop","id":7}

`input_mode` é a definição de produção em `config.yaml` (web/sip — ver
`bridge/README.md`), enviada assim que o WebSocket liga, para a webapp saber
se deve entrar na fila/teclado ou mostrar a mensagem de "hoje é por
telefone" — os dois modos nunca se cruzam no mesmo evento. Mensagem nova,
acrescentada a um contrato que já existia — nada do resto mudou.
"""

from __future__ import annotations

import asyncio
import ast
import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Callable

import yaml
from aiohttp import WSMsgType, web

from audio_router import AudioRouter
from score_store import ScoreStore, start_score_listener
from slot_manager import Decision, SlotManager


LOGGER = logging.getLogger("bridge.web_adapter")

# Tipo do áudio servido. Tem de ser posto à mão no `FileResponse`: o
# `web.FileResponse` do aiohttp adivinha a partir de uma instância própria de
# `mimetypes`, criada no import dele, que não vê um `mimetypes.add_type()`
# nosso — tentei por aí primeiro e a resposta continuou a sair como
# `application/octet-stream`. Não estraga a webapp (faz `fetch` +
# `decodeAudioData` sobre o ArrayBuffer e nunca olha para o cabeçalho), mas um
# `<audio src=...>` ou um proxy pelo meio podem tropeçar nisso.
AUDIO_CONTENT_TYPE = "audio/mp4"

WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
QR_PATH = REPO_ROOT / "game" / "resources" / "images" / "qr_lobby.png"
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

VALID_INPUT_MODES = ("web", "sip")
DEFAULT_INPUT_MODE = "web"

# Sem `ping` do cliente durante este tempo, a sessão perde o slot.
HEARTBEAT_TIMEOUT_SECONDS = 15.0

COLOR_BY_PLAYER = ["blue", "green", "red", "white"]

KEY_TO_EVENT = {str(digit): f"press_{digit}" for digit in range(10)}
KEY_TO_EVENT["*"] = "press_star"
KEY_TO_EVENT["#"] = "press_pound"

PLACEHOLDER_HTML = """<!doctype html>
<html lang="pt">
<head><meta charset="utf-8"><title>Hugo — a arrancar</title></head>
<body style="font-family: sans-serif; text-align:center; margin-top:15vh;">
<h1>A webapp está a ser construída</h1>
<p>Volta a tentar dentro de instantes.</p>
</body>
</html>"""


def load_input_mode(config_path: Path = CONFIG_PATH) -> str:
    """Lê `input_mode` de `config.yaml` (web/sip — ver bridge/README.md).

    Ficheiro ausente, chave ausente ou valor inválido caem todos em "web" (o
    modo mais restrito para o público — nunca deixa alguém cair sem querer
    numa fila que não devia existir). Um valor inválido fica registado."""
    try:
        with config_path.open(encoding="utf-8") as config_file:
            config = yaml.safe_load(config_file) or {}
    except (OSError, yaml.YAMLError) as exc:
        LOGGER.warning("Não foi possível ler %s (%s) — a usar input_mode=%s", config_path, exc, DEFAULT_INPUT_MODE)
        return DEFAULT_INPUT_MODE
    mode = config.get("input_mode", DEFAULT_INPUT_MODE)
    if mode not in VALID_INPUT_MODES:
        LOGGER.warning("input_mode=%r inválido em %s — a usar %s", mode, config_path, DEFAULT_INPUT_MODE)
        return DEFAULT_INPUT_MODE
    return mode


def decision_to_message(decision: Decision, clock: Callable[[], float]) -> dict | None:
    """Traduz uma `Decision` do SlotManager para o contrato JSON da webapp.

    Decisões sem mensagem própria (forwarded, ignored, touched, disconnected,
    rejected, waiting, match_ended) devolvem ``None`` — não fazem parte do
    contrato fixo do lado do cliente web.
    """
    if decision.kind == "assigned":
        return {"type": "slot", "player": decision.player, "color": COLOR_BY_PLAYER[decision.player]}
    if decision.kind == "queue_status":
        return {"type": "queued", "position": decision.position, "ahead": decision.ahead}
    if decision.kind == "offer":
        seconds = max(0, round(decision.deadline - clock()))
        return {"type": "your_turn", "player": decision.player, "seconds": seconds}
    if decision.kind == "released":
        # `reason="match_ended"` só acontece via `SlotManager.release_player`
        # (fim de partida detectado no áudio, ver AudioRouter/create_app
        # abaixo) — mensagem própria, nova, para a sessão distinguir "a tua
        # partida acabou" de "perdeste o lugar" (timeout/desconexão). Depois
        # desta mensagem a sessão fica "idle" no SlotManager: `handle_event`
        # já ignora teclas de sessões não activas, então nenhum código extra
        # é preciso para bloquear o teclado — uma sessão nova entra na fila
        # normalmente, como qualquer pessoa.
        if decision.reason == "match_ended":
            return {"type": "finished"}
        return {"type": "released"}
    return None


class WebBridge:
    """Liga sessões WebSocket ao SlotManager: source_id estável, heartbeat, encaminhamento."""

    def __init__(
        self,
        manager: SlotManager,
        *,
        heartbeat_timeout: float = HEARTBEAT_TIMEOUT_SECONDS,
        input_mode: str = DEFAULT_INPUT_MODE,
        score_store: ScoreStore | None = None,
    ) -> None:
        self.manager = manager
        self.heartbeat_timeout = heartbeat_timeout
        self.input_mode = input_mode
        self.score_store = score_store
        self._sockets: dict[str, web.WebSocketResponse] = {}
        # Sessões elegíveis para mandar UM "name": armado quando "finished"
        # sai para o cliente (ver route() abaixo), consumido em
        # _handle_name — nunca por session.player do SlotManager, que já
        # voltou a None assim que o lugar foi libertado (ver
        # `release_player`/`_release_active` em slot_manager.py).
        self._finished_players: dict[str, int] = {}

    async def route(self, decisions: list[Decision]) -> None:
        """Encaminha cada Decision para a sessão certa.

        Uma oferta perdida sem confirmação (`offer_expired`) volta
        automaticamente ao fim da fila — a webapp não tem forma própria de
        pedir isso outra vez, e ficar parada não é uma opção em palco.
        """
        for decision in decisions:
            if decision.kind == "offer_expired" and decision.source_type == "web":
                await self.route(self.manager.request_slot(decision.source_id))
                continue
            message = decision_to_message(decision, self.manager.clock)
            if message is None or decision.source_id is None:
                continue
            if message.get("type") == "finished" and self.score_store is not None:
                self._finished_players[decision.source_id] = decision.player
            ws = self._sockets.get(decision.source_id)
            if ws is None or ws.closed:
                continue
            try:
                await ws.send_json(message)
            except ConnectionResetError:
                LOGGER.debug("Sessão %s fechou antes de receber %s", decision.source_id, message)

    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=None)
        await ws.prepare(request)

        source_id = uuid.uuid4().hex
        self._sockets[source_id] = ws
        last_ping = time.monotonic()

        # Logo na ligação, antes de qualquer "hello": a webapp precisa disto
        # para saber que ecrã mostrar sem ter de perguntar ao utilizador.
        await ws.send_json({"type": "config", "input_mode": self.input_mode})

        try:
            while True:
                remaining = self.heartbeat_timeout - (time.monotonic() - last_ping)
                if remaining <= 0:
                    LOGGER.info("Sessão %s perdeu o heartbeat (sem ping)", source_id)
                    break
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=remaining)
                except asyncio.TimeoutError:
                    LOGGER.info("Sessão %s perdeu o heartbeat (sem ping)", source_id)
                    break

                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if not isinstance(data, dict):
                        continue
                    if data.get("type") == "ping":
                        last_ping = time.monotonic()
                    await self._handle_message(source_id, data)
                elif msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED, WSMsgType.ERROR):
                    break
        finally:
            del self._sockets[source_id]
            self._finished_players.pop(source_id, None)
            await self.route(self.manager.disconnect(source_id))
            if not ws.closed:
                await ws.close()
        return ws

    async def _handle_message(self, source_id: str, data: dict) -> None:
        mtype = data.get("type")
        if mtype == "ping":
            self.manager.touch(source_id)
            ws = self._sockets.get(source_id)
            if ws is not None and not ws.closed:
                await ws.send_json({"type": "pong"})
        elif mtype == "hello":
            await self.route(self.manager.connect(source_id, "web"))
        elif mtype == "press":
            event = KEY_TO_EVENT.get(str(data.get("key")))
            if event is not None:
                await self.route(self.manager.handle_event(source_id, event))
        elif mtype == "offhook":
            await self.route(self.manager.handle_event(source_id, "offhook"))
        elif mtype == "hangup":
            await self.route(self.manager.handle_event(source_id, "hungup"))
        elif mtype == "confirm":
            await self.route(self.manager.confirm(source_id))
        elif mtype == "name":
            await self._handle_name(source_id, data)
        else:
            LOGGER.debug("Sessão %s enviou mensagem desconhecida: %r", source_id, mtype)

    async def _handle_name(self, source_id: str, data: dict) -> None:
        """`{"type":"name","name":"..."}` — só aceite de uma sessão que
        acabou de receber "finished", e só uma vez (`pop`, ver __init__)."""
        if self.score_store is None:
            return
        player = self._finished_players.pop(source_id, None)
        if player is None:
            LOGGER.debug("Sessão %s mandou 'name' sem estar elegível — ignorado", source_id)
            return
        entry = self.score_store.submit(player, data.get("name"))
        message = {"type": "top10", "entries": self.score_store.top10(), "own": entry}
        ws = self._sockets.get(source_id)
        if ws is not None and not ws.closed:
            try:
                await ws.send_json(message)
            except ConnectionResetError:
                LOGGER.debug("Sessão %s fechou antes de receber o top10", source_id)


_RESOURCE_CALL_RE = re.compile(r'load_(speak|sfx)\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)')


def _class_literal_values(path: Path, class_name: str) -> dict[str, object]:
    """Lê atribuições literais de uma classe sem importar o jogo (pygame)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        values: dict[str, object] = {}
        for statement in node.body:
            if (
                isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
            ):
                try:
                    values[statement.targets[0].id] = ast.literal_eval(statement.value)
                except (ValueError, TypeError):
                    pass
        return values
    return {}


def _tv_show_audio_resources(repo_root: Path, *, attrs: frozenset[str] | None = None) -> set[str]:
    """Deriva as vozes do programa de TV do próprio código do jogo.

    `TvShowResources` constrói cada caminho a partir de `audio_prefix` dentro
    do ciclo por `Config.COUNTRIES`. Lemos a sua AST em vez de importar pygame
    ou manter aqui uma segunda lista manual dos seis ficheiros.

    `attrs`, se dado, restringe a leitura aos atributos `TvShowResources.*`
    indicados (ex.: `{"audio_ending"}`) — usado pela detecção de fim de
    partida em `_tv_show_ending_resources`, para não confundir o som de fim
    com os outros cinco (attract, initial, press_5, going_scylla, have_luck).
    """
    config = _class_literal_values(repo_root / "game" / "config.py", "Config")
    countries = config.get("COUNTRIES", [])
    country_assets = config.get("COUNTRY_ASSETS", {})
    if not isinstance(countries, list) or not isinstance(country_assets, dict):
        return set()

    tv_path = repo_root / "game" / "tv_show" / "tv_show_resources.py"
    tree = ast.parse(tv_path.read_text(encoding="utf-8"), filename=str(tv_path))
    filenames: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target, value = node.targets[0], node.value
        if not (
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Attribute)
            and isinstance(target.value.value, ast.Name)
            and target.value.value.id == "TvShowResources"
            and target.value.attr.startswith("audio_")
            and (attrs is None or target.value.attr in attrs)
            and isinstance(value, ast.BinOp)
            and isinstance(value.op, ast.Add)
            and isinstance(value.left, ast.Name)
            and value.left.id == "audio_prefix"
            and isinstance(value.right, ast.Constant)
            and isinstance(value.right.value, str)
        ):
            continue
        filenames.add(value.right.value)

    resources: set[str] = set()
    for country in countries:
        if not isinstance(country, str):
            continue
        assets = country_assets.get(country, country)
        if isinstance(assets, str):
            resources.update(f"audio_for_videos/{assets}/{filename}" for filename in filenames)
    return resources


def _tv_show_ending_resources(repo_root: Path) -> frozenset[str]:
    """Só o(s) recurso(s) de fim-de-partida (`TvShowResources.audio_ending`,
    tocado uma única vez ao entrar em `tv_show/ending.py` — ver
    `game/tv_show/in_cave.py:19`, só chega lá quando `cave.ended`).

    Usado pelo `AudioRouter` para detectar o fim da partida sem o nome do
    ficheiro (`you_lost.wav`) escrito à mão aqui — deriva-se do código do
    jogo tal como `build_audio_manifest`. Falha de leitura (jogo mudou de
    forma inesperada) devolve conjunto vazio: a detecção fica desligada em
    vez de arriscar apanhar o som errado."""
    try:
        return frozenset(_tv_show_audio_resources(repo_root, attrs=frozenset({"audio_ending"})))
    except (OSError, SyntaxError, ValueError) as exc:
        LOGGER.warning(
            "Não consegui derivar o recurso de fim de partida de %s (%s) — "
            "detecção de fim de partida desligada",
            repo_root / "game" / "tv_show" / "tv_show_resources.py",
            exc,
        )
        return frozenset()


def build_audio_manifest(repo_root: Path) -> list[str]:
    """Lista o áudio da Floresta, Caverna e programa de TV, só por leitura.

    A lista do programa de TV vem de `TvShowResources` + `Config`, para os
    países configurados, sem importar o jogo nem duplicar nomes de ficheiros.
    Um recurso fora do manifesto continua servido, só carrega mais tarde.
    """
    resources: set[str] = set()
    for sub in ("game/forest", "game/cave"):
        base = repo_root / sub
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for kind, game, filename in _RESOURCE_CALL_RE.findall(text):
                if kind == "speak":
                    sub_dir = "speak" if game == "RopeOutroData" else "speaks"
                else:
                    sub_dir = "SFX" if game == "RopeOutroData" else "sfx"
                resources.add(f"{game}/{sub_dir}/{filename}")
    resources.update(_tv_show_audio_resources(repo_root))
    return sorted(resources)


def _conversion_lock(app: web.Application, key: str) -> asyncio.Lock:
    locks: dict[str, asyncio.Lock] = app.setdefault("audio_convert_locks", {})
    lock = locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        locks[key] = lock
    return lock


async def _convert_to_aac(source: Path, dest: Path) -> None:
    """Converte para AAC/mono num contentor `.m4a` — formato que qualquer
    browser relevante descodifica com `decodeAudioData`, a uma fracção do
    tamanho do PCM16 que se usava antes (~10x mais pequeno, ver bridge/README).
    Os `pcm_u8` a 22kHz do jogo original são o risco (nem todo o browser os
    aceita); convertem-se todos por igual. 80k é sobra para voz/efeitos de um
    jogo de 1990 — não é música de alta fidelidade."""
    tmp = dest.with_suffix(".tmp.m4a")
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-ac",
        "1",
        "-ar",
        "44100",
        "-c:a",
        "aac",
        "-b:a",
        "80k",
        str(tmp),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not tmp.is_file():
        tmp.unlink(missing_ok=True)
        raise web.HTTPInternalServerError(
            text=f"Falha ao converter {source.name}: {stderr.decode(errors='replace')[-500:]}"
        )
    tmp.replace(dest)


async def audio_handler(request: web.Request) -> web.StreamResponse:
    """`GET /audio/<recurso>` — devolve o `.m4a` (AAC) já convertido, convertendo-o
    (e pondo em cache) na primeira vez que é pedido."""
    resource = request.match_info["resource"]
    source_paths: tuple[Path, ...] = request.app["audio_source_paths"]
    cache_dir: Path = request.app["audio_cache_dir"]
    source: Path | None = None
    source_root: Path | None = None

    # O mesmo recurso pode vir da BigFile ou de game/resources. A verificação
    # de travessia vale de forma independente para cada raiz, antes de sequer
    # considerar se o ficheiro existe nessa origem.
    for root in source_paths:
        candidate = (root / resource).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            raise web.HTTPForbidden()
        if candidate.is_file():
            source = candidate
            source_root = root
            break
    if source is None or source_root is None:
        raise web.HTTPNotFound()

    # O destino da cache também tem de ser validado, não só a origem. Um
    # recurso com `..` pode resolver para uma origem legítima dentro de
    # uma raiz e ainda assim apontar o ficheiro convertido para fora da
    # cache — seria escrita arbitrária a partir de um pedido HTTP.
    # Derivamos o caminho da cache a partir da origem já validada, não da
    # string que o cliente enviou.
    cached = (cache_dir / source.relative_to(source_root)).with_suffix(".m4a")
    try:
        cached.resolve().relative_to(cache_dir.resolve())
    except ValueError:
        raise web.HTTPForbidden()

    async with _conversion_lock(request.app, str(source)):
        if not cached.is_file() or cached.stat().st_mtime < source.stat().st_mtime:
            cached.parent.mkdir(parents=True, exist_ok=True)
            await _convert_to_aac(source, cached)
    return web.FileResponse(cached, headers={"Content-Type": AUDIO_CONTENT_TYPE})


async def audio_manifest_handler(request: web.Request) -> web.StreamResponse:
    """`GET /audio-manifest.json` — lista de recursos para a webapp pré-carregar."""
    return web.json_response(request.app["audio_manifest"])


async def top10_handler(request: web.Request) -> web.StreamResponse:
    """`GET /top10` — o top10 da sessão activa (ver `score_store.py`), em
    JSON. Mesma lista que a webapp já recebe embutida na resposta ao
    "name"; existe também como rota própria para outros ecrãs (ex. o LED
    grande) puderem ler sem passar pelo WebSocket."""
    store: ScoreStore | None = request.app.get("score_store")
    if store is None:
        raise web.HTTPNotFound()
    return web.json_response(store.top10())


async def qr_handler(request: web.Request) -> web.StreamResponse:
    if QR_PATH.is_file():
        return web.FileResponse(QR_PATH)
    raise web.HTTPNotFound(text="QR ainda não foi gerado")


async def webapp_handler(request: web.Request) -> web.StreamResponse:
    """Serve `bridge/webapp/` estaticamente; se a pasta ainda estiver vazia, mostra um aviso."""
    tail = request.match_info.get("tail", "") or "index.html"
    if WEBAPP_DIR.is_dir():
        candidate = (WEBAPP_DIR / tail).resolve()
        try:
            candidate.relative_to(WEBAPP_DIR.resolve())
        except ValueError:
            raise web.HTTPForbidden()
        if candidate.is_file():
            return web.FileResponse(candidate)
    if tail == "index.html":
        return web.Response(text=PLACEHOLDER_HTML, content_type="text/html")
    raise web.HTTPNotFound()


def create_app(
    manager: SlotManager,
    *,
    heartbeat_timeout: float = HEARTBEAT_TIMEOUT_SECONDS,
    audio_config: dict | None = None,
    input_mode: str | None = None,
    score_config: dict | None = None,
) -> tuple[web.Application, Callable[[list[Decision]], "asyncio.Future[None]"]]:
    """Constrói a app aiohttp; devolve também `route` para o tick periódico do main.py usar.

    `audio_config` é a secção `audio` do `config.yaml` (ver `bridge/README.md`).
    Sem ela (`None`), o router de áudio simplesmente não arranca — usado pelos
    testes existentes que não precisam de áudio.

    `input_mode` é "web"/"sip" (ver `bridge/README.md`). Sem ele (`None`, o
    caso normal — `main.py` não passa este argumento), é lido directamente
    de `bridge/config.yaml`, tal como `audio_config` já é lido por `main.py`
    antes de chegar aqui.

    `score_config` é a secção `score` do `config.yaml` (ver `score_store.py`
    e `bridge/README.md`). Sem ela (`None`), nem o listener UDP nem a rota
    `/top10` arrancam, e "name" da webapp é ignorado — usado pelos testes
    existentes que não precisam de pontuação.
    """
    if input_mode is None:
        input_mode = load_input_mode()
    elif input_mode not in VALID_INPUT_MODES:
        LOGGER.warning("input_mode=%r inválido — a usar %s", input_mode, DEFAULT_INPUT_MODE)
        input_mode = DEFAULT_INPUT_MODE

    score_store: ScoreStore | None = None
    if score_config:
        data_dir = Path(score_config.get("data_dir", "bridge/data"))
        if not data_dir.is_absolute():
            data_dir = REPO_ROOT / data_dir
        badwords_path = Path(score_config.get("badwords_path", "bridge/badwords.txt"))
        if not badwords_path.is_absolute():
            badwords_path = REPO_ROOT / badwords_path
        score_store = ScoreStore(data_dir, badwords_path)

    bridge = WebBridge(
        manager,
        heartbeat_timeout=heartbeat_timeout,
        input_mode=input_mode,
        score_store=score_store,
    )
    app = web.Application()

    if score_store is not None:
        app["score_store"] = score_store
        app.router.add_get("/top10", top10_handler)
        score_host = score_config.get("host", "127.0.0.1")
        score_port = int(score_config.get("port", 9110))

        async def _start_score_listener(_app: web.Application) -> None:
            _app["score_transport"] = await start_score_listener(score_store, score_host, score_port)

        async def _stop_score_listener(_app: web.Application) -> None:
            transport = _app.get("score_transport")
            if transport is not None:
                transport.close()
            score_store.close()

        app.on_startup.append(_start_score_listener)
        app.on_cleanup.append(_stop_score_listener)

    if audio_config:
        assets_path = Path(audio_config["assets_path"]).resolve()
        resources_value = audio_config.get("resources_path")
        source_paths = [assets_path]
        if resources_value:
            source_paths.append(Path(resources_value).resolve())
        cache_dir = Path(audio_config.get("cache_dir", "bridge/audio_cache"))
        if not cache_dir.is_absolute():
            # Relativo à raiz do repositório, não ao cwd de quem arrancou o
            # processo — para dar sempre o mesmo sítio, corrido de onde for.
            cache_dir = REPO_ROOT / cache_dir
        cache_dir = cache_dir.resolve()
        app["audio_source_paths"] = tuple(source_paths)
        app["audio_cache_dir"] = cache_dir
        app["audio_manifest"] = build_audio_manifest(REPO_ROOT)
        app.router.add_get("/audio-manifest.json", audio_manifest_handler)
        app.router.add_get("/audio/{resource:.+}", audio_handler)

        async def dispatch_audio(player: int, message: dict) -> bool:
            """Encaminha uma mensagem de áudio para a sessão WebSocket do jogador.
            Sem sessão ligada não é erro — só descarta (ver `audio_router.py`)."""
            slots = manager._slots
            if player < 0 or player >= len(slots):
                return False
            source_id = slots[player]
            if not source_id:
                return False
            ws = bridge._sockets.get(source_id)
            if ws is None or ws.closed:
                return False
            try:
                await ws.send_json(message)
                return True
            except ConnectionResetError:
                return False

        async def handle_match_ended(player: int) -> None:
            """Fim de partida detectado no áudio (ver AudioRouter) — liberta o
            lugar (repõe o quadrante, ver `SlotManager._release_active`) e
            avisa a sessão pela WebSocket via `route()`."""
            await bridge.route(manager.release_player(player))

        ending_resources = _tv_show_ending_resources(REPO_ROOT)
        audio_router = AudioRouter(
            ports=list(audio_config.get("ports", [9001, 9002, 9003, 9004])),
            dispatch=dispatch_audio,
            mode=audio_config.get("mode", "devices"),
            pa_host=audio_config.get("pa_host", "127.0.0.1"),
            pa_ports=audio_config.get("pa_ports"),
            pa_timeout=float(audio_config.get("pa_timeout_seconds", 0.4)),
            ending_resources=ending_resources,
            on_match_ended=handle_match_ended if ending_resources else None,
        )
        app["audio_router"] = audio_router
        app.on_startup.append(lambda _app: audio_router.start())
        app.on_cleanup.append(lambda _app: audio_router.stop())

    app.router.add_get("/ws", bridge.handle_websocket)
    app.router.add_get("/qr.png", qr_handler)
    # Catch-all por último: rotas específicas têm de ganhar todas as anteriores.
    app.router.add_get("/{tail:.*}", webapp_handler)
    return app, bridge.route
