#!/usr/bin/env bash
# Verificação corrível do ambiente: python arm64, os 7 imports, ffmpeg no
# PATH, e presença da pasta de assets. Sai != 0 se faltar algo essencial
# (python/venv, qualquer um dos 7 imports, ffmpeg). A pasta de assets é
# esperada estar em falta antes do dia do evento — reporta-se como aviso,
# não faz falhar o script.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_PY="$REPO_ROOT/.venv/bin/python3"

FAIL=0

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
MODULES="pygame moderngl pyvidplayer2 sounddevice soundfile numpy scipy"
if [ -x "$VENV_PY" ]; then
  for mod in $MODULES; do
    if OUT="$("$VENV_PY" -c "
import $mod
v = getattr($mod, '__version__', None) or getattr(getattr($mod, 'version', None), 'ver', None) or '?'
print(v)
" 2>&1)"; then
      VERSION="$(echo "$OUT" | tail -1)"
      echo "[ok]    $mod $VERSION"
    else
      echo "[FALHA] $mod não importou:"
      echo "$OUT" | tail -5 | sed 's/^/          /'
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
  echo "[ok]    ffmpeg no PATH ($(command -v ffmpeg), $(ffmpeg -version 2>&1 | head -1))"
else
  echo "[FALHA] ffmpeg não está no PATH"
  FAIL=1
fi
echo

# -- 4. pasta de assets (BigFile) -- aviso, não falha ------------------------
ASSETS="${1:-${HUGO_ASSETS:-}}"
if [ -z "$ASSETS" ]; then
  echo "[aviso] HUGO_ASSETS não está definida e não passaste caminho como argumento."
  echo "         Isto é esperado até a BigFile estar descarregada. Define com:"
  echo "         export HUGO_ASSETS=/caminho/para/BigFile"
elif [ -d "$ASSETS" ]; then
  echo "[ok]    pasta de assets encontrada: $ASSETS"
else
  echo "[aviso] pasta de assets NÃO encontrada em: $ASSETS"
  echo "         Isto é esperado até a BigFile estar descarregada."
fi
echo

if [ "$FAIL" -ne 0 ]; then
  echo "== check.sh: FALHOU (algo essencial em falta, ver [FALHA] acima) =="
  exit 1
fi

echo "== check.sh: OK (o essencial está pronto) =="
