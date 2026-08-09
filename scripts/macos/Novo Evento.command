#!/usr/bin/env bash
# Novo Evento.command — duplo-clique para começar um evento com o top 10 a zeros.
#
# Usa-se este em vez do Hugo.command uma vez, quando o evento começa a sério.
# Depois disso é sempre o Hugo.command: se o computador tiver de ser
# reiniciado a meio da noite, o top 10 do evento tem de continuar lá.
#
# Como funciona, e porque não mexe em código: o bridge já decide bem sozinho
# (ver bridge/score_store.py) — no arranque procura a base de sessão mais
# recente e, se ela tiver menos de 24h, reutiliza-a. É isso que salva os
# recordes num restart a meio do evento. Aqui só se arruma a sessão anterior
# para uma pasta de arquivo; sem sessão recente para encontrar, o bridge cria
# uma nova por si. Nenhum caminho novo no código, e nada que possa correr por
# engano num reinício.
#
# As bases antigas nunca são apagadas, só mudadas de sítio: ficam em
# bridge/data/arquivo/ como registo dos eventos anteriores.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DATA_DIR="$REPO_DIR/bridge/data"
ARQUIVO="$DATA_DIR/arquivo"

echo "============================================================"
echo " HUGO — novo evento (top 10 a zeros)"
echo "============================================================"
echo ""

# Mexer nos ficheiros com o bridge a correr dava uma base meio arrumada e um
# top 10 imprevisível. Melhor recusar e dizer o que fazer.
if pgrep -f "[b]ridge/main\.py" >/dev/null 2>&1; then
  echo "[FALHA] O bridge está a correr."
  echo ""
  echo "Fecha primeiro o Hugo (a janela do supervisor, Ctrl-C) e volta a abrir"
  echo "este ficheiro. Não mexo na base de dados com o jogo a andar."
  echo ""
  read -r -p "Carrega Enter para fechar."
  exit 1
fi

shopt -s nullglob
sessoes=("$DATA_DIR"/scores-*.db)
shopt -u nullglob

if [[ ${#sessoes[@]} -eq 0 ]]; then
  echo "Não havia nenhuma sessão anterior — o top 10 já estava vazio."
else
  mkdir -p "$ARQUIVO"
  for db in "${sessoes[@]}"; do
    n="$("$REPO_DIR/.venv/bin/python" - "$db" <<'PY' 2>/dev/null || echo "?"
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
print(con.execute("SELECT count(*) FROM scores").fetchone()[0])
PY
)"
    mv "$db" "$ARQUIVO/"
    echo "  arquivada $(basename "$db") — $n pontuações"
  done
  echo ""
  echo "Guardadas em: bridge/data/arquivo/  (nada foi apagado)"
fi

echo ""
echo "A arrancar o Hugo com o top 10 a zeros..."
echo ""
exec "$SCRIPT_DIR/Hugo.command"
