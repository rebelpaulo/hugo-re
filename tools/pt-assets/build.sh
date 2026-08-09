#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Prefere o venv do repo — é lá que o PyYAML vive. Cai no Python ARM do sistema
# se o venv ainda não existir. Podes forçar com PYTHON=... ./build.sh
PYTHON="${PYTHON:-$SCRIPT_DIR/../../.venv/bin/python}"
[[ -x "$PYTHON" ]] || PYTHON="/opt/homebrew/bin/python3.13"
FFMPEG="/usr/local/bin/ffmpeg"
FFPROBE="/usr/local/bin/ffprobe"
CUTS_FILE="$SCRIPT_DIR/cuts.yaml"
DRY_RUN=0
EXPECTED=(attract_demo hello_hello press_5 scylla_cave you_lost have_luck)

usage() {
  echo "Uso: ./build.sh [--cuts <ficheiro>] [--dry-run]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cuts)
      [[ $# -ge 2 ]] || { echo "Erro: falta o ficheiro depois de --cuts." >&2; usage >&2; exit 2; }
      CUTS_FILE="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Erro: argumento desconhecido: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ -x "$PYTHON" ]] || { echo "Erro: não encontrei o Python ARM em $PYTHON." >&2; exit 1; }
[[ -x "$FFMPEG" ]] || { echo "Erro: não encontrei o ffmpeg em $FFMPEG." >&2; exit 1; }
[[ -x "$FFPROBE" ]] || { echo "Erro: não encontrei o ffprobe em $FFPROBE." >&2; exit 1; }
[[ -f "$CUTS_FILE" ]] || { echo "Erro: não encontrei o ficheiro de cortes: $CUTS_FILE" >&2; exit 1; }

if ! "$PYTHON" -c 'import yaml' >/dev/null 2>&1; then
  echo "Erro: falta o módulo PyYAML no Python ARM." >&2
  echo "Instala-o com: $PYTHON -m pip install PyYAML" >&2
  exit 1
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/hugo-pt-build.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT
META_FILE="$WORK_DIR/cortes.tsv"

# Resolve os caminhos e valida o schema sem criar outputs.
if ! "$PYTHON" - "$CUTS_FILE" >"$META_FILE" <<'PY'
import re
import sys
from pathlib import Path

import yaml

cuts_path = Path(sys.argv[1]).expanduser().resolve()
expected = [
    "attract_demo", "hello_hello", "press_5",
    "scylla_cave", "you_lost", "have_luck",
]
pattern = re.compile(r"^(\d+):([0-5]\d):([0-5]\d)\.(\d{3})$")

def fail(message):
    raise SystemExit(f"Erro em {cuts_path}: {message}")

def clean_path(value, field):
    if not isinstance(value, str) or not value.strip():
        fail(f"'{field}' tem de ser um caminho não vazio")
    if "\t" in value or "\n" in value:
        fail(f"'{field}' não pode conter tabs nem mudanças de linha")
    return str((cuts_path.parent / value).resolve())

def millis(value, field, name):
    if not isinstance(value, str):
        fail(f"'{field}' do clip '{name}' tem de estar entre aspas")
    match = pattern.fullmatch(value)
    if not match:
        fail(f"'{field}' do clip '{name}' não segue HH:MM:SS.mmm")
    hours, minutes, seconds, ms = map(int, match.groups())
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + ms

try:
    data = yaml.safe_load(cuts_path.read_text(encoding="utf-8"))
except (OSError, yaml.YAMLError) as exc:
    fail(f"não foi possível ler o YAML: {exc}")
if not isinstance(data, dict):
    fail("a raiz do YAML tem de ser um mapa")

source = clean_path(data.get("source"), "source")
video_dir = clean_path(data.get("output_video"), "output_video")
audio_dir = clean_path(data.get("output_audio"), "output_audio")
clips = data.get("clips")
if not isinstance(clips, list):
    fail("'clips' tem de ser uma lista")

parsed = []
for item in clips:
    if not isinstance(item, dict):
        fail("cada clip tem de ser um mapa")
    name = item.get("name")
    if not isinstance(name, str) or "\t" in name or "\n" in name:
        fail("cada clip precisa de um nome válido")
    start = item.get("start")
    end = item.get("end")
    start_ms = millis(start, "start", name)
    end_ms = millis(end, "end", name)
    if end_ms <= start_ms:
        fail(f"o fim de '{name}' tem de ser posterior ao início")
    parsed.append((name, start, end, start_ms, end_ms))

names = [item[0] for item in parsed]
missing = [name for name in expected if name not in names]
extra = [name for name in names if name not in expected]
duplicates = sorted({name for name in names if names.count(name) > 1})
if missing or extra or duplicates or len(names) != len(expected):
    details = []
    if missing:
        details.append("em falta: " + ", ".join(missing))
    if extra:
        details.append("a mais: " + ", ".join(extra))
    if duplicates:
        details.append("repetidos: " + ", ".join(duplicates))
    fail("os nomes dos clips não são os seis esperados (" + "; ".join(details) + ")")

print("PATHS\t" + "\t".join((source, video_dir, audio_dir)))
by_name = {item[0]: item for item in parsed}
for name in expected:
    _, start, end, start_ms, end_ms = by_name[name]
    # O WAV termina na mesma grelha de 40 ms do vídeo a 25 fps.
    frames = (end_ms - start_ms) * 25 // 1000
    if frames < 1:
        fail(f"o clip '{name}' é demasiado curto para conter um frame a 25 fps")
    aligned = f"{frames / 25:.3f}"
    start_seconds = f"{start_ms / 1000:.3f}"
    aligned_end = f"{(start_ms + frames * 40) / 1000:.3f}"
    print("CLIP\t" + "\t".join((name, start, end, aligned, start_seconds, aligned_end, str(frames))))
PY
then
  exit 1
fi

IFS=$'\t' read -r marker SOURCE OUTPUT_VIDEO OUTPUT_AUDIO < "$META_FILE"
[[ "$marker" == "PATHS" ]] || { echo "Erro interno: metadados de caminhos inválidos." >&2; exit 1; }
[[ -f "$SOURCE" ]] || { echo "Erro: o master não existe: $SOURCE" >&2; exit 1; }

MASTER_DURATION="$("$FFPROBE" -v error -show_entries format=duration -of default=nw=1:nk=1 "$SOURCE")"
if ! "$PYTHON" - "$META_FILE" "$MASTER_DURATION" <<'PY'
import re
import sys

meta_path, duration_raw = sys.argv[1:]
try:
    master_ms = round(float(duration_raw) * 1000)
except ValueError:
    raise SystemExit("Erro: o ffprobe não devolveu uma duração válida para o master.")
pattern = re.compile(r"^(\d+):([0-5]\d):([0-5]\d)\.(\d{3})$")

def to_ms(value):
    h, m, s, ms = map(int, pattern.fullmatch(value).groups())
    return ((h * 60 + m) * 60 + s) * 1000 + ms

with open(meta_path, encoding="utf-8") as handle:
    for line in handle:
        fields = line.rstrip("\n").split("\t")
        if fields[0] == "CLIP" and to_ms(fields[3]) > master_ms:
            raise SystemExit(
                f"Erro: o fim de '{fields[1]}' ({fields[3]}) ultrapassa "
                f"a duração do master ({master_ms / 1000:.3f} s)."
            )
PY
then
  exit 1
fi

run_command() {
  printf '  '
  printf '%q ' "$@"
  printf '\n'
  if [[ "$DRY_RUN" -eq 0 ]]; then
    "$@"
  fi
}

if [[ "$DRY_RUN" -eq 0 ]]; then
  mkdir -p "$OUTPUT_VIDEO" "$OUTPUT_AUDIO"
fi

echo "Master: $SOURCE (${MASTER_DURATION}s)"
echo "Comandos de corte:"
while IFS=$'\t' read -r kind name start end aligned start_seconds aligned_end frames; do
  [[ "$kind" == "CLIP" ]] || continue
  video="$OUTPUT_VIDEO/$name.avi"
  audio="$OUTPUT_AUDIO/$name.wav"
  run_command "$FFMPEG" -nostdin -hide_banner -loglevel error -y -i "$SOURCE" \
    -ss "$start" -to "$end" -map 0:v:0 -an \
    -vf "scale=320:240:force_original_aspect_ratio=decrease,pad=320:240:(ow-iw)/2:(oh-ih)/2,fps=25" \
    -c:v mjpeg -q:v 2 -frames:v "$frames" "$video"
  run_command "$FFMPEG" -nostdin -hide_banner -loglevel error -y -i "$SOURCE" \
    -ss "$start" -to "$end" -map 0:a:0 -vn \
    -af "loudnorm=I=-16:TP=-1.5:LRA=11,atrim=start=$start_seconds:end=$aligned_end" \
    -ar 48000 -ac 2 -c:a pcm_s16le "$audio"
done < "$META_FILE"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "Dry-run concluído; nenhum ficheiro foi escrito."
  exit 0
fi

echo
echo "Verificação dos ficheiros produzidos:"
printf '%-18s %-6s %-10s %-11s %-8s %-8s %-10s %s\n' \
  "CLIP" "TIPO" "CODEC" "DIMENSÕES" "FPS" "HZ" "DURAÇÃO" "ESTADO"

VERIFY_FILE="$WORK_DIR/verificacao.tsv"
: > "$VERIFY_FILE"
for name in "${EXPECTED[@]}"; do
  "$PYTHON" - "$FFPROBE" "$OUTPUT_VIDEO/$name.avi" "$OUTPUT_AUDIO/$name.wav" "$name" >> "$VERIFY_FILE" <<'PY'
import json
import subprocess
import sys

ffprobe, video, audio, name = sys.argv[1:]
def probe(path):
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        check=True, text=True, stdout=subprocess.PIPE,
    )
    return json.loads(result.stdout)

vdata, adata = probe(video), probe(audio)
vstreams = [s for s in vdata["streams"] if s.get("codec_type") == "video"]
unexpected_audio = [s for s in vdata["streams"] if s.get("codec_type") == "audio"]
astreams = [s for s in adata["streams"] if s.get("codec_type") == "audio"]
errors = []
if len(vstreams) != 1: errors.append("número de faixas de vídeo inválido")
if unexpected_audio: errors.append("AVI contém áudio")
if len(astreams) != 1: errors.append("número de faixas de áudio inválido")
v = vstreams[0] if vstreams else {}
a = astreams[0] if astreams else {}
if v.get("codec_name") != "mjpeg": errors.append("codec de vídeo")
if (v.get("width"), v.get("height")) != (320, 240): errors.append("dimensões")
if v.get("r_frame_rate") != "25/1": errors.append("fps")
if a.get("codec_name") != "pcm_s16le": errors.append("codec de áudio")
if a.get("sample_rate") != "48000": errors.append("sample rate")
if a.get("channels") != 2: errors.append("canais")
try:
    vd = float(vdata["format"]["duration"])
    ad = float(adata["format"]["duration"])
except (KeyError, ValueError):
    vd = ad = -1
    errors.append("duração")
delta_ms = abs(vd - ad) * 1000
if delta_ms > 1.0: errors.append(f"duração difere {delta_ms:.3f} ms")
state = "OK" if not errors else "ERRO: " + ", ".join(errors)
print("\t".join((name, "vídeo", v.get("codec_name", "-"),
    f'{v.get("width", "-")}x{v.get("height", "-")}', v.get("r_frame_rate", "-"),
    "-", f"{vd:.3f}", state)))
print("\t".join((name, "áudio", a.get("codec_name", "-"), "-", "-",
    a.get("sample_rate", "-"), f"{ad:.3f}", state)))
PY
done

verification_failed=0
while IFS=$'\t' read -r name kind codec dimensions fps hz duration state; do
  printf '%-18s %-6s %-10s %-11s %-8s %-8s %-10s %s\n' \
    "$name" "$kind" "$codec" "$dimensions" "$fps" "$hz" "$duration" "$state"
  [[ "$state" == "OK" ]] || verification_failed=1
done < "$VERIFY_FILE"

if [[ "$verification_failed" -ne 0 ]]; then
  echo "Erro: pelo menos um ficheiro não cumpre as especificações." >&2
  exit 1
fi
echo "Os 12 ficheiros cumprem as especificações."
