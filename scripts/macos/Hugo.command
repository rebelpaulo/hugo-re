#!/usr/bin/env bash
# Hugo.command — abrir com duplo-clique no Finder no dia do evento.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_PY="$REPO_DIR/.venv/bin/python"
ASSETS="${HUGO_ASSETS:-$HOME/Claude code/hugo-assets/gold/BigFile}"

if [[ ! -d "$ASSETS" ]]; then
  echo "[FALHA] Não encontrei a pasta BigFile."
  echo ""
  echo "Liga o disco/pasta de assets e volta a abrir este ficheiro, ou define"
  echo "HUGO_ASSETS para a pasta BigFile antes de o lançar."
  echo "Caminho procurado: $ASSETS"
  exit 1
fi

ASSETS="$(cd "$ASSETS" && pwd -P)"
export HUGO_ASSETS="$ASSETS"

echo "============================================================"
echo " HUGO — verificação antes do evento"
echo "============================================================"

# doctor.sh também verifica se o jogo e o bridge já estão vivos, algo que só
# será verdade depois de arrancar o supervisor. Essas são as únicas FALHAs
# esperadas nesta fase; qualquer outra impede o arranque.
DOCTOR_OUTPUT="$("$SCRIPT_DIR/doctor.sh" "$ASSETS" 2>&1)" || DOCTOR_STATUS=$?
DOCTOR_STATUS="${DOCTOR_STATUS:-0}"
printf '%s\n' "$DOCTOR_OUTPUT"

FALHAS_ANTES_DO_ARRANQUE="$(
  printf '%s\n' "$DOCTOR_OUTPUT" |
    grep '^\[FALHA\]' |
    grep -v '^\[FALHA\] bridge não respondeu em http://127.0.0.1:8080/' |
    grep -v '^\[FALHA\] sem processo do jogo (game.py) a correr' || true
)"

if [[ "$DOCTOR_STATUS" -ne 0 ]] && [[ -n "$FALHAS_ANTES_DO_ARRANQUE" ]]; then
  echo ""
  echo "[FALHA] A verificação encontrou algo essencial em falta."
  echo "Corrige as linhas [FALHA] acima antes de abrir o evento."
  exit 1
fi

# O doctor pode falhar sem deixar nenhuma linha [FALHA] — se rebentar a meio,
# por exemplo. Nesse caso não sabemos o que correu mal, e seguir em frente
# calado é a pior das opções: o evento arranca sem verificação nenhuma e
# ninguém dá por isso.
if [[ "$DOCTOR_STATUS" -ne 0 ]]; then
  echo ""
  echo "[FALHA] A verificação terminou com erro ($DOCTOR_STATUS) mas não disse porquê."
  echo "Isso normalmente quer dizer que o próprio doctor.sh rebentou."
  echo "Corre-o à mão para ver o que se passa:"
  echo "  scripts/macos/doctor.sh"
  exit 1
fi

if [[ ! -x "$VENV_PY" ]]; then
  echo "[FALHA] Não encontrei a .venv em $REPO_DIR/.venv."
  echo "Corre scripts/macos/setup.sh e volta a tentar."
  exit 1
fi

LOBBY_IP="$("$VENV_PY" - <<'PY'
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    sock.connect(("8.8.8.8", 80))
    print(sock.getsockname()[0])
except OSError:
    print("127.0.0.1")
finally:
    sock.close()
PY
)"

echo ""
echo "============================================================"
echo " O endereço do lobby aparece daqui a uns 30 segundos, quando"
echo " o bridge acabar de levantar o túnel — procura a linha LOBBY."
echo " É esse que o QR no ecrã grande vai ter, e funciona a partir"
echo " de qualquer rede, não só desta."
echo ""
echo " Sem túnel (sem internet, ou cloudflared em falta) fica valer"
echo " o endereço local, e aí só joga quem estiver nesta Wi-Fi:"
echo "   http://$LOBBY_IP:8080/"
echo "============================================================"
echo ""
echo "A arrancar o jogo e o bridge. Para parar, usa Ctrl-C nesta janela."

exec "$SCRIPT_DIR/supervisor.sh" "$ASSETS"
