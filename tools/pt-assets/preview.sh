#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Prefere o venv do repo — é lá que o PyYAML vive. Cai no Python ARM do sistema
# se o venv ainda não existir. Podes forçar com PYTHON=... ./preview.sh
PYTHON="${PYTHON:-$SCRIPT_DIR/../../.venv/bin/python}"
[[ -x "$PYTHON" ]] || PYTHON="/opt/homebrew/bin/python3.13"
# Descobre o ffmpeg/ffprobe no PATH — funciona tanto com Homebrew Intel
# (/usr/local/bin) como Apple Silicon (/opt/homebrew/bin). Força um caminho
# com FFMPEG=/caminho/ffmpeg ou FFPROBE=/caminho/ffprobe.
FFMPEG="${FFMPEG:-$(command -v ffmpeg 2>/dev/null || true)}"
FFPROBE="${FFPROBE:-$(command -v ffprobe 2>/dev/null || true)}"
FONT_FILE="${FONT_FILE:-/System/Library/Fonts/Supplemental/Arial.ttf}"
CUTS_FILE="$SCRIPT_DIR/cuts.yaml"
EXPECTED=(attract_demo hello_hello press_5 scylla_cave you_lost have_luck)

if [[ "${1:-}" == "--cuts" && $# -eq 2 ]]; then
  CUTS_FILE="$2"
elif [[ $# -ne 0 ]]; then
  echo "Uso: ./preview.sh [--cuts <ficheiro>]" >&2
  exit 2
fi

[[ -x "$PYTHON" ]] || { echo "Erro: não encontrei o Python ARM em $PYTHON." >&2; exit 1; }
[[ -n "$FFMPEG" && -x "$FFMPEG" ]] || { echo "Erro: não encontrei o ffmpeg (define FFMPEG=/caminho/para/ffmpeg)." >&2; exit 1; }
[[ -n "$FFPROBE" && -x "$FFPROBE" ]] || { echo "Erro: não encontrei o ffprobe (define FFPROBE=/caminho/para/ffprobe)." >&2; exit 1; }
[[ -f "$FONT_FILE" ]] || { echo "Erro: não encontrei a fonte de macOS em $FONT_FILE." >&2; exit 1; }
"$FFMPEG" -version >/dev/null 2>&1 || { echo "Erro: $FFMPEG não corre." >&2; exit 1; }
"$FFPROBE" -version >/dev/null 2>&1 || { echo "Erro: $FFPROBE não corre." >&2; exit 1; }
[[ -f "$CUTS_FILE" ]] || { echo "Erro: não encontrei $CUTS_FILE." >&2; exit 1; }
if ! "$PYTHON" -c 'import yaml' >/dev/null 2>&1; then
  echo "Erro: falta o módulo PyYAML no Python ARM." >&2
  echo "Instala-o com: $PYTHON -m pip install PyYAML" >&2
  exit 1
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/hugo-pt-preview.XXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT

# Transporta os caminhos em JSON (achado 5) em vez de uma linha por campo —
# um "output_video" com uma mudança de linha já não desloca os campos
# seguintes. json.dumps escapa sempre \n dentro da string, por isso o JSON
# em si nunca tem uma quebra de linha a meio, mesmo que o caminho tenha.
PATHS_JSON="$("$PYTHON" - "$CUTS_FILE" <<'PY'
import json
import sys
from pathlib import Path

import yaml

path = Path(sys.argv[1]).expanduser().resolve()
data = yaml.safe_load(path.read_text(encoding="utf-8"))

def clean_path(value, field):
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"Erro: '{field}' não é um caminho válido em {path}.")
    if "\t" in value or "\n" in value:
        raise SystemExit(f"Erro: '{field}' não pode conter tabs nem mudanças de linha.")
    return str((path.parent / value).resolve())

print(json.dumps({
    "output_video": clean_path(data.get("output_video"), "output_video"),
    "output_audio": clean_path(data.get("output_audio"), "output_audio"),
}))
PY
)"

OUTPUT_VIDEO="$("$PYTHON" -c 'import json, sys; print(json.loads(sys.argv[1])["output_video"])' "$PATHS_JSON")"
OUTPUT_AUDIO="$("$PYTHON" -c 'import json, sys; print(json.loads(sys.argv[1])["output_audio"])' "$PATHS_JSON")"
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
      -frames:v 1 -vf "scale=320:240,drawtext=fontfile='$FONT_FILE':text='$name':x=8:y=h-th-8:fontsize=22:fontcolor=white:borderw=2:bordercolor=black" \
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
  filter+="[$video_index:v]setpts=PTS-STARTPTS,drawtext=fontfile='$FONT_FILE':text='$name':x=12:y=12:fontsize=24:fontcolor=white:borderw=2:bordercolor=black,format=yuv420p[v$index];"
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
