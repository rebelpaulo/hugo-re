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

Define primeiro a BigFile e valida todo o ambiente:

```sh
export HUGO_ASSETS=/caminho/para/BigFile
scripts/macos/check.sh
```

O check falha com código diferente de zero se faltar o Python correto, algum
import, `ffmpeg`, a variável/caminho de assets ou os diretórios sentinela da
BigFile. Os avisos escritos no stderr durante imports também ficam visíveis.

Depois, em dois terminais separados:

```sh
scripts/macos/run-audio.sh "$HUGO_ASSETS"
scripts/macos/run-game.sh "$HUGO_ASSETS"
```

Ambos aceitam a BigFile pelo primeiro argumento ou por `$HUGO_ASSETS`.

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
