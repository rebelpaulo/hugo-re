"""Testes corríveis sem framework: .venv/bin/python bridge/test_score_store.py

Cobre ScoreStore isoladamente (sem rede): pontuação pendente, limpeza/filtro
de nomes, top10, e a janela de sessão de 24h (correção do cliente sobre o
ticket original — "o dia" é 24h a contar do arranque, não a data do
calendário) incluindo o restart a meio do evento e a viragem de sessão.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from score_store import ScoreStore, clean_name


def make_badwords_file(tmp_dir: Path) -> Path:
    path = tmp_dir / "badwords.txt"
    path.write_text("# comentário\nPUTA\nMERDA\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 1. clean_name: normalização, limite de 8, filtro por substring.
# ---------------------------------------------------------------------------

badwords = frozenset({"PUTA", "MERDA"})
assert clean_name("hugo", badwords) == "HUGO"
assert clean_name("  ana maria  ", badwords) == "ANA MARI"  # 8 caracteres, corta
assert clean_name("jo3-ão!!", badwords) == "JO3O"  # símbolos, hífen e acento ficam de fora
assert clean_name("", badwords) == "???"
assert clean_name("!!!", badwords) == "???"
assert clean_name(None, badwords) == "???"
assert clean_name(12345, badwords) == "???"
assert clean_name("puta", badwords) == "???"
assert clean_name("xputax", badwords) == "???"  # substring, não só palavra inteira
assert clean_name("MERDANO", badwords) == "???"  # contém "MERDA" como substring
assert clean_name("normal", badwords) == "NORMAL"
print("OK 1: clean_name normaliza, corta a 8, filtra por substring")


# ---------------------------------------------------------------------------
# 2. Pontuação pendente + submissão: junta nome à pontuação certa.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    store = ScoreStore(tmp_path / "data", make_badwords_file(tmp_path), now=lambda: 1_000_000.0)

    # Sem pontuação pendente: submit não escreve nada.
    assert store.submit(0, "HUGO") is None
    assert store.top10() == []

    store.set_pending_score(2, 4200)
    entry = store.submit(2, "hugo")
    assert entry == {"name": "HUGO", "score": 4200}, entry
    # "uma vez": a pontuação pendente já foi consumida.
    assert store.pop_pending_score(2) is None

    store.set_pending_score(0, 999)
    store.submit(0, "puta")  # filtrado
    assert store.top10() == [
        {"name": "HUGO", "score": 4200},
        {"name": "???", "score": 999},
    ], store.top10()
    print("OK 2: pontuação pendente junta-se ao nome certo, uma vez, e ??? filtra palavrões")


# ---------------------------------------------------------------------------
# 3. top10: ordena por pontuação desc., limita a 10.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    store = ScoreStore(tmp_path / "data", make_badwords_file(tmp_path), now=lambda: 2_000_000.0)
    for i in range(12):
        store.set_pending_score(i % 4, i * 100)
        store.submit(i % 4, f"P{i}")
    top = store.top10()
    assert len(top) == 10, len(top)
    assert [entry["score"] for entry in top] == sorted(
        (entry["score"] for entry in top), reverse=True
    ), top
    assert top[0]["score"] == 1100, top  # i=11 -> 1100, a maior
    print("OK 3: top10 ordenado por pontuação decrescente, limitado a 10")


# ---------------------------------------------------------------------------
# 4. Sessão de 24h — restart a meio do evento reutiliza a mesma base, sem
#    perder pontuações já gravadas (correção do cliente sobre o ticket).
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    data_dir = tmp_path / "data"
    badwords_path = make_badwords_file(tmp_path)
    t0 = 1_700_000_000.0

    store1 = ScoreStore(data_dir, badwords_path, now=lambda: t0)
    store1.set_pending_score(1, 555)
    store1.submit(1, "PRIMEIRO")
    db_path_1 = store1.db_path
    store1.close()

    # "Reinicia": nova instância sobre a mesma pasta, 1h depois (< 24h) —
    # simula o supervisor.sh a reiniciar o bridge a meio do evento.
    store2 = ScoreStore(data_dir, badwords_path, now=lambda: t0 + 3600)
    assert store2.db_path == db_path_1, (store2.db_path, db_path_1)
    assert store2.top10() == [{"name": "PRIMEIRO", "score": 555}], store2.top10()
    store2.set_pending_score(2, 700)
    store2.submit(2, "SEGUNDO")
    assert store2.top10() == [
        {"name": "SEGUNDO", "score": 700},
        {"name": "PRIMEIRO", "score": 555},
    ], store2.top10()
    store2.close()
    print("OK 4: restart a menos de 24h reutiliza a base e preserva o top10")


# ---------------------------------------------------------------------------
# 5. Sessão de 24h — mais de 24h depois, cria uma base nova e vazia; a
#    antiga fica no disco (arquivo), nunca apagada.
# ---------------------------------------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    data_dir = tmp_path / "data"
    badwords_path = make_badwords_file(tmp_path)
    t0 = 1_700_000_000.0

    store1 = ScoreStore(data_dir, badwords_path, now=lambda: t0)
    store1.set_pending_score(0, 111)
    store1.submit(0, "ONTEM")
    db_path_1 = store1.db_path
    store1.close()

    # 25h depois — fora da janela de 24h: sessão nova, top10 vazio.
    store2 = ScoreStore(data_dir, badwords_path, now=lambda: t0 + 25 * 3600)
    assert store2.db_path != db_path_1, "devia ter criado uma base nova"
    assert store2.top10() == [], store2.top10()
    assert db_path_1.is_file(), "a base antiga tem de ficar no disco, como arquivo"
    store2.close()
    print("OK 5: sessão com mais de 24h cria base nova e vazia; a antiga fica de arquivo")


print("Todos os cenários passaram.")
