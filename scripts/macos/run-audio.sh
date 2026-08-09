#!/usr/bin/env bash
# Arranca uma instância do audio-server nas quatro portas usadas pelo jogo,
# cada uma a sair pela saída de áudio default do Mac. Depois do B1, esta lista
# colapsa para uma única porta e um único sink.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_PY="$REPO_ROOT/.venv/bin/python3"
PORTS="9001,9002,9003,9004"
SINKS="default,default,default,default"

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

ASSETS="$(cd "$ASSETS" && pwd -P)"

if [ ! -x "$VENV_PY" ]; then
  echo "ERRO: não encontrei o .venv em $REPO_ROOT/.venv." >&2
  echo "Corre primeiro: scripts/macos/setup.sh" >&2
  exit 1
fi

echo "== run-audio.sh: audio-server nas portas 9001-9004, saída default do Mac =="
echo "   assets:    $ASSETS"
echo "   resources: $REPO_ROOT/game/resources"

COMMAND=(
  "$VENV_PY" "$REPO_ROOT/audio-server/audio_server.py"
  --host 127.0.0.1
  --ports "$PORTS"
  --sinks "$SINKS"
  --assets "$ASSETS"
  --resources "$REPO_ROOT/game/resources"
)
printf '   comando:  '
printf ' %q' "${COMMAND[@]}"
printf '\n'

"${COMMAND[@]}" &
SERVER_PID=$!

cleanup() {
  if kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
  fi
  wait "$SERVER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if ! "$VENV_PY" - 9001 9002 9003 9004 <<'PY'
import json
import socket
import sys
import time

ports = [int(port) for port in sys.argv[1:]]
deadline = time.monotonic() + 5.0
pending = set(ports)

while pending and time.monotonic() < deadline:
    for port in tuple(pending):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.15)
            try:
                sock.sendto(b'{"cmd":"READY"}', ("127.0.0.1", port))
                data, _ = sock.recvfrom(4096)
                response = json.loads(data.decode("utf-8"))
                if isinstance(response, dict) and "error" in response:
                    pending.remove(port)
            except PermissionError as exc:
                print(f"ERRO: a sonda UDP local foi bloqueada: {exc}", file=sys.stderr)
                raise SystemExit(1) from exc
            except (OSError, ValueError):
                pass
    if pending:
        time.sleep(0.1)

if pending:
    print("ERRO: o audio-server não respondeu nas portas: " + ", ".join(map(str, sorted(pending))), file=sys.stderr)
    raise SystemExit(1)
PY
then
  echo "ERRO: o audio-server não ficou pronto; consulta as mensagens acima." >&2
  exit 1
fi

LISTENERS="$(lsof -nP -a -p "$SERVER_PID" -iUDP 2>/dev/null || true)"
for port in 9001 9002 9003 9004; do
  if ! grep -Fq "127.0.0.1:$port" <<<"$LISTENERS"; then
    echo "ERRO: a porta UDP $port respondeu, mas não pertence ao processo $SERVER_PID." >&2
    exit 1
  fi
done

echo "[ok] audio-server pronto em 127.0.0.1 nas portas 9001-9004."
wait "$SERVER_PID"
SERVER_STATUS=$?
trap - EXIT INT TERM
exit "$SERVER_STATUS"
