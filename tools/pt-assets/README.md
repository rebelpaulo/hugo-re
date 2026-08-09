# Clips portugueses do Hugo

1. Descarrega o master e guarda-o como `../../../hugo-assets/pt-master.mkv` (ou muda `source` em `cuts.yaml`).
2. Afina os seis pares `start`/`end` em `cuts.yaml`; os valores incluídos são apenas um primeiro palpite.
3. Corre `./build.sh` para gerar os AVI e WAV; usa `./build.sh --dry-run` para ver os comandos sem escrever ficheiros.
4. Corre `./preview.sh` e abre `preview/contact-sheet.png` e `preview/clips-pt.mp4`.
5. Repete os passos 2–4 até nenhuma fala ou imagem ficar cortada.

Os caminhos relativos são resolvidos a partir do ficheiro YAML. Para experimentar outra configuração, usa `./build.sh --cuts /caminho/cuts.yaml` e `./preview.sh --cuts /caminho/cuts.yaml`. Os scripts precisam do PyYAML no Python ARM; se faltar, indicam o comando de instalação e param.

## Especificações de saída

| Saída | Codec | Dimensões / som | Cadência | Container |
|---|---|---|---|---|
| Vídeo | MJPEG, sem faixa de áudio | 320×240 | 25 fps | AVI |
| Áudio | PCM signed 16-bit little-endian | 48 000 Hz, estéreo | — | WAV |

O áudio é normalizado para -16 LUFS, com true peak máximo de -1,5 dB. Como o vídeo tem 25 frames por segundo, o pipeline alinha o fim do WAV à grelha de 40 ms do AVI; ambos ficam com a mesma duração ao milissegundo.

## Atenção aos nomes

Os nomes estão hardcoded em `game/tv_show/tv_show_resources.py` e não podem mudar:

`attract_demo`, `hello_hello`, `press_5`, `scylla_cave`, `you_lost`, `have_luck`.

Cada nome tem de produzir um `.avi` em `game/resources/videos/pt/` e um `.wav` em `game/resources/audio_for_videos/pt/`. O AVI não pode ter áudio: o jogo toca sempre o WAV separado através do audio-server.
