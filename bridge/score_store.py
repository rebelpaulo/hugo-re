"""Pontuação do dia: liga a pontuação que o jogo manda por UDP no fim da
partida (`game/score_report.py`) ao nome que o jogador escreve na webapp
depois de `{"type":"finished"}`, e guarda o top 10 numa base SQLite.

"O dia" não é a data do calendário — é uma janela de 24 horas a contar do
arranque da SESSÃO (correção do cliente sobre o ticket original). O evento
começa ao fim da tarde e atravessa a meia-noite; com um ficheiro por data de
calendário, o top 10 esvaziava-se a meio da festa, exactamente no pior
momento. Em vez disso:

  1. No arranque, procura-se em `data_dir` a base de sessão mais recente,
     pelo `session_start` guardado dentro dela (tabela `meta` — nunca o
     mtime do ficheiro, que um restart do bridge muda sem querer).
  2. Se essa sessão começou há menos de 24 horas, é reaberta e reutilizada
     tal como está — cobre o caso crítico de um restart a meio do evento
     (o `supervisor.sh` pode reiniciar o bridge; às 22h ninguém pode perder
     os recordes do dia).
  3. Caso contrário, cria-se uma base nova, com o timestamp de arranque no
     nome (`scores-YYYYMMDD-HHMM.db`).
  4. Bases antigas ficam no disco — pequenas, servem de arquivo dos eventos
     anteriores. Nunca apagadas por este módulo.

Duas peças:

  - `ScoreUdpListener`: escuta a porta nova (127.0.0.1:9110 por omissão —
    ver `bridge/config.yaml: score.port` e o cabeçalho de
    `game/score_report.py` sobre porque não é a 9102 sugerida inicialmente)
    por `{"player":N,"score":X}`. Fire-and-forget do lado do jogo; aqui só
    se guarda, nunca se responde.
  - `ScoreStore`: pontuação pendente por jogador (a corrida entre o UDP da
    pontuação e o `finished` do fim de partida detectado no áudio — ver
    `bridge/audio_router.py` — corre nos dois sentidos; por isso a
    pontuação fica "pendente" à espera de UM nome, nunca presa a uma ordem
    de chegada), o filtro de nome, e a base SQLite da sessão activa.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Callable

LOGGER = logging.getLogger("bridge.score_store")

DB_GLOB = "scores-*.db"
MAX_NAME_LEN = 8
# Quantos entram no quadro de honra. Ver `ScoreStore.top10` para o porquê de
# ser 5 apesar de tudo à volta se chamar "top10".
TOP_N = 5
FALLBACK_NAME = "???"
SESSION_WINDOW_SECONDS = 24 * 3600


def _load_badwords(path: Path) -> frozenset[str]:
    """Lê a lista de palavras a filtrar (uma por linha, ver
    `bridge/badwords.txt`). Ficheiro ausente = filtro vazio, nunca um erro
    de arranque — é conteúdo opcional, editável pela produção."""
    if not path.is_file():
        LOGGER.warning("Lista de palavras a filtrar não encontrada em %s — filtro desligado", path)
        return frozenset()
    words = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        words.add(line.upper())
    return frozenset(words)


def clean_name(raw: object, badwords: frozenset[str] = frozenset()) -> str:
    """Normaliza e valida um nome para o top10: maiúsculas, só A-Z/0-9/
    espaço, no máximo 8 caracteres (estilo arcade de recordes de sala de
    jogos, pedido no ticket). Nome vazio, sem nenhum carácter válido, ou que
    contenha (por substring, já em maiúsculas) uma palavra da lista de
    filtro vira "???" — decisão deliberada de nunca rejeitar a submissão em
    si: o jogador já está bloqueado depois disto (ver `bridge/README.md`),
    sem forma de tentar outra vez sem voltar à fila."""
    if not isinstance(raw, str):
        return FALLBACK_NAME
    upper = raw.strip().upper()
    cleaned_chars = [ch for ch in upper if ("A" <= ch <= "Z") or ("0" <= ch <= "9") or ch == " "]
    cleaned = " ".join("".join(cleaned_chars).split())  # colapsa espaços repetidos/pontas
    cleaned = cleaned[:MAX_NAME_LEN].strip()
    if not cleaned:
        return FALLBACK_NAME
    for word in badwords:
        if word and word in cleaned:
            return FALLBACK_NAME
    return cleaned


class ScoreStore:
    """Pontuação pendente por jogador + base SQLite da sessão activa."""

    def __init__(
        self,
        data_dir: Path | str,
        badwords_path: Path | str,
        *,
        now: Callable[[], float] = time.time,
        session_window_seconds: float = SESSION_WINDOW_SECONDS,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.badwords = _load_badwords(Path(badwords_path))
        self._now = now
        self._session_window = session_window_seconds
        self._pending: dict[int, int] = {}
        self.db_path = self._resolve_session_db()
        self._conn = self._open(self.db_path)

    # ------------------------------------------------------------------
    # Sessão de 24h (ver cabeçalho do módulo).
    # ------------------------------------------------------------------
    def _resolve_session_db(self) -> Path:
        latest = self._latest_session_db()
        if latest is not None:
            path, session_start = latest
            if self._now() - session_start < self._session_window:
                return path
        return self._new_session_db_path()

    def _latest_session_db(self) -> tuple[Path, float] | None:
        best: tuple[Path, float] | None = None
        for path in sorted(self.data_dir.glob(DB_GLOB)):
            session_start = self._read_session_start(path)
            if session_start is None:
                continue
            if best is None or session_start > best[1]:
                best = (path, session_start)
        return best

    @staticmethod
    def _read_session_start(path: Path) -> float | None:
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        except sqlite3.Error:
            return None
        try:
            row = conn.execute("SELECT session_start FROM meta LIMIT 1").fetchone()
        except sqlite3.Error:
            return None
        finally:
            conn.close()
        return float(row[0]) if row else None

    def _new_session_db_path(self) -> Path:
        stamp = datetime.datetime.fromtimestamp(self._now()).strftime("%Y%m%d-%H%M")
        path = self.data_dir / f"scores-{stamp}.db"
        suffix = 2
        while path.exists():  # dois arranques no mesmo minuto — nunca apaga uma base existente
            path = self.data_dir / f"scores-{stamp}-{suffix}.db"
            suffix += 1
        return path

    def _open(self, path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.execute("CREATE TABLE IF NOT EXISTS meta (session_start REAL NOT NULL)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS scores ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "player INTEGER NOT NULL,"
            "name TEXT NOT NULL,"
            "score INTEGER NOT NULL,"
            "ts REAL NOT NULL)"
        )
        if conn.execute("SELECT COUNT(*) FROM meta").fetchone()[0] == 0:
            # Base nova (nunca reabre uma reutilizada — essa já tem a linha
            # da sua própria sessão, ver `_resolve_session_db`): grava agora
            # o início desta sessão, para o próximo arranque decidir.
            conn.execute("INSERT INTO meta (session_start) VALUES (?)", (self._now(),))
        conn.commit()
        return conn

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Pontuação pendente (corrida UDP vs. finished — ver cabeçalho).
    # ------------------------------------------------------------------
    def set_pending_score(self, player: int, score: int) -> None:
        self._pending[player] = int(score)

    def pop_pending_score(self, player: int) -> int | None:
        return self._pending.pop(player, None)

    # ------------------------------------------------------------------
    # Nome + gravação.
    # ------------------------------------------------------------------
    def clean_name(self, raw: object) -> str:
        return clean_name(raw, self.badwords)

    def submit(self, player: int, raw_name: object, clock: Callable[[], float] | None = None) -> dict | None:
        """Junta o nome (limpo) à pontuação pendente daquele jogador e grava
        na base da sessão activa. Sem pontuação pendente (jogo sem o patch,
        ou o UDP nunca chegou), não escreve nada — devolve None, e quem
        chama mostra o top10 na mesma, sem entrada própria (degrada, não
        parte — ver ticket)."""
        score = self.pop_pending_score(player)
        if score is None:
            return None
        name = self.clean_name(raw_name)
        ts = (clock or self._now)()
        self._conn.execute(
            "INSERT INTO scores (player, name, score, ts) VALUES (?, ?, ?, ?)",
            (player, name, score, ts),
        )
        self._conn.commit()
        return {"name": name, "score": score}

    def top10(self) -> list[dict]:
        """Os melhores da sessão. São TOP_N = 5, não 10 (decisão do cliente:
        no ecrã do telemóvel, cinco linhas deixam espaço para os logótipos e
        lêem-se de relance). O nome do método, a rota `/top10` e o tipo de
        mensagem `top10` ficam como estão — são identificadores do protocolo,
        e trocá-los custaria mais do que vale."""
        rows = self._conn.execute(
            "SELECT name, score FROM scores ORDER BY score DESC, ts ASC LIMIT ?", (TOP_N,)
        ).fetchall()
        return [{"name": name, "score": score} for name, score in rows]


class ScoreUdpListener(asyncio.DatagramProtocol):
    """`{"player":0..3,"score":N}` vindo de `game/score_report.py` — nunca
    responde (o jogo não espera nada, ver o próprio módulo)."""

    def __init__(self, store: ScoreStore) -> None:
        self.store = store
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr) -> None:
        try:
            msg = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            LOGGER.debug("Pacote de pontuação ilegível de %s", addr)
            return
        if not isinstance(msg, dict):
            return
        player = msg.get("player")
        score = msg.get("score")
        if not isinstance(player, int) or isinstance(player, bool) or not 0 <= player <= 3:
            LOGGER.debug("Pontuação com 'player' inválido: %r", msg)
            return
        if not isinstance(score, int) or isinstance(score, bool) or score < 0:
            LOGGER.debug("Pontuação com 'score' inválido: %r", msg)
            return
        self.store.set_pending_score(player, score)

    def error_received(self, exc: Exception) -> None:
        LOGGER.warning("Erro UDP no listener de pontuação: %s", exc)


async def start_score_listener(
    store: ScoreStore, host: str, port: int
) -> asyncio.DatagramTransport:
    loop = asyncio.get_running_loop()
    try:
        transport, _protocol = await loop.create_datagram_endpoint(
            lambda: ScoreUdpListener(store), local_addr=(host, port)
        )
    except OSError as erro:
        raise RuntimeError(
            f"Não consegui escutar em {host}:{port} para a pontuação ({erro}).\n"
            f"  Confirma que não há outro bridge a correr (ver bridge/config.yaml: score.port)."
        ) from erro
    LOGGER.info("Listener de pontuação a escutar em %s:%d", host, port)
    return transport
