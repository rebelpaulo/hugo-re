#!/usr/bin/env bash
# Arranca o jogo com o cwd correto (game/) e a pasta de dados (BigFile) por
# $HUGO_ASSETS ou 1º argumento.
#
# NOTA sobre o cwd: game/resource.py e a maior parte do jogo carregam
# recursos com caminhos relativos tipo "resources/images/...", o que só
# resolve com cwd = game/. É esse o cwd usado aqui.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_PY="$REPO_ROOT/.venv/bin/python3"
GAME_DIR="$REPO_ROOT/game"

ASSETS="${1:-${HUGO_ASSETS:-}}"

if [ -z "$ASSETS" ]; then
  echo "ERRO: falta a pasta de dados (a 'BigFile' da gold version)." >&2
  echo "Usa: scripts/macos/run-game.sh /caminho/para/BigFile" >&2
  echo "ou:  export HUGO_ASSETS=/caminho/para/BigFile && scripts/macos/run-game.sh" >&2
  exit 1
fi

if ! "$SCRIPT_DIR/check.sh" --validate-assets-only "$ASSETS"; then
  echo "ERRO: indica a BigFile completa, com os diretórios sentinela acima." >&2
  exit 1
fi

# O jogo muda de cwd abaixo; fixa primeiro qualquer caminho relativo recebido.
ASSETS="$(cd "$ASSETS" && pwd -P)"

if [ ! -x "$VENV_PY" ]; then
  echo "ERRO: não encontrei o .venv em $REPO_ROOT/.venv." >&2
  echo "Corre primeiro: scripts/macos/setup.sh" >&2
  exit 1
fi

echo "== run-game.sh: a arrancar o jogo =="
echo "   cwd:   $GAME_DIR"
echo "   dados: $ASSETS"

cd "$GAME_DIR"
exec "$VENV_PY" game.py "$ASSETS"
