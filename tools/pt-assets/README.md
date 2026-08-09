# Clips portugueses do Hugo

1. Descarrega o master e guarda-o como `../../../hugo-assets/pt-master.mkv` (ou muda `source` em `cuts.yaml`).
2. Afina os seis pares `start`/`end` em `cuts.yaml`; os valores incluídos são apenas um primeiro palpite.
3. Corre `./build.sh` para gerar os AVI e WAV; usa `./build.sh --dry-run` para ver os comandos sem escrever ficheiros.
4. Corre `./preview.sh` e abre `preview/contact-sheet.png` e `preview/clips-pt.mp4`.
5. Repete os passos 2–4 até nenhuma fala ou imagem ficar cortada.

Os caminhos relativos são resolvidos a partir do ficheiro YAML. Para experimentar outra configuração, usa `./build.sh --cuts /caminho/cuts.yaml` e `./preview.sh --cuts /caminho/cuts.yaml`. Os scripts precisam do PyYAML no Python ARM; se faltar, indicam o comando de instalação e param.

Por omissão os scripts descobrem o `ffmpeg`/`ffprobe` no `PATH` (`command -v`); se precisares de um binário específico, define `FFMPEG=/caminho/ffmpeg` e/ou `FFPROBE=/caminho/ffprobe` antes de correr.

## Especificações de saída

| Saída | Codec | Dimensões / som | Cadência | Container |
|---|---|---|---|---|
| Vídeo | MJPEG, sem faixa de áudio | 320×240 | 25 fps | AVI |
| Áudio | PCM signed 16-bit little-endian | 48 000 Hz, estéreo | — | WAV |

O áudio é normalizado para -16 LUFS (true peak máximo de -1,5 dB) com **loudnorm de dois passos**: o `build.sh` mede primeiro o clip (`print_format=json`) e só depois aplica a normalização com os valores `measured_*`, o que fica muito mais próximo do alvo do que um passo único. Como o vídeo tem 25 frames por segundo, o pipeline alinha o fim do WAV à grelha de 40 ms do AVI com `apad` + corte explícito à duração alinhada (`asetpts` repõe os timestamps a seguir); ambos ficam com a mesma duração ao milissegundo — reprodutível: correr o `build.sh` outra vez sobre o mesmo `cuts.yaml` dá ficheiros idênticos.

A verificação final do `build.sh` mede LUFS e true peak de cada WAV e falha se saírem fora da tolerância (±1 LU / até -1,2 dBTP) — não basta o container e o codec estarem certos.

## Escrita atómica

O `build.sh` gera os 12 ficheiros numa pasta de staging ao lado do destino final (`<destino>.build-<pid>`) e só promove (`mv`) para `game/resources/videos/pt/` e `game/resources/audio_for_videos/pt/` depois de o conjunto inteiro passar a verificação. Uma falha a meio nunca deixa clips novos misturados com antigos, nem um par vídeo/áudio dessincronizado — os ficheiros de produção só mudam quando tudo está confirmado.

## Loop com crossfade

Um clip marcado `loop: true` em `cuts.yaml` (ex.: `attract_demo`) recebe automaticamente crossfades de vídeo e áudio (`xfade` e `afade` + `amix`, ~0,8 s — ver `LOOP_CROSSFADE_FRAMES` no `build.sh`) que cruzam o fim do clip com o início, para o ciclo fechar sem salto quando o jogo repete os ficheiros. A janela acrescentada é totalmente sobreposta, por isso o AVI e o WAV conservam a duração original. O `build.sh` mede e mostra o YAVG (luminância média) do primeiro e do último frame depois do crossfade, para se perceber se as duas pontas ficaram próximas. Se o material das duas pontas for muito diferente, o crossfade aproxima mas pode não eliminar o salto — isso fica visível nos números, não é uma falha do script.

## Atenção aos nomes

Os nomes estão hardcoded em `game/tv_show/tv_show_resources.py` e não podem mudar:

`attract_demo`, `hello_hello`, `press_5`, `scylla_cave`, `you_lost`, `have_luck`.

Cada nome tem de produzir um `.avi` em `game/resources/videos/pt/` e um `.wav` em `game/resources/audio_for_videos/pt/`. O AVI não pode ter áudio: o jogo toca sempre o WAV separado através do audio-server.
