#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Prefere o venv do repo — é lá que o PyYAML vive. Cai no Python ARM do sistema
# se o venv ainda não existir. Podes forçar com PYTHON=... ./build.sh
PYTHON="${PYTHON:-$SCRIPT_DIR/../../.venv/bin/python}"
[[ -x "$PYTHON" ]] || PYTHON="/opt/homebrew/bin/python3.13"
# Descobre o ffmpeg/ffprobe no PATH — funciona tanto com Homebrew Intel
# (/usr/local/bin) como Apple Silicon (/opt/homebrew/bin). Força um caminho
# com FFMPEG=/caminho/ffmpeg ou FFPROBE=/caminho/ffprobe.
FFMPEG="${FFMPEG:-$(command -v ffmpeg 2>/dev/null || true)}"
FFPROBE="${FFPROBE:-$(command -v ffprobe 2>/dev/null || true)}"
CUTS_FILE="$SCRIPT_DIR/cuts.yaml"
DRY_RUN=0
EXPECTED=(attract_demo hello_hello press_5 scylla_cave you_lost have_luck)
# Janela do crossfade de loop (clips marcados "loop: true" em cuts.yaml).
# ~0,8 s a 25 fps; dentro da faixa 0,5-1 s pedida.
LOOP_CROSSFADE_FRAMES=20

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
[[ -n "$FFMPEG" && -x "$FFMPEG" ]] || { echo "Erro: não encontrei o ffmpeg (define FFMPEG=/caminho/para/ffmpeg)." >&2; exit 1; }
[[ -n "$FFPROBE" && -x "$FFPROBE" ]] || { echo "Erro: não encontrei o ffprobe (define FFPROBE=/caminho/para/ffprobe)." >&2; exit 1; }
"$FFMPEG" -version >/dev/null 2>&1 || { echo "Erro: $FFMPEG não corre." >&2; exit 1; }
"$FFPROBE" -version >/dev/null 2>&1 || { echo "Erro: $FFPROBE não corre." >&2; exit 1; }
[[ -f "$CUTS_FILE" ]] || { echo "Erro: não encontrei o ficheiro de cortes: $CUTS_FILE" >&2; exit 1; }

if ! "$PYTHON" -c 'import yaml' >/dev/null 2>&1; then
  echo "Erro: falta o módulo PyYAML no Python ARM." >&2
  echo "Instala-o com: $PYTHON -m pip install PyYAML" >&2
  exit 1
fi

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/hugo-pt-build.XXXXXX")"
# STAGE_VIDEO/STAGE_AUDIO só ficam definidas mais abaixo; a expansão
# "${VAR:-}" evita "unbound variable" se a trap disparar antes disso.
# A limpeza só apaga pastas cujo nome contenha ".build-" — rede de
# segurança para nunca apagar uma pasta de destino por engano.
limpar() {
  rm -rf "$WORK_DIR"
  local d
  for d in "${STAGE_VIDEO:-}" "${STAGE_AUDIO:-}"; do
    [[ -n "$d" && "$d" == *.build-* ]] && rm -rf "$d"
  done
  return 0
}
trap limpar EXIT
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
    loop = item.get("loop", False)
    if not isinstance(loop, bool):
        fail(f"'loop' do clip '{name}' tem de ser verdadeiro/falso")
    parsed.append((name, start, end, start_ms, end_ms, loop))

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
    _, start, end, start_ms, end_ms, loop = by_name[name]
    # O WAV termina na mesma grelha de 40 ms do vídeo a 25 fps.
    frames = (end_ms - start_ms) * 25 // 1000
    if frames < 1:
        fail(f"o clip '{name}' é demasiado curto para conter um frame a 25 fps")
    aligned = f"{frames / 25:.3f}"
    start_seconds = f"{start_ms / 1000:.3f}"
    aligned_end = f"{(start_ms + frames * 40) / 1000:.3f}"
    print("CLIP\t" + "\t".join((name, start, end, aligned, start_seconds, aligned_end, str(frames), "1" if loop else "0")))
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

# Passo 1 do loudnorm de dois passos: mede o segmento sem o alterar.
# Imprime "I TP LRA THRESH OFFSET" medidos.
measure_loudness() {
  local start_seconds="$1" end_seconds="$2" log="$WORK_DIR/loudnorm-measure.log"
  "$FFMPEG" -nostdin -hide_banner -loglevel info -i "$SOURCE" \
    -map 0:a:0 -vn \
    -af "atrim=start=$start_seconds:end=$end_seconds,asetpts=PTS-STARTPTS,loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json" \
    -f null - 2> "$log"
  "$PYTHON" - "$log" <<'PY'
import json
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
start = text.rindex("{")
end = text.rindex("}") + 1
data = json.loads(text[start:end])
print(data["input_i"], data["input_tp"], data["input_lra"], data["input_thresh"], data["target_offset"])
PY
}

# YAVG (luminância média) de um frame — usado para provar que o crossfade
# de loop aproximou as duas pontas do attract.
frame_yavg() {
  local video="$1" frame="$2"
  "$FFMPEG" -nostdin -hide_banner -loglevel error -i "$video" \
    -vf "select=eq(n\,$frame),signalstats,metadata=print:file=-" -frames:v 1 -f null - 2>/dev/null \
    | grep -o 'lavfi.signalstats.YAVG=[0-9.]*' | head -1 | cut -d= -f2
}

# Escreve tudo numa pasta de staging ao lado do destino final e só promove
# (achado 3) depois de o conjunto inteiro passar a verificação. Assim uma
# falha a meio nunca deixa clips novos misturados com antigos, nem um par
# vídeo/áudio dessincronizado.
# Os caminhos de staging são SEMPRE distintos dos de destino, mesmo em
# dry-run. Se apontassem para o destino, a trap de limpeza apagava os
# assets reais à saída — e um --dry-run destruía o que diz não tocar.
STAGE_VIDEO="$OUTPUT_VIDEO.build-$$"
STAGE_AUDIO="$OUTPUT_AUDIO.build-$$"
if [[ "$DRY_RUN" -eq 0 ]]; then
  rm -rf "$STAGE_VIDEO" "$STAGE_AUDIO"
  mkdir -p "$STAGE_VIDEO" "$STAGE_AUDIO"
fi

echo "Master: $SOURCE (${MASTER_DURATION}s)"
echo "Comandos de corte:"
while IFS=$'\t' read -r kind name start end aligned start_seconds aligned_end frames loop; do
  [[ "$kind" == "CLIP" ]] || continue
  video="$STAGE_VIDEO/$name.avi"
  audio="$STAGE_AUDIO/$name.wav"

  run_command "$FFMPEG" -nostdin -hide_banner -loglevel error -y -i "$SOURCE" \
    -ss "$start" -to "$end" -map 0:v:0 -an \
    -vf "scale=320:240:force_original_aspect_ratio=decrease,pad=320:240:(ow-iw)/2:(oh-ih)/2,fps=25" \
    -c:v mjpeg -q:v 2 -frames:v "$frames" "$video"

  if [[ "$loop" == "1" ]]; then
    # Clip marcado loop:true — cruza o fim com o início (achado 4) para o
    # ciclo fechar sem salto quando o jogo repete o ficheiro.
    overlap="$LOOP_CROSSFADE_FRAMES"
    if (( overlap * 2 >= frames )); then
      overlap=$(( frames / 4 ))
      (( overlap > 0 )) || overlap=1
    fi
    offset_ms=$(( (frames - overlap) * 40 ))
    offset_seconds=$(printf '%d.%03d' $((offset_ms / 1000)) $((offset_ms % 1000)))
    duration_ms=$(( overlap * 40 ))
    duration_seconds=$(printf '%d.%03d' $((duration_ms / 1000)) $((duration_ms % 1000)))
    loop_video="$STAGE_VIDEO/$name.loop.avi"
    run_command "$FFMPEG" -nostdin -hide_banner -loglevel error -y -i "$video" \
      -filter_complex "[0:v]split=2[main][headsrc];[headsrc]trim=start_frame=0:end_frame=$overlap,setpts=PTS-STARTPTS,fps=25[head];[main][head]xfade=transition=fade:duration=$duration_seconds:offset=$offset_seconds[out]" \
      -map "[out]" -c:v mjpeg -q:v 2 -frames:v "$frames" "$loop_video"
    if [[ "$DRY_RUN" -eq 0 ]]; then
      mv -f "$loop_video" "$video"
      yavg_first="$(frame_yavg "$video" 0)"
      yavg_last="$(frame_yavg "$video" $((frames - 1)))"
      echo "  loop '$name': crossfade de $overlap frames (${duration_seconds}s) — YAVG primeiro=$yavg_first último=$yavg_last"
    fi
  fi

  if [[ "$DRY_RUN" -eq 0 ]]; then
    # Passo 1 (medir) + passo 2 (aplicar com measured_*) do loudnorm de dois
    # passos (achado 2) — muito mais próximo do alvo de -16 LUFS do que o
    # passo único. O corte exacto é feito no início do filtro, ainda com os
    # timestamps absolutos do master. Repor os PTS antes de um -ss de saída
    # faria o ffmpeg descartar todo o áudio dos clips que não começam a zero.
    # apad+atrim garantem depois a duração alinhada à grelha de 40 ms.
    read -r meas_i meas_tp meas_lra meas_thresh meas_offset < <(measure_loudness "$start_seconds" "$aligned_end")
    loudnorm_filter="loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=$meas_i:measured_TP=$meas_tp:measured_LRA=$meas_lra:measured_thresh=$meas_thresh:offset=$meas_offset:linear=true"
  else
    loudnorm_filter="loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=<medido>:measured_TP=<medido>:measured_LRA=<medido>:measured_thresh=<medido>:offset=<medido>:linear=true"
  fi

  run_command "$FFMPEG" -nostdin -hide_banner -loglevel error -y -i "$SOURCE" \
    -map 0:a:0 -vn \
    -af "atrim=start=$start_seconds:end=$aligned_end,asetpts=PTS-STARTPTS,${loudnorm_filter},apad,atrim=start=0:end=$aligned,asetpts=PTS-STARTPTS" \
    -t "$aligned" -ar 48000 -ac 2 -c:a pcm_s16le "$audio"

  if [[ "$loop" == "1" ]]; then
    # Tal como no vídeo, cruza os últimos instantes com o início. O começo
    # recebe fade-in, é atrasado até à janela final e misturado sobre o
    # fade-out; o WAV conserva exactamente a duração alinhada do clip.
    loop_audio="$STAGE_AUDIO/$name.loop.wav"
    run_command "$FFMPEG" -nostdin -hide_banner -loglevel error -y \
      -i "$audio" -i "$audio" \
      -filter_complex "[0:a]afade=t=out:st=$offset_seconds:d=$duration_seconds[main];[1:a]atrim=start=0:end=$duration_seconds,asetpts=PTS-STARTPTS,afade=t=in:st=0:d=$duration_seconds,adelay=delays=$offset_ms:all=1[head];[main][head]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]" \
      -map "[aout]" -t "$aligned" -ar 48000 -ac 2 -c:a pcm_s16le "$loop_audio"
    if [[ "$DRY_RUN" -eq 0 ]]; then
      mv -f "$loop_audio" "$audio"
    fi
  fi
done < "$META_FILE"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "Dry-run concluído; nenhum ficheiro foi escrito."
  exit 0
fi

echo
echo "Verificação dos ficheiros produzidos:"
printf '%-18s %-6s %-10s %-11s %-8s %-8s %-10s %-7s %-7s %s\n' \
  "CLIP" "TIPO" "CODEC" "DIMENSÕES" "FPS" "HZ" "DURAÇÃO" "LUFS" "TP" "ESTADO"

VERIFY_FILE="$WORK_DIR/verificacao.tsv"
: > "$VERIFY_FILE"
for name in "${EXPECTED[@]}"; do
  "$PYTHON" - "$FFMPEG" "$FFPROBE" "$STAGE_VIDEO/$name.avi" "$STAGE_AUDIO/$name.wav" "$name" >> "$VERIFY_FILE" <<'PY'
import json
import subprocess
import sys

ffmpeg, ffprobe, video, audio, name = sys.argv[1:]

# Alvo do loudnorm e tolerância aceite na verificação final (achado 2).
TARGET_I, TARGET_TP = -16.0, -1.5
I_TOLERANCE, TP_TOLERANCE = 1.0, 0.3

def probe(path):
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        check=True, text=True, stdout=subprocess.PIPE,
    )
    return json.loads(result.stdout)

def measure_loudness(path):
    result = subprocess.run(
        [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "info", "-i", path,
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
        check=True, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    text = result.stderr
    start = text.rindex("{")
    end = text.rindex("}") + 1
    data = json.loads(text[start:end])
    return float(data["input_i"]), float(data["input_tp"])

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

try:
    lufs, tp = measure_loudness(audio)
except (subprocess.CalledProcessError, ValueError, KeyError):
    lufs = tp = float("nan")
    errors.append("não foi possível medir LUFS/true peak")
else:
    if abs(lufs - TARGET_I) > I_TOLERANCE:
        errors.append(f"LUFS fora da tolerância ({lufs:.1f})")
    if tp > TARGET_TP + TP_TOLERANCE:
        errors.append(f"true peak fora da tolerância ({tp:.1f} dBTP)")

state = "OK" if not errors else "ERRO: " + ", ".join(errors)
print("\t".join((name, "vídeo", v.get("codec_name", "-"),
    f'{v.get("width", "-")}x{v.get("height", "-")}', v.get("r_frame_rate", "-"),
    "-", f"{vd:.3f}", "-", "-", state)))
print("\t".join((name, "áudio", a.get("codec_name", "-"), "-", "-",
    a.get("sample_rate", "-"), f"{ad:.3f}", f"{lufs:.1f}", f"{tp:.1f}", state)))
PY
done

verification_failed=0
while IFS=$'\t' read -r name kind codec dimensions fps hz duration lufs tp state; do
  printf '%-18s %-6s %-10s %-11s %-8s %-8s %-10s %-7s %-7s %s\n' \
    "$name" "$kind" "$codec" "$dimensions" "$fps" "$hz" "$duration" "$lufs" "$tp" "$state"
  [[ "$state" == "OK" ]] || verification_failed=1
done < "$VERIFY_FILE"

if [[ "$verification_failed" -ne 0 ]]; then
  echo "Erro: pelo menos um ficheiro não cumpre as especificações." >&2
  echo "Os ficheiros de staging ficam em $STAGE_VIDEO e $STAGE_AUDIO até o script terminar; nada foi promovido para o destino final." >&2
  exit 1
fi
echo "Os 12 ficheiros cumprem as especificações."

# Só agora, com o conjunto inteiro validado, é que o destino final é tocado.
mkdir -p "$OUTPUT_VIDEO" "$OUTPUT_AUDIO"
for name in "${EXPECTED[@]}"; do
  mv -f "$STAGE_VIDEO/$name.avi" "$OUTPUT_VIDEO/$name.avi"
  mv -f "$STAGE_AUDIO/$name.wav" "$OUTPUT_AUDIO/$name.wav"
done
echo "Promovido para: $OUTPUT_VIDEO e $OUTPUT_AUDIO"
