#!/bin/bash
# Arranque único para o dia do evento: liga o audio-server, corre o jogo, e
# desliga o áudio quando o jogo fecha.
#
# Porque é que isto existe: o run-audio.sh e o run-game.sh são processos
# independentes. Fechar o jogo não diz nada ao servidor de áudio, que fica a
# tocar o que tinha em curso — e a segurar as portas UDP, o que impede o
# arranque seguinte. Ao vivo isso é som a sair do PA sem nada no ecrã.
#
# Uso:
#   ./scripts/macos/run-event.sh [caminho/para/BigFile]
#   HUGO_ASSETS=/caminho/para/BigFile ./scripts/macos/run-event.sh
#
# Sai com Ctrl-C ou com F12 dentro do jogo. Nos dois casos o áudio morre.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

ASSETS="${1:-${HUGO_ASSETS:-}}"
if [[ -z "$ASSETS" ]]; then
  echo "[FALHA] indica a pasta BigFile, por argumento ou em HUGO_ASSETS." >&2
  echo "        exemplo: ./scripts/macos/run-event.sh ~/hugo-assets/gold/BigFile" >&2
  exit 1
fi

AUDIO_PID=""
SERVER_PID=""

# ATENÇÃO ao padrão: `pgrep -f audio_server.py` também apanha qualquer shell
# cuja linha de comando contenha esse texto — incluindo este próprio script e
# o terminal de quem o lançou. A classe de caracteres `[a]` faz o padrão não
# corresponder a si mesmo. Já matei o meu próprio shell de teste com a versão
# ingénua disto.
PADRAO_AUDIO='[a]udio_server\.py'

audio_vivo() { pgrep -f "$PADRAO_AUDIO" >/dev/null 2>&1; }

parar_audio() {
  echo ""
  echo "== a desligar o áudio =="
  # Primeiro pelo PID que nós arrancámos, que é sempre o correto.
  [[ -n "$SERVER_PID" ]] && kill "$SERVER_PID" 2>/dev/null || true
  [[ -n "$AUDIO_PID" ]] && kill "$AUDIO_PID" 2>/dev/null || true
  # Espera que largue as portas: um arranque imediato a seguir apanharia-as
  # ocupadas e o run-audio.sh recusar-se-ia a arrancar.
  for _ in $(seq 1 15); do
    audio_vivo || break
    sleep 0.3
  done
  audio_vivo && pkill -f "$PADRAO_AUDIO" 2>/dev/null || true
  return 0
}
trap parar_audio EXIT INT TERM

# Um audio-server esquecido de uma sessão anterior segura as portas e faz o
# arranque falhar.
if audio_vivo; then
  echo "== havia um audio-server de uma sessão anterior; a fechá-lo =="
  pkill -f "$PADRAO_AUDIO" 2>/dev/null || true
  sleep 1
fi

echo "== 1/2: audio-server =="
HUGO_ASSETS="$ASSETS" "$SCRIPT_DIR/run-audio.sh" "$ASSETS" &
AUDIO_PID=$!

# O run-audio.sh só devolve prontidão depois de sondar as portas a sério.
# Damos-lhe tempo, mas não esperamos para sempre.
pronto=0
for _ in $(seq 1 40); do
  if audio_vivo; then
    pronto=1
    # Guarda o PID real do servidor, para o desligar sem depender de padrões.
    SERVER_PID="$(pgrep -f "$PADRAO_AUDIO" | head -1)"
    break
  fi
  if ! kill -0 "$AUDIO_PID" 2>/dev/null; then break; fi
  sleep 0.5
done

if [[ "$pronto" -ne 1 ]]; then
  echo "[FALHA] o audio-server não arrancou. O jogo corre à mesma, mas sem som" >&2
  echo "        — e com um congelamento de 1 s por cada som pedido." >&2
  echo "        Vê as mensagens acima antes de continuares." >&2
fi

echo "== 2/2: jogo =="
# O jogo em primeiro plano: quando fechar, a trap desliga o áudio.
HUGO_ASSETS="$ASSETS" "$SCRIPT_DIR/run-game.sh" "$ASSETS"
