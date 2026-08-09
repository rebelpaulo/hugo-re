#!/usr/bin/env bash
# Arranca UMA instância do audio-server na porta 9001, a sair pela saída de
# áudio default do Mac (sem sinks virtuais, sem BlackHole — decisão de
# produto). Passa a pasta de assets (BigFile) por $HUGO_ASSETS ou 1º argumento.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_PY="$REPO_ROOT/.venv/bin/python3"

ASSETS="${1:-${HUGO_ASSETS:-}}"

if [ -z "$ASSETS" ]; then
  echo "ERRO: falta a pasta de assets (a 'BigFile' da gold version)." >&2
  echo "Usa: scripts/macos/run-audio.sh /caminho/para/BigFile" >&2
  echo "ou:  export HUGO_ASSETS=/caminho/para/BigFile && scripts/macos/run-audio.sh" >&2
  exit 1
fi

if [ ! -d "$ASSETS" ]; then
  echo "ERRO: a pasta de assets indicada não existe: $ASSETS" >&2
  echo "Confirma o caminho da BigFile (ainda pode não ter sido descarregada)." >&2
  exit 1
fi

if [ ! -x "$VENV_PY" ]; then
  echo "ERRO: não encontrei o .venv em $REPO_ROOT/.venv." >&2
  echo "Corre primeiro: scripts/macos/setup.sh" >&2
  exit 1
fi

echo "== run-audio.sh: audio-server na porta 9001, saída default do Mac =="
echo "   assets:    $ASSETS"
echo "   resources: $REPO_ROOT/game/resources"

exec "$VENV_PY" "$REPO_ROOT/audio-server/audio_server.py" \
  --host 0.0.0.0 \
  --ports 9001 \
  --assets "$ASSETS" \
  --resources "$REPO_ROOT/game/resources"
