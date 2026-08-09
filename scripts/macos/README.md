# hugo-re em macOS (Apple Silicon)

Scripts para pôr o `hugo-re` a arrancar num Mac arm64. O upstream só tem
scripts Linux-only (ALSA, systemd, `/dev/uinput`) em `scripts/`, por isso
estes ficam à parte, em `scripts/macos/`.

Máquina de referência: Darwin 25.5.0, arm64.

## Antes de mais: python correto

Este projeto usa **sempre** `/opt/homebrew/bin/python3.13` (arm64). Nunca
`/usr/local/bin/python3` — esse é um build x86_64 que rebenta com erros
`posix_spawnp` num Mac Apple Silicon. Os scripts abaixo já apontam para o
sítio certo; não precisas de te preocupares com isto no dia-a-dia, só se
algo mais no repo apontar para o python errado.

## Ordem de arranque no dia do evento

1. **Uma vez, com antecedência** (não precisa de repetir todos os dias, é
   idempotente):
   ```
   scripts/macos/setup.sh
   ```
   Cria o `.venv` na raiz do repo e instala as dependências do jogo e do
   audio-server.

2. **No dia, antes de ligar tudo**, corre a verificação:
   ```
   export HUGO_ASSETS=/caminho/para/BigFile
   scripts/macos/check.sh
   ```
   Confirma que o python é arm64, que os 7 imports funcionam, que o
   `ffmpeg` está no PATH, e que a pasta de assets existe. Sai com código
   != 0 se faltar algo essencial (ver secção de riscos abaixo — **neste
   momento falha por causa do `pyvidplayer2`**).

3. **Arranca o audio-server** (uma janela de terminal, fica a correr):
   ```
   scripts/macos/run-audio.sh "$HUGO_ASSETS"
   ```
   Uma só instância, porta 9001, som pela saída default do Mac.

4. **Arranca o jogo** (outra janela de terminal):
   ```
   scripts/macos/run-game.sh "$HUGO_ASSETS"
   ```

Todos os scripts aceitam a pasta de dados por `$HUGO_ASSETS` ou por
primeiro argumento posicional. Se não a passares, o script para logo com
uma mensagem clara — não tentes correr sem ela, ainda não foi descarregada
(outra pessoa trata disso em paralelo).

## O que cada script faz

- **`setup.sh`** — cria `.venv` com `/opt/homebrew/bin/python3.13 -m venv`
  e instala `game/requirements.txt` + `audio-server/requirements.txt`. Se
  o `.venv` já existir, não o recria — verifica que é arm64 e reinstala as
  dependências por cima (idempotente, não rebenta).
- **`run-audio.sh`** — arranca uma única instância do audio-server na
  porta 9001, `--host 0.0.0.0`, saída de áudio default do Mac. Não passa
  `--sinks`, ver "Porquê sem `--sinks`" abaixo.
- **`run-game.sh`** — faz `cd` para `game/` (o cwd correto, ver secção
  seguinte) e corre `game.py <pasta de dados>`.
- **`check.sh`** — verificação corrível e sem efeitos secundários. Podes
  correr quantas vezes quiseres.

## O cwd correto para o jogo — o que descobri

`game/resource.py` e a maior parte do jogo (ex.: `game/game.py`) carregam
recursos com caminhos relativos como `"resources/images/loading.png"`.
Isto só resolve com **cwd = `game/`**. Confirmei correndo, a partir de
`game/`:

```python
os.path.isdir('resources/videos/ar')       # True
os.path.isdir('audio_for_videos/ar')       # False
os.path.isdir('resources/audio_for_videos/ar')  # True
```

Ou seja: `cwd = game/` é o correto e é o que `run-game.sh` usa — é o único
cwd em que os `pygame.image.load("resources/images/...")` do arranque
(chamados logo nas primeiras linhas de `game.py`) e o
`prefix = "resources/videos/{country}/"` de
`game/tv_show/tv_show_resources.py:30` resolvem.

**Mas há um bug no upstream que este cwd não resolve** (não é um problema
dos scripts — é código dentro de `game/`, que este ticket não tocou):
`tv_show_resources.py:31` monta o prefixo do áudio como
`audio_prefix = f"audio_for_videos/{country}/"`, sem o `resources/` que o
`prefix` dos vídeos tem por cima. Os ficheiros `.wav` estão de facto em
`game/resources/audio_for_videos/<país>/`, não em `game/audio_for_videos/`.
Não há nenhum cwd único onde ambos os caminhos relativos resolvam ao mesmo
tempo — confirmei correndo o teste acima a partir de `game/resources/`
também (aí é o `resources/videos/...` que deixa de resolver). Efeito
prático: os vídeos do tv_show tocam, mas o áudio desses vídeos (attract,
initial, press_5, going_scylla, ending, have_luck) não. Isto é algo para
reportar a quem mexe em `game/`, não para os scripts macOS tentarem
contornar.

## Porquê sem `--sinks`

Decisão de produto: uma só instância, porta 9001, saída default do Mac,
sem sinks virtuais nem BlackHole. O audio-server já cai automaticamente na
saída default sempre que o nome do sink não corresponde a nenhum
dispositivo PortAudio real (`audio-server/audio_server.py:351-356`, usa
`device=None` quando não encontra o dispositivo). Como o `--sinks` default
(`virtual_sink_0`) nunca vai corresponder a um nome de dispositivo real
num Mac, não passamos `--sinks` de todo — o fallback para a saída default
já faz exatamente o que queremos, sem termos de inventar um nome de sink
falso.

Nota: o README do audio-server (`audio-server/README.md`) descreve
`--port` (singular). Está desatualizado — o código só aceita `--ports`
(plural, lista separada por vírgulas). Os scripts aqui seguem o código.

## Teclas dos 4 jogadores (fallback de teclado em palco)

De `game/config.py:18-31`. Cada jogador tem o próprio bloco de teclas — não
são alternativas para a mesma ação, cada coluna é o teclado de um jogador.

| Ação | Jogador 1 (azul) | Jogador 2 (verde) | Jogador 3 (vermelho) | Jogador 4 (branco) |
|---|---|---|---|---|
| Telefone descaído (atender) | F1 | F3 | F5 | F7 |
| Telefone pousado (desligar) | F2 | F4 | F6 | F8 |
| Dígito 1 | 1 | 4 | 7 | Num 1 |
| Dígito 2 | 2 | 5 | 8 | Num 2 |
| Dígito 3 | 3 | 6 | 9 | Num 3 |
| Dígito 4 | q | r | u | Num 4 |
| Dígito 5 | w | t | i | Num 5 |
| Dígito 6 | e | y | o | Num 6 |
| Dígito 7 | a | f | j | Num 7 |
| Dígito 8 | s | g | k | Num 8 |
| Dígito 9 | d | h | l | Num 9 |
| Dígito 0 | z | x | c | Num 0 |

Sair do jogo: **F12** (todos os jogadores).

(Confere com o bloco "123 / qwe / asd / z" do jogador 1 em
`game/README.md` — é a mesma coisa, só que aqui em tabela e com os 4
jogadores lado a lado.)

## Ambiente instalado

- Python: `/opt/homebrew/bin/python3.13` → 3.13.14, arm64. Confirmado com
  `platform.machine()` → `arm64`.
- `.venv` na raiz do repo (`hugo-re/.venv`).
- `ffmpeg` 7.1.1 em `/usr/local/bin/ffmpeg` (fora do venv, é dependência de
  sistema do `pyvidplayer2`/`opencv-python`, já estava instalado).

### `pip freeze` do `.venv`

```
cffi==2.1.1
glcontext==3.0.0
moderngl==5.12.0
numpy==2.5.1
opencv-python==5.0.0.93
pycparser==3.0
pygame==2.6.1
pyvidplayer2==0.9.36
scipy==1.18.0
sounddevice==0.5.5
soundfile==0.14.0
typing_extensions==4.16.0
```

`opencv-python`, `glcontext`, `cffi`, `pycparser` e `typing_extensions` são
dependências transitivas (do `pyvidplayer2` e do `sounddevice`), não vêm
diretamente dos `requirements.txt` do upstream.

## RISCO Nº1: `pyvidplayer2` não importa nesta máquina (arm64 + Python 3.13)

**O pacote instala sem problemas** (`pip install` corre limpo, é uma wheel
pura Python). **Mas importar falha**, e importa porque quem importa é o
próprio `pyvidplayer2/__init__.py`, não código nosso:

```
File ".../pyvidplayer2/__init__.py", line 63, in <module>
    from .video_tkinter import VideoTkinter
File ".../pyvidplayer2/video_tkinter.py", line 1, in <module>
    import tkinter as tk
File ".../python3.13/tkinter/__init__.py", line 38, in <module>
    import _tkinter
ModuleNotFoundError: No module named '_tkinter'
```

**Causa:** o Homebrew separa o Python dos bindings Tcl/Tk. O
`/opt/homebrew/bin/python3.13` tem o pacote `tkinter` (ficheiros `.py`),
mas não tem a extensão C `_tkinter` porque a fórmula `python-tk@3.13` (que
a traz) não está instalada. O `pyvidplayer2` faz
`importlib.util.find_spec("tkinter")` para decidir se importa
`VideoTkinter` — isso encontra o pacote (existe no disco) mas rebenta a
importar de verdade, porque a extensão C não está lá. Isto acontece **só
por importar `pyvidplayer2`**, mesmo que o jogo só use a classe `Video`
(não usa `VideoTkinter`) — o import de topo do pacote já falha antes de lá
chegar.

**Isto bloqueia o jogo por completo nesta máquina**: `game/game.py` faz
`from tv_show.tv_show_resources import TvShowResources`, que faz
`from pyvidplayer2 import Video`, que dispara o crash acima. `run-game.sh`
vai falhar com este erro até isto ficar resolvido.

**Alternativas que existem (nenhuma foi aplicada — fora do que este
ticket pode tocar):**

1. `brew install python-tk@3.13` — instala os bindings Tcl/Tk certos para
   este Python exato. É a correção óbvia, mas é `brew install` fora do
   venv, no sistema — proibido pelas regras deste ticket. Só quem decide
   sobre a máquina o pode fazer.
2. Downgrade/pin de `pyvidplayer2` a uma versão sem esta importação
   incondicional — não confirmei se existe alguma; teria de se investigar
   o histórico do pacote no PyPI/GitHub.
3. "Enganar" o `find_spec("tkinter")` em runtime (ex.: meta path finder a
   fingir que `tkinter` não existe, antes do import) — falso-positivo
   arriscado, não resolve nada de raiz, e mistura-se com código do jogo
   que este ticket não deve tocar. Não fiz isto.
4. Trocar de interpretador para um que já traga Tcl/Tk embutido (ex. pyenv
   com `--with-tcltk`) — muda o python fixado por este ticket
   (`/opt/homebrew/bin/python3.13`), fora de âmbito.

`check.sh` apanha isto e sai com código != 0 — não vai passar despercebido.

## `.venv` e o `.gitignore`

O `.gitignore` da raiz ignora `venv/`, `env/` e `ENV/`, mas **não**
`.venv/` — confirmei com `git check-ignore -v .venv`, sem output nenhum,
ou seja o `.gitignore` da raiz não o apanha. Na prática isto não é
problema: `python -m venv` cria sozinho um `.venv/.gitignore` com um `*`
lá dentro, e é esse ficheiro (não o da raiz) que faz o git ignorar tudo o
que está dentro do `.venv` (confirmei com `git status --short`, o `.venv`
não aparece como untracked). Como este ticket não pode editar o
`.gitignore` da raiz, fica só registado: se algum dia esse
`.venv/.gitignore` desaparecer (ex.: recriares o venv com outra
ferramenta que não o `venv` da stdlib), o `.venv` passa a aparecer em
`git status` e é preciso ignorá-lo à mão.
