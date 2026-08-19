#!/usr/bin/env bash
# supervisor.sh — vigia o jogo e o bridge; reinicia quem morrer. Para macOS,
# para se poder parar e arrancar à mão em palco (nada de launchd).
#
# Porque é que isto existe: sem isto, se o jogo ou o bridge morrerem a meio
# do evento, ficam mortos — ninguém no ecrã, ninguém a jogar, e a única forma
# de reparar é alguém em palco perceber o que aconteceu. Este script observa
# os dois, reinicia quem cair, e só desiste (parando tudo, com uma mensagem
# clara) se o mesmo processo morrer 3 vezes numa janela curta — a marca de
# que o problema é a configuração/ambiente, não azar, e reiniciar para
# sempre só ia mascarar isso.
#
# Uso:
#   ./scripts/macos/supervisor.sh [caminho/para/BigFile]
#   HUGO_ASSETS=/caminho/para/BigFile ./scripts/macos/supervisor.sh
#
# Ctrl-C (ou `kill` ao PID deste script) para tudo de forma limpa: jogo,
# bridge, e o audio-server clássico se tiver sido arrancado com --audio-pa.
#
# NOTA DE ARQUITETURA (achado, não assumido): a partir do B2, o bridge em
# modo `audio.mode: devices` (bridge/config.yaml) já escuta ele próprio as
# portas UDP 9001-9004 para encaminhar som para os telemóveis
# (bridge/audio_router.py). O audio-server clássico (run-audio.sh) usa as
# MESMAS portas por omissão — arrancar os dois ao mesmo tempo faz um dos
# dois falhar a abrir a porta. Testado: com o bridge já a correr, o
# run-audio.sh falha com "a porta UDP 9001 respondeu, mas não pertence ao
# processo"; na ordem inversa, o bridge morre logo no arranque com
# `OSError: [Errno 48] Address already in use` em audio_router.py:130 — sem
# apanhar a exceção. Por isso este supervisor SÓ arranca o audio-server
# clássico se pedires --audio-pa explicitamente (o modo de recurso do PRD,
# "se os altifalantes dos telemóveis falharem"), e nesse caso o bridge
# deve estar configurado para `audio.mode: pa` — isso é conteúdo de
# bridge/config.yaml, fora do alcance deste script.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_PY="$REPO_DIR/.venv/bin/python"

# Quando este ficheiro é lançado com `... &`, o Bash não interactivo herda
# SIGINT como ignorado. Nessa situação Bash 3.2 não permite que `trap INT`
# o volte a apanhar: `kill -INT <pid>` seria ignorado para sempre. Recomeçamos
# uma vez por Python da .venv, que repõe INT/TERM no estado por omissão antes
# de re-executar Bash. O PID não muda, por isso quem lançou o supervisor pode
# continuar a enviar-lhe sinais directamente.
if [[ "${HUGO_SUPERVISOR_SIGNALS_READY:-}" != "1" ]] && [[ -x "$VENV_PY" ]]; then
  export HUGO_SUPERVISOR_SIGNALS_READY=1
  exec "$VENV_PY" -c '
import os
import signal
import sys

signal.signal(signal.SIGINT, signal.SIG_DFL)
signal.signal(signal.SIGTERM, signal.SIG_DFL)
os.execv(sys.argv[1], sys.argv[1:])
' /bin/bash "$0" "$@"
fi

AUDIO_PA=0
ASSETS=""
for arg in "$@"; do
  case "$arg" in
    --audio-pa) AUDIO_PA=1 ;;
    *) ASSETS="$arg" ;;
  esac
done
ASSETS="${ASSETS:-${HUGO_ASSETS:-}}"

if [[ -z "$ASSETS" ]]; then
  echo "[FALHA] indica a pasta BigFile, por argumento ou em HUGO_ASSETS." >&2
  echo "        exemplo: ./scripts/macos/supervisor.sh ~/hugo-assets/gold/BigFile" >&2
  exit 1
fi
if [[ ! -x "$VENV_PY" ]]; then
  echo "[FALHA] não encontrei o .venv em $REPO_DIR/.venv. Corre primeiro scripts/macos/setup.sh." >&2
  exit 1
fi

# -- log num sítio óbvio, com timestamps ------------------------------------
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/supervisor-$(date +%Y%m%d-%H%M%S).log"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"
}

# -- limite de reinícios: 3 mortes do mesmo processo em menos de 60s = desiste
MAX_DEATHS=3
WINDOW_SECONDS=60
# Bash só corre uma trap pendente quando o comando em primeiro plano acaba.
# Um intervalo curto limita a latência de INT/TERM, sem transformar a vigia
# num ciclo ocupado. `wait -n` não existe no Bash 3.2 fornecido pelo macOS.
POLL_INTERVAL=0.2

# Janela deslizante de timestamps de morte, sem arrays (bash 3.2 do macOS não
# tem `local -n`/namerefs) — três variáveis escalares chegam como fila FIFO.
GAME_D1=0; GAME_D2=0; GAME_D3=0
BRIDGE_D1=0; BRIDGE_D2=0; BRIDGE_D3=0
SIP_D1=0; SIP_D2=0; SIP_D3=0

GAME_PID=""
BRIDGE_PID=""
SIP_PID=""
AUDIO_WRAPPER_PID=""
AUDIO_SERVER_PID=""
STOPPING=0

# ATENÇÃO ao padrão (mesma armadilha documentada em run-event.sh): `pgrep -f
# audio_server.py` também apanha a linha de comando deste próprio script se o
# texto aparecer nela. `[a]udio_server\.py` não corresponde a si mesmo.
PADRAO_AUDIO='[a]udio_server\.py'
audio_vivo() { pgrep -f "$PADRAO_AUDIO" >/dev/null 2>&1; }

start_audio_pa() {
  log "== a arrancar o audio-server clássico (--audio-pa) =="
  HUGO_ASSETS="$ASSETS" "$SCRIPT_DIR/run-audio.sh" "$ASSETS" >>"$LOG_FILE" 2>&1 &
  AUDIO_WRAPPER_PID=$!
  local pronto=0
  for _ in $(seq 1 40); do
    if audio_vivo; then
      pronto=1
      AUDIO_SERVER_PID="$(pgrep -f "$PADRAO_AUDIO" | head -1)"
      break
    fi
    if ! kill -0 "$AUDIO_WRAPPER_PID" 2>/dev/null; then break; fi
    sleep 0.5
  done
  if [[ "$pronto" -ne 1 ]]; then
    log "[FALHA] o audio-server clássico não arrancou (ver $LOG_FILE)."
  else
    log "[ok] audio-server clássico pronto (PID $AUDIO_SERVER_PID)."
  fi
}

stop_audio_pa() {
  [[ "$AUDIO_PA" -eq 1 ]] || return 0
  log "== a desligar o audio-server clássico =="
  [[ -n "$AUDIO_SERVER_PID" ]] && matar_com_escalada "$AUDIO_SERVER_PID" "o audio-server clássico"
  [[ -n "$AUDIO_WRAPPER_PID" ]] && matar_com_escalada "$AUDIO_WRAPPER_PID" "o lançador do audio-server"
  while IFS= read -r pid; do
    [[ -n "$pid" ]] && matar_com_escalada "$pid" "um audio-server clássico residual"
  done < <(pgrep -f "$PADRAO_AUDIO" 2>/dev/null || true)
}

start_game() {
  HUGO_ASSETS="$ASSETS" "$SCRIPT_DIR/run-game.sh" "$ASSETS" >>"$LOG_FILE" 2>&1 &
  GAME_PID=$!
  log "[ok] jogo arrancado (PID $GAME_PID)."
}

start_bridge() {
  "$VENV_PY" "$REPO_DIR/bridge/main.py" >>"$LOG_FILE" 2>&1 &
  BRIDGE_PID=$!
  log "[ok] bridge arrancado (PID $BRIDGE_PID)."
}

# O FreeSWITCH passa a arrancar SEMPRE, mesmo quando o evento começa em modo
# telemóveis. A razão é o botão de modo no ecrã grande (ver game/mode_button.py):
# se o FreeSWITCH só subisse quando alguém escolhesse "telefones", o botão
# ficava a prometer uma coisa que demorava meio minuto a existir — ou que não
# existia de todo se o binário faltasse. A escutar sem ninguém a ligar não faz
# mal nenhum; só segura a porta 5060.
#
# REGRA, a mesma do túnel em bridge/tunnel.py: isto NUNCA pode impedir o evento
# de arrancar. Sem FreeSWITCH instalado, ou se ele não subir, fica registado e
# segue-se — o modo telemóveis, que é o normal, não depende disto para nada.
start_sip() {
  log "== a arrancar o FreeSWITCH (telefones) =="
  "$SCRIPT_DIR/run-sip.sh" >>"$LOG_FILE" 2>&1 &
  SIP_PID=$!
  for _ in $(seq 1 60); do
    if ! kill -0 "$SIP_PID" 2>/dev/null; then
      SIP_PID=""
      log "[aviso] o FreeSWITCH não arrancou (ver $LOG_FILE)."
      log "[aviso] O evento segue em modo telemóveis; o botão de TELEFONES não vai funcionar."
      return 0
    fi
    if grep -q "== FreeSWITCH pronto ==" "$LOG_FILE" 2>/dev/null; then
      log "[ok] FreeSWITCH pronto (PID $SIP_PID)."
      return 0
    fi
    sleep 0.5
  done
  log "[aviso] o FreeSWITCH demorou de mais a ficar pronto; deixa-se a arrancar em segundo plano."
}

# Manda SIGTERM e espera até 5s; escala para SIGKILL se não for suficiente.
# Medido: o jogo (pygame) por vezes demora vários segundos a reagir a um
# SIGTERM simples (sem handler próprio, mas o loop só verifica sinais
# pendentes entre frames) — não é fiável esperar que morra logo a seguir.
matar_com_escalada() {
  local pid="$1" nome="$2"
  kill -0 "$pid" 2>/dev/null || return 0
  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 17); do
    if ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid" 2>/dev/null || true
      log "[ok] $nome parou."
      return 0
    fi
    sleep 0.3
  done
  log "[aviso] $nome não reagiu a SIGTERM em 5s; a forçar com SIGKILL."
  kill -9 "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  if kill -0 "$pid" 2>/dev/null; then
    log "[aviso] não consegui confirmar a paragem de $nome (PID $pid)."
  else
    log "[ok] $nome foi forçado a parar."
  fi
}

parar_tudo() {
  [[ "$STOPPING" -eq 1 ]] && return 0
  STOPPING=1
  log "== a parar tudo =="
  [[ -n "$GAME_PID" ]] && matar_com_escalada "$GAME_PID" "o jogo"
  [[ -n "$BRIDGE_PID" ]] && matar_com_escalada "$BRIDGE_PID" "o bridge"
  # O run-sip.sh tem trap própria: ao receber o sinal desliga o FreeSWITCH
  # antes de sair, portanto basta matar o lançador.
  [[ -n "$SIP_PID" ]] && matar_com_escalada "$SIP_PID" "o FreeSWITCH"
  stop_audio_pa
  log "== supervisor parado. Log completo em: $LOG_FILE =="
}

on_signal() {
  log "Sinal de paragem recebido."
  parar_tudo
  exit 0
}
trap on_signal INT TERM

# Regista uma morte na fila FIFO de 3 posições da variável $1_D1/$1_D2/$1_D3 e
# devolve 1 (esgotou o limite) se as 3 couberem dentro da janela.
# $1 = prefixo ("GAME" ou "BRIDGE"), $2 = timestamp epoch da morte agora.
registar_morte() {
  local prefixo="$1" agora="$2" d1 d2 d3
  eval "d1=\$${prefixo}_D1; d2=\$${prefixo}_D2; d3=\$${prefixo}_D3"
  d1="$d2"; d2="$d3"; d3="$agora"
  eval "${prefixo}_D1=\$d1; ${prefixo}_D2=\$d2; ${prefixo}_D3=\$d3"
  if [[ "$d1" -ne 0 ]] && (( agora - d1 < WINDOW_SECONDS )); then
    return 1
  fi
  return 0
}

log "== supervisor.sh a arrancar =="
log "   log: $LOG_FILE"
log "   assets: $ASSETS"
log "   limite: $MAX_DEATHS mortes em ${WINDOW_SECONDS}s por processo, depois desiste"

[[ "$AUDIO_PA" -eq 1 ]] && start_audio_pa
start_sip
start_game
start_bridge

log "== a vigiar (Ctrl-C para tudo de forma limpa) =="
while true; do
  # O `|| true` evita que `set -e` saia antes de a trap correr se o sleep for
  # interrompido por INT ou TERM.
  sleep "$POLL_INTERVAL" || true
  AGORA="$(date +%s)"

  if [[ -n "$GAME_PID" ]] && ! kill -0 "$GAME_PID" 2>/dev/null; then
    log "[FALHA] o jogo morreu (PID $GAME_PID)."
    if registar_morte GAME "$AGORA"; then
      log "== a reiniciar o jogo =="
      start_game
    else
      log "[FALHA] o jogo morreu $MAX_DEATHS vezes em menos de ${WINDOW_SECONDS}s."
      log "[FALHA] A DESISTIR — não vou reiniciar para sempre. Vê o log e resolve à mão: $LOG_FILE"
      parar_tudo
      exit 1
    fi
  fi

  if [[ -n "$BRIDGE_PID" ]] && ! kill -0 "$BRIDGE_PID" 2>/dev/null; then
    log "[FALHA] o bridge morreu (PID $BRIDGE_PID)."
    if registar_morte BRIDGE "$AGORA"; then
      log "== a reiniciar o bridge =="
      start_bridge
    else
      log "[FALHA] o bridge morreu $MAX_DEATHS vezes em menos de ${WINDOW_SECONDS}s."
      log "[FALHA] A DESISTIR — não vou reiniciar para sempre. Vê o log e resolve à mão: $LOG_FILE"
      parar_tudo
      exit 1
    fi
  fi

  # O FreeSWITCH reinicia-se, mas nunca derruba o evento: esgotado o limite
  # ficam só os telemóveis, que é o modo normal.
  if [[ -n "$SIP_PID" ]] && ! kill -0 "$SIP_PID" 2>/dev/null; then
    log "[aviso] o FreeSWITCH morreu (PID $SIP_PID)."
    SIP_PID=""
    if registar_morte SIP "$AGORA"; then
      start_sip
    else
      log "[aviso] o FreeSWITCH morreu $MAX_DEATHS vezes em menos de ${WINDOW_SECONDS}s — desisto dele."
      log "[aviso] O evento continua em modo telemóveis; o botão de TELEFONES deixa de funcionar."
    fi
  fi

  if [[ "$AUDIO_PA" -eq 1 ]] && [[ -n "$AUDIO_SERVER_PID" ]] && ! kill -0 "$AUDIO_SERVER_PID" 2>/dev/null; then
    log "[aviso] o audio-server clássico morreu (PID $AUDIO_SERVER_PID); não é reiniciado automaticamente."
    log "[aviso] o jogo continua, mas sem som pelas colunas — e com o congelamento de 1s por som descrito no ledger."
    AUDIO_SERVER_PID=""
  fi
done
