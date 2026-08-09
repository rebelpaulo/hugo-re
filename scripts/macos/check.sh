#!/usr/bin/env bash
# Verificação corrível do ambiente: python arm64, os 7 imports, ffmpeg no
# PATH, e conteúdo sentinela da BigFile. Sai != 0 se faltar algo essencial.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_PY="$REPO_ROOT/.venv/bin/python3"

FAIL=0
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/hugo-check.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "== check.sh: hugo-re (macOS arm64) =="
echo

# -- 1. venv + arquitetura --------------------------------------------------
if [ ! -x "$VENV_PY" ]; then
  echo "[FALHA] .venv não encontrado em $REPO_ROOT/.venv (corre scripts/macos/setup.sh)"
  FAIL=1
else
  ARCH="$("$VENV_PY" -c 'import platform; print(platform.machine())' 2>/dev/null || echo "?")"
  if [ "$ARCH" = "arm64" ]; then
    echo "[ok]    .venv é arm64 ($("$VENV_PY" --version 2>&1))"
  else
    echo "[FALHA] .venv reporta arquitetura '$ARCH', esperava 'arm64'"
    FAIL=1
  fi
fi
echo

# -- 2. os 7 imports (um processo por módulo, para isolar falhas) -----------
echo "-- imports --"
MODULES=(pygame moderngl pyvidplayer2 sounddevice soundfile numpy scipy)
if [ -x "$VENV_PY" ]; then
  for mod in "${MODULES[@]}"; do
    if "$VENV_PY" -c "
import $mod
v = getattr($mod, '__version__', None) or getattr(getattr($mod, 'version', None), 'ver', None) or '?'
print(v)
" >"$TMP_DIR/$mod.out" 2>"$TMP_DIR/$mod.err"; then
      VERSION="$(tail -1 "$TMP_DIR/$mod.out")"
      echo "[ok]    $mod $VERSION"
      if [ -s "$TMP_DIR/$mod.err" ]; then
        echo "[aviso] $mod escreveu no stderr:"
        sed 's/^/          /' "$TMP_DIR/$mod.err"
      fi
    else
      echo "[FALHA] $mod não importou:"
      tail -5 "$TMP_DIR/$mod.err" | sed 's/^/          /'
      FAIL=1
    fi
  done
else
  echo "[FALHA] a saltar imports, sem .venv"
  FAIL=1
fi
echo

# -- 3. ffmpeg no PATH -------------------------------------------------------
if command -v ffmpeg >/dev/null 2>&1; then
  if ffmpeg -version >"$TMP_DIR/ffmpeg.out" 2>"$TMP_DIR/ffmpeg.err"; then
    FFMPEG_VERSION="$(head -1 "$TMP_DIR/ffmpeg.out")"
    echo "[ok]    ffmpeg no PATH ($(command -v ffmpeg), $FFMPEG_VERSION)"
    if [ -s "$TMP_DIR/ffmpeg.err" ]; then
      echo "[aviso] ffmpeg escreveu no stderr:"
      sed 's/^/          /' "$TMP_DIR/ffmpeg.err"
    fi
  else
    echo "[FALHA] ffmpeg existe no PATH, mas não arrancou:"
    tail -5 "$TMP_DIR/ffmpeg.err" | sed 's/^/          /'
    FAIL=1
  fi
else
  echo "[FALHA] ffmpeg não está no PATH"
  FAIL=1
fi
echo

# -- 4. pasta de assets (BigFile) -------------------------------------------
ASSETS="${1:-${HUGO_ASSETS:-}}"
if [ -z "$ASSETS" ]; then
  echo "[FALHA] HUGO_ASSETS não está definida e não passaste caminho como argumento."
  echo "         Define com:"
  echo "         export HUGO_ASSETS=/caminho/para/BigFile"
  FAIL=1
elif [ ! -d "$ASSETS" ]; then
  echo "[FALHA] pasta de assets não encontrada em: $ASSETS"
  FAIL=1
else
  MISSING_SENTINELS=""
  for sentinel in BoltData ForestData IceCavernData MenuData; do
    if [ ! -d "$ASSETS/$sentinel" ]; then
      MISSING_SENTINELS="$MISSING_SENTINELS $sentinel/"
    fi
  done
  if [ -n "$MISSING_SENTINELS" ]; then
    echo "[FALHA] a pasta não parece ser a BigFile; faltam:$MISSING_SENTINELS"
    echo "         caminho verificado: $ASSETS"
    FAIL=1
  else
    ASSETS="$(cd "$ASSETS" && pwd -P)"
    echo "[ok]    BigFile validada: $ASSETS"
  fi
fi
echo

if [ "$FAIL" -ne 0 ]; then
  echo "== check.sh: FALHOU (algo essencial em falta, ver [FALHA] acima) =="
  exit 1
fi

echo "== check.sh: OK (o essencial está pronto) =="
