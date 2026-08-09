# Foreman Ledger — hugo-bridge (Revenge of the 90s, 12 set 2026)

**Run started:** 2026-08-09
**Repo:** `/Users/mac/Claude code/hugo-re` (fork `rebelpaulo/hugo-re`, upstream `gzalo/hugo-re`)
**Baseline commit:** `617e322` (upstream/main @ 2026-07-31)
**Branch:** `ns-bridge`
**Spec:** `/Users/mac/Downloads/hugo/PRD-hugo-bridge.md`
**Mode:** Codex-boosted (Agent tool + real shell + Codex CLI 0.144.4, standing consent 2026-07-14)

## Environment facts (probed 2026-08-09)

| Fact | Value |
|---|---|
| Arch | arm64 (Apple Silicon) |
| Python (arm64) | `/opt/homebrew/bin/python3.13` — 3.13.14 — **use this one** |
| Python (AVOID) | `/usr/local/bin/python3` — 3.11.6 — **x86_64, will crash** |
| ffmpeg | `/usr/local/bin/ffmpeg` 7.1.1 |
| yt-dlp | `/usr/local/bin/yt-dlp` 2026.07.04 |
| Docker | **NOT INSTALLED** → B3 (SIP) blocked until Docker Desktop is installed |
| gh | authenticated as `rebelpaulo` |
| Upstream licence | MIT (fork OK) |

## Roadmap → tasks

| ID | Block | Scope | Status |
|---|---|---|---|
| T0 | B0 | Fork + branch + scout | DONE |
| T1 | B0 | Backup assets (gold version, sprites, PT master) | PENDING |
| T2 | B0 | `tools/pt-assets/` (cuts.yaml, build.sh, preview.sh) + 6 clips PT | PENDING |
| T3 | B0 | Jogo a correr no Mac com teclado, 4 jogadores, arm64 venv | PENDING |
| T4 | B0 | audio-server 1 instância :9001 + validar cacofonia do attract | PENDING |
| T5 | B1 | `game/udp_input.py` + 4 patches no `game.py` | PENDING |
| T6 | B1 | patch `pos_by_country` → indexar por índice de jogador | PENDING |
| T7 | B1 | `bridge/` core: emitter, slot_manager, main, config | PENDING |
| T8 | B2 | webapp retro + web_adapter (WS) + lobby/fila | PENDING |
| T9 | B2 | QR overlay nos quadrantes vazios (bridge→jogo, msg `slots`) | PENDING |
| T10 | B3 | Docker + Asterisk + ari_adapter | BLOCKED (no Docker) |
| T11 | B4 | Reconnect, timeouts, logs, script de arranque único | PENDING |
| T12 | B5 | Ensaio geral | HUMAN |

## Attempts (append-only)

| # | Task | Seat | Ticket | Status | Evidence | Notes |
|---|---|---|---|---|---|---|
| 1 | T0 | LEAD | inline | DONE | fork+clone+branch `ns-bridge` @ 617e322 | remotes origin+upstream OK |
| 2 | T0 | scout/sonnet | inline | DONE | fact sheet: game loop, pos_by_country, quadrantes | ver "Achados" abaixo |
| 3 | T0 | scout/sonnet | inline | DONE | fact sheet: assets, audio, attract | ver "Achados" abaixo |
| 4 | T1 | worker/sonnet | inline | DISPATCHED | — | aquisição de assets |
| 5 | T2 | worker/codex `gpt-5.6-sol` | `.foreman/scratch/ticket-B-pt-assets.md` | DISPATCHED | job `brawt3ar8` → `.foreman/scratch/out-B.txt` | 1º despacho Codex desta run; billing = subscrição ChatGPT |
| 6 | T3 | worker/sonnet | inline | DONE_WITH_CONCERNS | venv arm64 OK; `pyvidplayer2` falhou import | ver T3b |
| 7 | T1b | LEAD | inline | DONE | gold version descarregada via Chrome do utilizador, extraída p/ `hugo-assets/gold/` (BigFile 259 MB) | sha256 `17da5d6b…1b01f`, RAR v5, extraído com `bsdtar` |
| 8 | T3b | LEAD | inline | DONE | `brew install python-tk@3.13`; `from pyvidplayer2 import Video` → OK | autorizado pelo utilizador |
| 9 | T1c | Explore/sonnet | inline | DISPATCHED | — | caça aos sprites originais (DeviantArt/AsuharaMoon) |
| 10 | T3c | worker/codex `gpt-5.6-sol` | `.foreman/scratch/ticket-D-scoreboard-guard.md` | DISPATCHED | job `bva3ta01s` → `.foreman/scratch/out-D.txt` | guard de degradação do scoreboard |

## Decisões do utilizador (2026-08-09)

| Tema | Decisão |
|---|---|
| Gold version | Descarregada pelo Chrome do utilizador (autorizou explicitamente). Feito. |
| Sprites do scoreboard | Patch de degradação **+** caçar o original em paralelo. |
| `_tkinter` em falta | `brew install python-tk@3.13`. Feito, import verificado. |

## Correções a relatórios de workers (verificadas pelo LEAD)

- **Falso positivo do worker T3.** Reportou como bug que
  `game/tv_show/tv_show_resources.py:31` (`audio_prefix`) não tem o prefixo
  `resources/` que o `prefix` de vídeo (linha 30) tem. **Não é bug.** A linha 41-45
  guarda uma *string* que viaja por UDP até ao audio-server; é o audio-server que a
  resolve, contra `--assets` e depois `--resources` (`audio-server/audio_server.py:239-244`).
  Com `--resources ../game/resources` resolve certo. Os dois prefixos são assimétricos
  porque são resolvidos por **processos diferentes**. Não tocar.

## Achados do B0 que mudam o plano do B1 (medidos, não inferidos)

### A1 — Bug de macOS no upstream: o jogo nunca arrancou num Mac

`game/game.py:47-48` chamava `pygame.display.gl_set_attribute()` no **corpo da classe**
(tempo de import), mas o `pygame.init()` só acontece na linha 53, dentro de `run()`.
No Linux o ramo `platform.system() == "Darwin"` nunca corre, por isso ninguém deu por
isto. Em macOS o módulo não chega a importar: `pygame.error: video system not initialized`.

Reproduzido duas vezes (sandbox do Codex e sessão normal). **Contradiz o PRD §6ter**, que
afirma "o autor testou em Mac". Não testou.

Corrigido: o `gl_set_attribute` passou para dentro do `run()`, a seguir ao `pygame.init()`
e antes do `set_mode()`. A substituição dos shaders fica onde estava. Diff de 7 linhas.
Depois disto o jogo arranca, renderiza os 4 quadrantes e sobrevive >2 min a 16% de CPU.

**Candidato a PR para o upstream** (PRD §9.3 fala em contribuir de volta).

### A2 — `COUNTRIES = ["pt"]*4` não funciona. O `pos_by_country` é a menor das avarias.

Todos os recursos de tv_show são dicionários **indexados por país**
(`game/tv_show/tv_show_resources.py:33-45`). Com quatro entradas iguais, as chaves colidem
e os 4 quadrantes passam a **partilhar o mesmo objeto `Video`**
(`game/tv_show/attract.py:10` → `TvShowResources.videos_attract[context.country]`).

Consequências, por ordem de gravidade:

1. `VideoState.on_exit` (`video_state.py:32`) faz `self.video.stop()`. Quando **um**
   jogador descolga e sai do attract, **para o vídeo de attract nos outros três
   quadrantes**. Visível, garantido, em palco.
2. `on_enter` faz `video.restart()` no objeto partilhado — cada entrada rebobina os
   outros quadrantes.
3. `pos_by_country` (`game.py:95`) colide → ataques desenhados na janela errada.
4. Filtro de alvos (`game.py:157`) `tv_show.country != current_country` → com 4 países
   iguais a lista de alvos fica **vazia**; o sistema de ataques morre em silêncio.

**Recomendação para o B1 (diff muito menor do que o do PRD):** não desmontar os
dicionários. Dar a cada jogador uma **chave distinta** e acrescentar um mapeamento
chave → pasta de assets, de modo a que as quatro chaves resolvam para `pt`. Assim:
os 4 `Video` voltam a ser objetos independentes; `pos_by_country` tem 4 chaves;
`country_to_port` manda os 4 para 9001 (via o `.get(k, 9001)` que já existe); e o filtro
de alvos volta a funcionar porque as chaves diferem. Uma alteração, quatro avarias
resolvidas.

### A3 — O audio-server em baixo **congela o loop de render**, 1 s por som

`game/audio_helper.py:24` faz `self.sock.settimeout(1.0)` e fica à espera de resposta
**no fio principal**. Medido com uma sonda UDP na porta 9001 sem servidor a responder:
os 4 pedidos de attract chegaram a **exatamente 1,00 / 1,01 / 1,00 s de intervalo** — ou
seja, um segundo de loop bloqueado por cada som pedido.

Ao vivo isto significa: se o audio-server morrer, o jogo não fica só mudo — fica aos
soluços, com um congelamento de 1 s por cada efeito sonoro. É um modo de falha silencioso,
porque ninguém testa com o audio-server desligado. **Endurecer no B4** (fire-and-forget,
ou timeout curtíssimo). Cuidado: a resposta traz o `instance_id` que o `stop()` usa.

### A4 — Cacofonia do attract: confirmada, mas menor do que se temia

Com os 4 quadrantes no mesmo país, o arranque dispara 4 pedidos do mesmo
`attract_demo.wav` desfasados ~1 s (que é o bloqueio do A3, não o desenho do jogo).
Depois estabiliza em **1 pedido por ciclo de ~17,7 s**, não 4 — porque o objeto `Video`
partilhado (A2) só dispara um `restart`. Assim que o A2 for corrigido e os 4 vídeos forem
independentes, esperam-se **4 loops verdadeiramente desfasados** e aí a cacofonia é real.
Reavaliar depois do patch do B1. Mitigação preferida do PRD (attract a volume 0) continua
válida.

## Decisão de arquitetura de rede (2026-08-09) — altera um não-objetivo do PRD

O PRD §1 diz "não expor nada à internet pública". **Revogado para a via QR**, com base em
investigação com fontes. O Paulo decidiu: **túnel + local em paralelo**, e adiar o domínio
(quick tunnel nos ensaios, domínio fixo antes do B5).

### Porque é que só-LAN não serve para a via QR

- Nenhum QR faz Wi-Fi + URL num scan. O formato `WIFI:S:...` é convenção do ZXing (iOS 11+,
  Android 10+) e acaba na ligação à rede. São sempre ≥2 gestos.
- **O telemóvel foge da rede.** Android sonda conectividade e aplica `avoid bad wifi`
  (AOSP, `NETWORK_AVOID_BAD_WIFI`); iOS tem Wi-Fi Assist. Numa rede sem internet, o tráfego
  é encaminhado para os dados móveis — e o "manter ligado" **não é durável**, o SO reavalia.
  Mata o WebSocket a meio do jogo.
- `.local` (mDNS) só resolve em Android 12+. Usar IP.
- Captive portal: o CNA da Apple é limitado (900x572, sem barra de endereços, sem
  persistência de cookies) — não serve para correr a webapp.
- Um AP doméstico não chega para centenas (design de alta densidade: Cisco/Meraki, Netgear).

### Porque é que o túnel resolve

- Cloudflare Tunnel suporta WebSocket sem configuração extra (doc oficial), sem tecto de
  largura de banda documentado, e ligação **de saída** — sem port forwarding.
- Elimina o conteúdo misto de raiz: o telemóvel só fala com um host HTTPS público, nunca
  com o IP privado. Também contorna o pedido de permissão de rede local do Chrome 142.
- O público joga pelos **próprios dados móveis** — um scan, sem trocar de rede.

### Ressalvas registadas

- Quick tunnels (`trycloudflare.com`) dão URL **aleatório** a cada arranque — servem para
  ensaios, não para o QR final. Hostname fixo exige domínio com DNS na Cloudflare (~10 €/ano).
- **Não reiniciar o `cloudflared` durante o evento** — derruba as ligações WS abertas
  (doc oficial).
- ngrok descartado: tecto de 1 GB/mês no plano grátis. Estimativa de ~430 MB para 2 h com
  50 jogadores; os ensaios comem da mesma quota.
- Uplink do local passa a ser ponto único de falha para a via QR → **hotspot 4G/5G
  dedicado como failover**, e a via local fica como plano B.
- SIP não é afetado: os telefones falam com o Asterisk na LAN, sem internet.

### Confirmado: nenhuma API da webapp exige HTTPS

`navigator.vibrate()` (exige só ativação do utilizador), Web Audio, `requestFullscreen()` e
`screen.orientation.lock()` **não** estão na lista de features restritas a contexto seguro
do MDN. Só um Service Worker exigiria HTTPS — e não precisamos de um. Por isso o servidor
local em `http://` é um plano B funcional, não um consolo.

## Revisão do PR #1 — 17 achados (FAIL)

CodeRabbit ficou rate-limited (41 min) e continuou rate-limited depois do toque → pela regra
do CLAUDE.md global, a revisão passou para o Codex. Duas fontes: o conector do Codex no
GitHub (3 achados) e uma revisão local adversarial (17 achados, superset).

Distribuídos por três workers com write sets disjuntos:

| Frente | Achados | Seat | Estado |
|---|---|---|---|
| F1 `game/` — pontuação ao saltar o scoreboard | 1 bloqueante | worker/sonnet | **DONE** — 2150=2150 e 1950=1950 provados |
| F2 `tools/pt-assets/` — reprodutibilidade, loudness, escrita atómica, loop do attract, caminhos, ffmpeg | 1 bloqueante + 5 | worker/sonnet | a correr |
| F3 `scripts/macos/` — portas, sinks, prontidão, bind 0.0.0.0, caminho relativo, check.sh, setup.sh, README falso | 7 maiores + 2 menores | worker/codex | a correr |

Achado 17 (o ledger versionado no PR): **decisão de manter**. É o registo de decisões do
projeto e sobrevive a compactação, que é o que o CLAUDE.md do workspace quer. Contém
caminhos locais, mas o fork é privado.

## Incidente de orquestração (2026-08-09) — write sets sobrepostos

O worker F1 (`game/` scoreboard) viu `press_5.avi` e `hello_hello.wav` a 0 bytes, concluiu
que o jogo os tinha truncado, e fez `git checkout --` nesses ficheiros. Não era verdade:
eram ficheiros a meio de serem escritos pelo `ffmpeg` do worker F2, que corria em paralelo
na mesma pasta. O F1 saiu do seu write set e reverteu trabalho do F2.

Sem dano final — o F2 ainda estava na fase de build e reconstrói os 12 do zero com
verificação no fim, portanto ganha a corrida. **Causa: eu dei ao F1 um write set
(`game/**`) que se tocava com o do F2 (`game/resources/{videos,audio_for_videos}/pt/`).**
Lição para o resto da run: write sets disjuntos ao nível da pasta, e proibição explícita de
`git checkout` a workers.

## Riscos abertos

| Risco | Onde | Nota |
|---|---|---|
| `libSDL2` duplicado (cv2 vs pygame) | `.venv` | O runtime avisa: "may cause spurious casting failures and mysterious crashes". `opencv-python` vem por arrasto do `pyvidplayer2`. Endereçar no B4. |
| Sprites do scoreboard perdidos | `game/resources/scores/` | Sem fonte conhecida. Mitigado pelo guard (T3c). |
| Docker não instalado | máquina | B3 (SIP) bloqueado. Prazo 3 set. |
| PyYAML não está no venv | `.venv` | `tools/pt-assets/build.sh` precisa dele; o script falha com mensagem clara. Juntar ao `setup.sh`. |

## Consentimento Codex

Registado 2026-08-09: `codex login status` → **Logged in using ChatGPT** (subscrição,
não API key metered). Modelo configurado `gpt-5.6-sol`, effort `medium`. Consentimento
permanente do utilizador de 2026-07-14 aplica-se; anunciado ao utilizador no 1º despacho.

## Achados dos scouts (factos, com âncoras)

### Contradiz o PRD

1. **Os vídeos por país ESTÃO no repo.** PRD §4.2 / §6bis / armadilha nº7 dizem que
   não vêm nos assets. Vêm: 36 `.avi` em `game/resources/videos/{ar,cl,dn,fr}/` e
   24 `.wav` em `game/resources/audio_for_videos/{ar,cl,dn,fr}/`. Nada de assets está
   no `.gitignore`. Só faltam mesmo os sprites do scoreboard, o mp3 da música, e a
   pasta de dados da gold version.
2. **Specs de ffmpeg do PRD §6quater erradas.** Medido com ffprobe nos clips `ar`:
   vídeo `mjpeg` 320x240 25fps (PRD dizia `mpeg4`); áudio `pcm_s16le` **48000** Hz
   estéreo (PRD dizia 44100). Vídeo e áudio bit-exact na mesma duração por clip.
3. **`country_to_port` não está em `audio_helper.py`** — está em `game/game.py:93`.
   O `audio_helper.py` só conhece um `port: int`. E o audio-server recebe `--ports`
   (plural, lista), não `--port`; o README do upstream está desatualizado e o PRD
   copiou-o.

### Aumenta o âmbito do B1

4. **`pos_by_country` é pior do que o PRD descreve.** Não é só a colisão de chaves em
   `game/game.py:95`. O filtro de alvos em `game/game.py:157` é
   `tv_show.country != current_country`: com 4× `"pt"` a lista de alvos fica **vazia**
   e o sistema de ataques morre em silêncio, sem exceção. As tuplas de `attack` são
   produzidas em `game/game.py:154` e `:162` a carregar strings de país, e lidas em
   `:181-182`. O patch tem de passar tudo para índice de jogador, não só o dicionário.

### Factos úteis

- Loop principal: `game/game.py:100` `while running:`; `PhoneEvents` recriado em `:101`;
  `pygame.event.get()` em `:103-132`. Confirma o modelo edge-triggered do PRD §2.1.
- `PhoneEvents` (`game/phone_events.py:6-20`): `offhook`, `hungup`, `press_0..press_9`,
  `press_star`, `press_pound`, mais `any_set()` em `:22-38`.
  **`press_star` e `press_pound` são campos mortos** — não existe `Config.BTN_STAR`
  nem `BTN_POUND`, nada os põe a True hoje. O contrato UDP pode enviá-los, mas nada
  do jogo os consome ainda.
- Quadrantes: `positions` em `game/game.py:26-31` = (0,0) (320,0) (0,240) (320,240);
  `screens` 320x240 em `:84`; blit em `:164-165`; ícones de telefone em `:167-174`
  (é aqui que entra o overlay de QR do B2).
- Único argumento CLI: `sys.argv[1]` = pasta de dados, lido em `game/resource.py:8-11`.
  `game.py` não tem argparse.
- Não existe conceito de slot vazio / jogador ligado. Os 4 `tv_shows` são sempre
  instanciados para os 4 `COUNTRIES` (`game/game.py:93-94`).
- Attract é por país, não por quadrante (`game/tv_show/attract.py:8-14`,
  `video_state.py:21-27`). Hoje 4 países = 4 portas = sem colisão. **Com 4× `pt`,
  `country_to_port.get("pt", 9001)` manda os 4 para a porta 9001 — confirma-se tanto
  a instância única do PRD como o risco de cacofonia do attract.**
- Durações de referência (clips `ar`, para o `cuts.yaml`): attract_demo 16,41s ·
  hello_hello 6,21s · press_5 6,49s · scylla_cave 4,84s · you_lost 17,17s ·
  have_luck 2,41s.
- `game/resources/videos/sources.txt` lista as fontes YouTube dos 4 países existentes;
  o `README.md` da raiz linha 39 tem a fonte PT.
