#!/bin/bash
# Arranca o FreeSWITCH apontado à nossa configuração (bridge/freeswitch/),
# com a mesma disciplina do run-event.sh: espera confirmada antes de dizer
# que está pronto, limpeza garantida à saída (Ctrl-C ou erro), e o padrão
# `[f]reeswitch` nos `pkill` para nunca apanhar o próprio shell.
#
# Só traz o FreeSWITCH — não arranca o bridge. Ver bridge/README.md (secção
# SIP) para pôr `input_mode: sip` em bridge/config.yaml e, à parte, correr
# `.venv/bin/python bridge/main.py` (tal como run-audio.sh e run-game.sh são
# dois processos separados; combiná-los como o run-event.sh faz para
# áudio+jogo é uma extensão natural mas não pedida aqui).
#
# Uso:
#   ./scripts/macos/run-sip.sh
#
# Sai com Ctrl-C. Nesse e em qualquer outro caso de saída, o FreeSWITCH é
# desligado — nunca fica um processo pendurado a segurar a porta 5060 para
# o arranque seguinte.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
FS_DIR="$REPO_DIR/bridge/freeswitch"

FS_PREFIX="$(brew --prefix freeswitch 2>/dev/null || true)"
FREESWITCH_BIN="${FS_PREFIX:+$FS_PREFIX/bin/freeswitch}"
FS_CLI_BIN="${FS_PREFIX:+$FS_PREFIX/bin/fs_cli}"
[[ -x "$FREESWITCH_BIN" ]] || FREESWITCH_BIN="/opt/homebrew/bin/freeswitch"
[[ -x "$FS_CLI_BIN" ]] || FS_CLI_BIN="/opt/homebrew/bin/fs_cli"

if [[ ! -x "$FREESWITCH_BIN" ]]; then
  echo "[FALHA] não encontrei o binário do freeswitch ($FREESWITCH_BIN)." >&2
  echo "        Confirma 'brew install freeswitch'." >&2
  exit 1
fi

FS_LOG_DIR="/tmp/fslog"
FS_DB_DIR="/tmp/fsdb"

# ATENÇÃO ao padrão: `pgrep -f freeswitch` também apanha qualquer shell cuja
# linha de comando contenha esse texto — incluindo este próprio script. A
# classe de caracteres `[f]` faz o padrão não corresponder a si mesmo (ver
# run-event.sh, mesma disciplina).
PADRAO_FS='[f]reeswitch'
fs_vivo() { pgrep -f "$PADRAO_FS" >/dev/null 2>&1; }

FS_PID=""

parar_freeswitch() {
  echo ""
  echo "== a desligar o FreeSWITCH =="
  if fs_vivo; then
    "$FS_CLI_BIN" -x "shutdown" >/dev/null 2>&1 || true
    # O shutdown "porta-se bem" mas demora — dá-lhe tempo antes de forçar.
    for _ in $(seq 1 20); do
      fs_vivo || break
      sleep 0.5
    done
  fi
  if fs_vivo; then
    echo "   não desligou a tempo — a forçar (pkill -9)"
    pkill -9 -f "$PADRAO_FS" 2>/dev/null || true
  fi
  return 0
}
trap parar_freeswitch EXIT INT TERM

# Um FreeSWITCH esquecido de uma sessão anterior segura a porta 5060 e o
# arranque falha.
if fs_vivo; then
  echo "== havia um FreeSWITCH de uma sessão anterior; a fechá-lo =="
  pkill -9 -f "$PADRAO_FS" 2>/dev/null || true
  sleep 1
fi

echo "== 1/2: a construir bridge/freeswitch/conf/ =="
"$FS_DIR/build-conf.sh"

echo "== 2/2: a arrancar o FreeSWITCH =="
mkdir -p "$FS_LOG_DIR" "$FS_DB_DIR"
"$FREESWITCH_BIN" -nf -nonat -conf "$FS_DIR/conf" -log "$FS_LOG_DIR" -db "$FS_DB_DIR" &
FS_PID=$!

# Espera confirmada a sério: pergunta ao ESL, não adivinha por tempo fixo.
pronto=0
for _ in $(seq 1 40); do
  if ! kill -0 "$FS_PID" 2>/dev/null; then
    echo "[FALHA] o FreeSWITCH morreu durante o arranque — ver $FS_LOG_DIR/freeswitch.log" >&2
    exit 1
  fi
  if "$FS_CLI_BIN" -x "status" 2>/dev/null | grep -q "FreeSWITCH.*ready"; then
    pronto=1
    break
  fi
  sleep 0.5
done

if [[ "$pronto" -ne 1 ]]; then
  echo "[FALHA] o FreeSWITCH não respondeu 'ready' a tempo — ver $FS_LOG_DIR/freeswitch.log" >&2
  exit 1
fi

echo ""
echo "== FreeSWITCH pronto =="
"$FS_CLI_BIN" -x "sofia status" 2>/dev/null || true
echo ""
echo "   Perfil da LAN: internal (contexto hugo-lan) — ver bridge/freeswitch/README.md"
echo "   Agora, à parte: input_mode: sip em bridge/config.yaml, e"
echo "   .venv/bin/python bridge/main.py"
echo ""
echo "   Ctrl-C para desligar o FreeSWITCH."

# Fica em primeiro plano à espera do processo do FreeSWITCH; Ctrl-C aciona
# a trap acima.
wait "$FS_PID"
