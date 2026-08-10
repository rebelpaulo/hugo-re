#!/usr/bin/env bash
# doctor.sh — passagem única pelo estado de tudo o que interessa para o
# evento: venv/Python, imports, ausência do opencv (ver Problema 1 do
# endurecimento pré-evento), ffmpeg, pasta de assets, os 12 clips PT, os
# sprites do scoreboard, portas relevantes, se o bridge responde, se o jogo
# está vivo, e o IP do lobby. [ok]/[FALHA] em cada linha; sai != 0 se faltar
# algo essencial.
#
# É o que se corre às 20h antes de abrir as portas — depois de o
# supervisor.sh já ter arrancado o jogo e o bridge. Correr antes disso é
# normal (mostra [FALHA] em "jogo vivo"/"bridge responde", como seria de
# esperar) mas não é o caso de uso principal.
#
# Uso:
#   ./scripts/macos/doctor.sh [caminho/para/BigFile]
#   HUGO_ASSETS=/caminho/para/BigFile ./scripts/macos/doctor.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_PY="$REPO_ROOT/.venv/bin/python3"

FAIL=0
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/hugo-doctor.XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT

ok()    { echo "[ok]    $*"; }
falha() { echo "[FALHA] $*"; FAIL=1; }
aviso() { echo "[aviso] $*"; }
info()  { echo "[info]  $*"; }

echo "== doctor.sh: hugo-re (macOS arm64), $(date '+%Y-%m-%d %H:%M:%S') =="
echo

# -- 1. venv + arquitetura ---------------------------------------------------
echo "-- venv --"
if [ ! -x "$VENV_PY" ]; then
  falha ".venv não encontrado em $REPO_ROOT/.venv (corre scripts/macos/setup.sh)"
else
  ARCH="$("$VENV_PY" -c 'import platform; print(platform.machine())' 2>/dev/null || echo "?")"
  VERSION="$("$VENV_PY" -c 'import sys; print(".".join(map(str, sys.version_info[:2])))' 2>/dev/null || echo "?")"
  if [ "$ARCH" = "arm64" ] && [ "$VERSION" = "3.13" ]; then
    ok ".venv é arm64, Python 3.13 ($("$VENV_PY" --version 2>&1))"
  else
    falha ".venv reporta arquitetura '$ARCH' / Python '$VERSION' (esperava arm64 / 3.13)"
  fi
fi
echo

# -- 2. imports ---------------------------------------------------------------
echo "-- imports --"
# aiohttp e qrcode são do bridge (bridge/main.py, bridge/qr.py). Faltavam aqui
# e no requirements-lock.txt, e por isso uma .venv nova passava na verificação
# e só rebentava quando alguém tentasse arrancar o bridge.
MODULES=(pygame moderngl pyvidplayer2 sounddevice soundfile numpy scipy yaml aiohttp qrcode)
if [ -x "$VENV_PY" ]; then
  for mod in "${MODULES[@]}"; do
    if "$VENV_PY" -c "import $mod" >"$TMP_DIR/$mod.out" 2>"$TMP_DIR/$mod.err"; then
      ok "$mod importa"
    else
      falha "$mod não importou:"
      tail -3 "$TMP_DIR/$mod.err" | sed 's/^/          /'
    fi
  done
  # Guarda de regressão do Problema 1 (endurecimento pré-evento): o cv2
  # (opencv) NUNCA deve estar instalado neste .venv — traz o seu próprio
  # libSDL2 e colide com o do pygame ("mysterious crashes", ver
  # requirements-lock.txt). Sem cv2, o pyvidplayer2 usa o FFMPEGReader.
  if "$VENV_PY" -c "import cv2" >/dev/null 2>&1; then
    falha "cv2 (opencv) está instalado — isto reintroduz o libSDL2 duplicado."
    echo "          remove com: $VENV_PY -m pip uninstall -y opencv-python opencv-python-headless"
  else
    ok "cv2 (opencv) ausente, como deve ser — sem risco de libSDL2 duplicado"
  fi
else
  falha "a saltar imports, sem .venv"
fi
echo

# -- 3. ffmpeg ------------------------------------------------------------
echo "-- ffmpeg --"
if command -v ffmpeg >/dev/null 2>&1 && ffmpeg -version >"$TMP_DIR/ffmpeg.out" 2>&1; then
  ok "ffmpeg no PATH ($(command -v ffmpeg), $(head -1 "$TMP_DIR/ffmpeg.out"))"
else
  falha "ffmpeg não está no PATH ou não arrancou"
fi
echo

# -- 4. pasta de assets (BigFile) -------------------------------------------
echo "-- assets (BigFile) --"
ASSETS="${1:-${HUGO_ASSETS:-}}"
if [ -z "$ASSETS" ]; then
  falha "HUGO_ASSETS não definida e sem argumento. Define: export HUGO_ASSETS=/caminho/para/BigFile"
elif "$SCRIPT_DIR/check.sh" --validate-assets-only "$ASSETS" >"$TMP_DIR/assets.out" 2>&1; then
  cat "$TMP_DIR/assets.out"
  ASSETS="$(cd "$ASSETS" && pwd -P)"
else
  cat "$TMP_DIR/assets.out"
  falha "BigFile inválida em: $ASSETS"
  ASSETS=""
fi
echo

# -- 5. os 12 clips PT (6 vídeo + 6 áudio) -----------------------------------
echo "-- os 12 clips PT --"
CLIPS=(attract_demo have_luck hello_hello press_5 scylla_cave you_lost)
VIDEO_DIR="$REPO_ROOT/game/resources/videos/pt"
AUDIO_DIR="$REPO_ROOT/game/resources/audio_for_videos/pt"
for clip in "${CLIPS[@]}"; do
  v="$VIDEO_DIR/$clip.avi"
  a="$AUDIO_DIR/$clip.wav"
  if [ -s "$v" ]; then
    ok "vídeo pt/$clip.avi ($(du -h "$v" | cut -f1))"
  else
    falha "vídeo pt/$clip.avi em falta ou vazio ($v)"
  fi
  if [ -s "$a" ]; then
    ok "áudio pt/$clip.wav ($(du -h "$a" | cut -f1))"
  else
    falha "áudio pt/$clip.wav em falta ou vazio ($a)"
  fi
done
echo

# -- 6. sprites do scoreboard -------------------------------------------------
echo "-- sprites do scoreboard --"
SPRITE_MIN_BYTES=10000
for sprite in sprite1.png sprite2.png; do
  f="$REPO_ROOT/game/resources/scores/$sprite"
  if [ -f "$f" ]; then
    SIZE="$(wc -c <"$f" | tr -d ' ')"
    if [ "$SIZE" -ge "$SPRITE_MIN_BYTES" ]; then
      ok "scores/$sprite presente ($(du -h "$f" | cut -f1))"
    else
      falha "scores/$sprite existe mas tem só ${SIZE} bytes — parece um placeholder, não o sprite real"
    fi
  else
    falha "scores/$sprite em falta ($f)"
  fi
done
if [ -n "$ASSETS" ]; then
  if [ -f "$ASSETS/RopeOutroData/GFX/SCORE.cgf" ]; then
    ok "fonte do scoreboard RopeOutroData/GFX/SCORE.cgf presente na BigFile"
  else
    falha "fonte do scoreboard RopeOutroData/GFX/SCORE.cgf em falta na BigFile"
  fi
else
  aviso "sem BigFile válida, a saltar a verificação de RopeOutroData/GFX/SCORE.cgf"
fi
echo

# -- 7. portas relevantes (informativo — o dono varia consoante o modo de
#       áudio do bridge; ver a nota de arquitetura em supervisor.sh) --------
echo "-- portas --"
verificar_porta() {
  local proto="$1" porta="$2" esperado="$3"
  local linha
  linha="$(lsof -nP -i"${proto}:${porta}" 2>/dev/null | awk 'NR==2 {print $1, $2}')" || true
  if [ -n "$linha" ]; then
    info "$proto $porta ocupada por $linha (esperado: $esperado)"
  else
    info "$proto $porta livre"
  fi
}
verificar_porta TCP 8080 "bridge (web/lobby)"
verificar_porta UDP 9100 "jogo (entrada UDP do bridge)"
for p in 9001 9002 9003 9004; do
  verificar_porta UDP "$p" "bridge (audio_router, modo devices) OU audio-server clássico (modo pa) — nunca os dois ao mesmo tempo"
done
echo

# -- 8. bridge responde -------------------------------------------------------
echo "-- bridge --"
if command -v curl >/dev/null 2>&1; then
  HTTP_CODE="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:8080/ 2>/dev/null)" || true
  HTTP_CODE="${HTTP_CODE:-000}"
  if [ "$HTTP_CODE" = "200" ]; then
    ok "bridge responde em http://127.0.0.1:8080/ (HTTP $HTTP_CODE)"
  else
    falha "bridge não respondeu em http://127.0.0.1:8080/ (HTTP $HTTP_CODE) — está a correr?"
  fi
else
  falha "sem curl no PATH; não consigo testar o bridge"
fi
echo

# -- 9. jogo vivo --------------------------------------------------------------
echo "-- jogo --"
# `[g]ame\.py` não corresponde a si mesmo — mesma armadilha do pkill -f
# documentada em run-event.sh e supervisor.sh.
GAME_PID="$(pgrep -f '[g]ame\.py' | head -1 || true)"
if [ -n "$GAME_PID" ] && kill -0 "$GAME_PID" 2>/dev/null; then
  ok "jogo vivo (PID $GAME_PID)"
else
  falha "sem processo do jogo (game.py) a correr"
fi
echo

# -- 10. IP do lobby ------------------------------------------------------------
echo "-- IP do lobby --"
if [ -x "$VENV_PY" ]; then
  LOBBY_IP="$("$VENV_PY" - <<'PY' 2>/dev/null
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(("8.8.8.8", 80))
    print(s.getsockname()[0])
except OSError:
    print("127.0.0.1")
finally:
    s.close()
PY
)"
  info "http://$LOBBY_IP:8080/ (mesmo truque do socket que o bridge usa em bridge/main.py:lan_ip)"
else
  aviso "sem .venv, não consigo calcular o IP do lobby"
fi
echo

if [ "$FAIL" -ne 0 ]; then
  echo "== doctor.sh: FALHOU (algo essencial em falta, ver [FALHA] acima) =="
  exit 1
fi

echo "== doctor.sh: OK (tudo o que interessa está pronto) =="
