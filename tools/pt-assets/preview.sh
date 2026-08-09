#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Prefere o venv do repo — é lá que o PyYAML vive. Cai no Python ARM do sistema
# se o venv ainda não existir. Podes forçar com PYTHON=... ./preview.sh
PYTHON="${PYTHON:-$SCRIPT_DIR/../../.venv/bin/python}"
[[ -x "$PYTHON" ]] || PYTHON="/opt/homebrew/bin/python3.13"
FFMPEG="/usr/local/bin/ffmpeg"
FFPROBE="/usr/local/bin/ffprobe"
CUTS_FILE="$SCRIPT_DIR/cuts.yaml"
EXPECTED=(attract_demo hello_hello press_5 scylla_cave you_lost have_luck)

if [[ "${1:-}" == "--cuts" && $# -eq 2 ]]; then
  CUTS_FILE="$2"
elif [[ $# -ne 0 ]]; then
  echo "Uso: ./preview.sh [--cuts <ficheiro>]" >&2
  exit 2
fi

[[ -x "$PYTHON" ]] || { echo "Erro: não encontrei o Python ARM em $PYTHON." >&2; exit 1; }
[[ -x "$FFMPEG" && -x "$FFPROBE" ]] || { echo "Erro: não encontrei ffmpeg/ffprobe em /usr/local/bin/." >&2; exit 1; }
[[ -f "$CUTS_FILE" ]] || { echo "Erro: não encontrei $CUTS_FILE." >&2; exit 1; }
if ! "$PYTHON" -c 'import yaml' >/dev/null 2>&1; then
  echo "Erro: falta o módulo PyYAML no Python ARM." >&2
  echo "Instala-o com: $PYTHON -m pip install PyYAML" >&2
  exit 1
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/hugo-pt-preview.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT
PATHS_FILE="$WORK_DIR/paths.tsv"

"$PYTHON" - "$CUTS_FILE" > "$PATHS_FILE" <<'PY'
import sys
from pathlib import Path
import yaml

path = Path(sys.argv[1]).expanduser().resolve()
data = yaml.safe_load(path.read_text(encoding="utf-8"))
for key in ("output_video", "output_audio"):
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise SystemExit(f"Erro: '{key}' não é um caminho válido em {path}.")
    print(str((path.parent / value).resolve()))
PY

OUTPUT_VIDEO="$(sed -n '1p' "$PATHS_FILE")"
OUTPUT_AUDIO="$(sed -n '2p' "$PATHS_FILE")"
PREVIEW_DIR="$SCRIPT_DIR/preview"
mkdir -p "$PREVIEW_DIR"

for name in "${EXPECTED[@]}"; do
  [[ -f "$OUTPUT_VIDEO/$name.avi" ]] || { echo "Erro: falta $OUTPUT_VIDEO/$name.avi; corre ./build.sh primeiro." >&2; exit 1; }
  [[ -f "$OUTPUT_AUDIO/$name.wav" ]] || { echo "Erro: falta $OUTPUT_AUDIO/$name.wav; corre ./build.sh primeiro." >&2; exit 1; }
done

# Extrai o primeiro, o central e o último frame útil de cada clip.
frame_inputs=()
layout=()
index=0
for row in "${!EXPECTED[@]}"; do
  name="${EXPECTED[$row]}"
  duration="$("$FFPROBE" -v error -show_entries format=duration -of default=nw=1:nk=1 "$OUTPUT_VIDEO/$name.avi")"
  positions="$("$PYTHON" - "$duration" <<'PY'
import sys
d = float(sys.argv[1])
print(f"0.000 {d / 2:.3f} {max(0, d - 0.080):.3f}")
PY
)"
  column=0
  for position in $positions; do
    frame="$WORK_DIR/frame-${index}.png"
    "$FFMPEG" -nostdin -hide_banner -loglevel error -y -ss "$position" -i "$OUTPUT_VIDEO/$name.avi" \
      -frames:v 1 -vf "scale=320:240,drawtext=text='$name':x=8:y=h-th-8:fontsize=22:fontcolor=white:borderw=2:bordercolor=black" \
      "$frame"
    frame_inputs+=( -i "$frame" )
    layout+=( "$((column * 320))_$((row * 240))" )
    index=$((index + 1))
    column=$((column + 1))
  done
done

layout_string="$(IFS='|'; echo "${layout[*]}")"
"$FFMPEG" -nostdin -hide_banner -loglevel error -y "${frame_inputs[@]}" \
  -filter_complex "xstack=inputs=18:layout=$layout_string" -frames:v 1 \
  "$PREVIEW_DIR/contact-sheet.png"

concat_inputs=()
filter=""
concat_refs=""
for index in "${!EXPECTED[@]}"; do
  name="${EXPECTED[$index]}"
  concat_inputs+=( -i "$OUTPUT_VIDEO/$name.avi" -i "$OUTPUT_AUDIO/$name.wav" )
  video_index=$((index * 2))
  audio_index=$((video_index + 1))
  filter+="[$video_index:v]setpts=PTS-STARTPTS,drawtext=text='$name':x=12:y=12:fontsize=24:fontcolor=white:borderw=2:bordercolor=black,format=yuv420p[v$index];"
  filter+="[$audio_index:a]asetpts=PTS-STARTPTS[a$index];"
  concat_refs+="[v$index][a$index]"
done
filter+="${concat_refs}concat=n=6:v=1:a=1[vout][aout]"

"$FFMPEG" -nostdin -hide_banner -loglevel error -y "${concat_inputs[@]}" \
  -filter_complex "$filter" -map '[vout]' -map '[aout]' \
  -c:v libx264 -crf 18 -preset medium -c:a aac -b:a 192k -movflags +faststart \
  "$PREVIEW_DIR/clips-pt.mp4"

echo "Contact sheet: $PREVIEW_DIR/contact-sheet.png"
echo "Vídeo com áudio: $PREVIEW_DIR/clips-pt.mp4"
