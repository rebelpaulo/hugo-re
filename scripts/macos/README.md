# hugo-re em macOS (Apple Silicon)

Scripts para arrancar o `hugo-re` num Mac arm64. O upstream só tem scripts
Linux (ALSA, systemd, `/dev/uinput`) em `scripts/`, por isso estes ficam à
parte, em `scripts/macos/`.

## Pré-requisitos

- macOS em Apple Silicon (`arm64`).
- Python 3.13 arm64 do Homebrew em `/opt/homebrew/bin/python3.13`. Nunca usar
  `/usr/local/bin/python3`, que nesta máquina é um build x86_64.
- Bindings Tk para esse Python: `brew install python-tk@3.13`. O `_tkinter` é
  necessário porque o `pyvidplayer2` o importa durante o arranque.
- `ffmpeg` disponível no `PATH`.
- A pasta BigFile completa, incluindo `BoltData`, `ForestData`,
  `IceCavernData` e `MenuData`.

## Preparação

Com antecedência, corre:

```sh
scripts/macos/setup.sh
```

O script cria ou verifica o `.venv` arm64 na raiz do repo, confirma o
`_tkinter` e instala as versões fixadas em `requirements-lock.txt`.

## Ordem de arranque no dia do evento

No dia do evento, a forma mais simples é fazer duplo-clique em
`scripts/macos/Hugo.command` no Finder. Abre uma janela do Terminal, encontra
a BigFile em `~/Claude code/hugo-assets/gold/BigFile` (ou usa `$HUGO_ASSETS`),
corre o `doctor.sh` antes de arrancar e mostra o URL do lobby em letras grandes.
Se o doctor encontrar uma falta essencial, o lançador pára antes de abrir o
jogo; as duas FALHAs sobre jogo/bridge ainda não vivos são esperadas nessa
verificação pré-arranque.

Também o podes abrir a partir do Terminal com:

```sh
open scripts/macos/Hugo.command
```

Antes de mais, confirma `input_mode` em `bridge/config.yaml` consoante o que está montado
na sala **desta** activação — `web` (só webapp/QR) ou `sip` (só telefones físicos); os dois
nunca se cruzam no mesmo evento, e mudar isto não pede código, só reiniciar o bridge (ver
`bridge/README.md`).

Define depois a BigFile e valida todo o ambiente:

```sh
export HUGO_ASSETS=/caminho/para/BigFile
scripts/macos/check.sh
```

O check falha com código diferente de zero se faltar o Python correto, algum
import, `ffmpeg`, a variável/caminho de assets ou os diretórios sentinela da
BigFile. Os avisos escritos no stderr durante imports também ficam visíveis.

Depois, para correr o jogo e o bridge vigiados (recomendado — ver
`supervisor.sh` abaixo):

```sh
scripts/macos/supervisor.sh "$HUGO_ASSETS"
```

Ou, para correr as peças à mão em terminais separados (sem supervisão):

```sh
scripts/macos/run-game.sh "$HUGO_ASSETS"
.venv/bin/python bridge/main.py
```

Todos os scripts que pedem a BigFile aceitam-na pelo primeiro argumento ou
por `$HUGO_ASSETS`.

Antes de abrir as portas, confirma tudo numa passagem:

```sh
scripts/macos/doctor.sh "$HUGO_ASSETS"
```

## supervisor.sh — vigia o jogo e o bridge

```sh
scripts/macos/supervisor.sh "$HUGO_ASSETS"
```

Arranca o jogo e o bridge, e reinicia sozinho quem morrer a meio do evento.
Se o mesmo processo morrer 3 vezes em menos de 60 segundos, desiste — pára
tudo (incluindo o outro processo) e escreve uma mensagem clara no log, em vez
de reiniciar para sempre e mascarar um problema real de ambiente/config.

- Log com timestamps em `scripts/macos/logs/supervisor-<data>.log` (um
  ficheiro por sessão, nunca versionado — ver o `.gitignore` da pasta).
- Ctrl-C (ou `kill` ao processo) pára tudo de forma limpa: primeiro SIGTERM,
  e se o processo não sair em 5s (medido: acontece com o jogo/pygame),
  escala para SIGKILL. Isto funciona quer o sinal seja enviado só ao PID do
  supervisor (`kill -INT <pid>` ou `kill -TERM <pid>`), quer seja um Ctrl-C
  enviado ao grupo de processos. Nunca deixa processos nem portas presos.
- **Não** arranca o audio-server clássico (`run-audio.sh`) por omissão — a
  partir do B2 o bridge, em `audio.mode: devices`, já escuta ele próprio as
  portas 9001-9004 para encaminhar som para os telemóveis
  (`bridge/audio_router.py`). Arrancar os dois ao mesmo tempo faz um dos dois
  falhar a abrir a porta (testado nos dois sentidos — ver o comentário no
  topo do próprio `supervisor.sh`). Passa `--audio-pa` só se `bridge/config.yaml`
  estiver deliberadamente em `audio.mode: pa` (o modo de recurso, "se os
  altifalantes dos telemóveis falharem").

## doctor.sh — o que se corre às 20h antes de abrir as portas

```sh
scripts/macos/doctor.sh "$HUGO_ASSETS"
```

Uma passagem única por tudo o que interessa: `.venv`/Python, os 8 imports, a
ausência do `cv2`, `ffmpeg`, a BigFile, os 12 clips PT, os sprites do
scoreboard, as portas relevantes (8080, 9100, 9001-9004), se o bridge
responde, se o jogo está vivo, e o IP do lobby. `[ok]`/`[FALHA]` em cada
linha, sai != 0 se faltar algo essencial. Corre-se depois de o
`supervisor.sh` já ter arrancado tudo — antes disso é normal ver `[FALHA]`
em "bridge"/"jogo".

## Se algo ficar preso

Fecha primeiro o supervisor com Ctrl-C ou `kill -TERM <pid-do-supervisor>`.
Se, excepcionalmente, uma porta continuar ocupada, identifica o processo antes
de o terminar — não uses um `pkill -f` com um padrão ingénuo:

```sh
lsof -nP -iTCP:8080 -iUDP:9100 -iUDP:9001 -iUDP:9002 -iUDP:9003 -iUDP:9004
kill -TERM <pid>
sleep 5
kill -KILL <pid> # só se ainda estiver vivo
```

Confirma de novo com o mesmo `lsof` antes de voltar a arrancar.

## Comportamento dos scripts

- `run-audio.sh` arranca o audio-server apenas em `127.0.0.1`, nas portas
  9001 a 9004 usadas pelos quatro jogadores. Passa quatro sinks explícitos,
  todos com fallback para a saída default do Mac, e só anuncia sucesso depois
  de obter resposta UDP real de todas as portas. Depois do B1, a configuração
  colapsa para uma porta e um sink.
- `run-game.sh` converte a BigFile para caminho absoluto antes de mudar o cwd
  para `game/`. Esse cwd é necessário porque o jogo abre recursos por caminhos
  relativos como `resources/images/loading.png`.
- O `audio_prefix` do tv show é enviado por UDP e resolvido pelo audio-server
  relativamente ao diretório fornecido por `--resources`; não deve receber um
  prefixo `resources/` adicional.
- `setup.sh` instala o `.venv` com `--no-deps`, de propósito: sem isso o pip
  puxava o `opencv-python` como dependência do `pyvidplayer2`, e esse pacote
  traz o seu próprio `libSDL2` que colide com o do `pygame` (aviso `objc[...]
  Class SDLApplication is implemented in both ...`, risco real de crash a
  meio do jogo). Sem `cv2` instalado, o `pyvidplayer2` usa sozinho o
  `FFMPEGReader` para ler os `.avi` — confirmado a decodificar os 6 clips PT
  nos 4 quadrantes sem perda de funcionalidade. Ver o comentário no topo de
  `requirements-lock.txt`. `doctor.sh` falha alto se o `cv2` reaparecer.

## Teclas dos quatro jogadores

Num Mac, as teclas F só chegam ao jogo com «Usar F1, F2, etc. como teclas de
função padrão» ligado nas Definições do Sistema, ou carregando também em Fn.

| Ação | Jogador 1 | Jogador 2 | Jogador 3 | Jogador 4 |
|---|---|---|---|---|
| Atender | F1 | F3 | F5 | F7 |
| Desligar | F2 | F4 | F6 | F8 |
| Dígitos 1–3 | 1, 2, 3 | 4, 5, 6 | 7, 8, 9 | Num 1/V, Num 2/↑, Num 3/P |
| Dígitos 4–6 | q, w, e | r, t, y | u, i, o | Num 4/←, Num 5/M, Num 6/→ |
| Dígitos 7–9 | a, s, d | f, g, h | j, k, l | Num 7/vírgula, Num 8/↓, Num 9/N |
| Dígito 0 | z | x | c | Num 0/B |

Sair do jogo: F12.
