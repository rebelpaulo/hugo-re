#!/usr/bin/env bash
# Cria (ou verifica, se já existir) o .venv arm64 na raiz do repo e instala as
# dependências do jogo e do audio-server. Idempotente: corre outra vez à
# vontade, não rebenta se o .venv já lá estiver.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_DIR="$REPO_ROOT/.venv"
PYTHON_BIN="/opt/homebrew/bin/python3.13"

echo "== setup.sh: hugo-re (macOS arm64) =="

if [ ! -x "$PYTHON_BIN" ]; then
  echo "ERRO: não encontrei $PYTHON_BIN." >&2
  echo "Este projeto exige o Python arm64 do Homebrew (python3.13)." >&2
  echo "NUNCA uses /usr/local/bin/python3 — é um build x86_64 que rebenta com posix_spawnp nesta máquina." >&2
  echo "Corrige com: brew install python@3.13" >&2
  exit 1
fi

ARCH="$("$PYTHON_BIN" -c 'import platform; print(platform.machine())')"
if [ "$ARCH" != "arm64" ]; then
  echo "ERRO: $PYTHON_BIN reporta arquitetura '$ARCH', esperava 'arm64'." >&2
  exit 1
fi

if [ -d "$VENV_DIR" ]; then
  echo "-- .venv já existe em $VENV_DIR, a verificar em vez de recriar --"
  VENV_ARCH="$("$VENV_DIR/bin/python3" -c 'import platform; print(platform.machine())' 2>/dev/null || echo "?")"
  if [ "$VENV_ARCH" != "arm64" ]; then
    echo "AVISO: o .venv existente reporta arquitetura '$VENV_ARCH' (esperava arm64)." >&2
    echo "Está provavelmente contaminado por um python x86_64. Apaga '$VENV_DIR' à mão e corre este script outra vez." >&2
    exit 1
  fi
  echo "   .venv existente é arm64, ok."
else
  echo "-- a criar .venv com $PYTHON_BIN --"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

echo "-- a atualizar pip --"
"$VENV_DIR/bin/python3" -m pip install --upgrade pip -q

echo "-- a instalar game/requirements.txt --"
"$VENV_DIR/bin/pip" install -q -r "$REPO_ROOT/game/requirements.txt"

echo "-- a instalar audio-server/requirements.txt --"
"$VENV_DIR/bin/pip" install -q -r "$REPO_ROOT/audio-server/requirements.txt"

echo "-- feito. Corre scripts/macos/check.sh para confirmar que está tudo ok. --"
