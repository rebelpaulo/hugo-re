# Bridge — núcleo de activação + servidor web + SIP

Este directório contém a parte comum às entradas web e SIP (`slot_manager.py`,
`emitter.py`), o servidor HTTP/WebSocket que liga a webapp ao `SlotManager`
(`adapters/web_adapter.py`, `main.py`, `qr.py`), o router de áudio que leva o som do
jogo ao telemóvel de cada jogador (`audio_router.py`), e agora também os telefones
físicos: o adaptador SIP (`adapters/sip_adapter.py`) e a configuração do FreeSWITCH
que o alimenta (`freeswitch/`, ver `bridge/freeswitch/README.md`). Sem Docker, sem
Asterisk/ARI — FreeSWITCH nativo (Homebrew), decisão tomada e verificada antes deste
trabalho.

## Arrancar o bridge a sério

```sh
.venv/bin/python bridge/main.py
```

Isto lê `bridge/config.yaml`, cria o `UdpEmitter` e o `SlotManager`, gera o QR do lobby
uma vez (`game/resources/images/qr_lobby.png`) e arranca o servidor HTTP/WebSocket.
Imprime logo no arranque, bem visível, o URL do lobby com o IP real da máquina na LAN —
é isso que se aponta ao ecrã ou se mostra em QR. `SIGINT`/`SIGTERM` desligam tudo de
forma limpa (cancela o tick periódico, corre `end_match()`, fecha o servidor).

O servidor HTTP/WebSocket escuta deliberadamente em `0.0.0.0` (ver `config.yaml`) —
os telemóveis dos convidados têm de o alcançar pela Wi-Fi do evento. O emissor UDP para
o jogo continua sempre em `127.0.0.1`, nunca muda.

## `input_mode` — como é que as pessoas entram no jogo

Decisão da produção, em `config.yaml`, ligada **antes do evento** consoante o que está
montado na sala — nunca escolha do público, e os dois usos nunca se cruzam no mesmo
evento: ou é todo com a webapp, ou é todo com telefones físicos. Mudar aqui e reiniciar o
bridge é tudo o que é preciso; não é preciso mexer em código.

```yaml
input_mode: web   # web | sip
```

- `web` — só webapp. Quem lê o QR cai **direto** no teclado ou na fila, sem nenhum ecrã de
  escolha pelo meio.
- `sip` — só telefones físicos da sala. Não há QR nenhum no ecrã grande neste modo, logo
  ninguém devia sequer chegar à webapp; se alguém lá chegar à mesma (URL guardado de um
  evento anterior), vê só um aviso curto a dizer que hoje é por telefone.

Valor ausente ou inválido em `config.yaml` (incluindo o antigo `both`, que deixou de
existir) cai em `web` (o modo mais restrito para o público) e fica registado no log — ver
`load_input_mode()` em `adapters/web_adapter.py`.

O servidor manda o modo à webapp logo que o WebSocket liga, antes de qualquer outra coisa
(mensagem nova `{"type":"config","input_mode":"web"}`, ver secção do adaptador web abaixo)
— é assim que a webapp sabe se deve entrar na fila/teclado ou mostrar o aviso de sip, sem
ter de perguntar. O jogo também recebe o modo, na mensagem `slots` já enviada por UDP (ver
"Contrato UDP" abaixo) — é o que `game/invite_overlay.py` usa para desenhar o convite certo
num quadrante vazio: com QR em modo `web`, sem QR em modo `sip`.

## Arranque e configuração

As opções operacionais estão comentadas em `config.yaml`. O emissor e o gestor podem ser
criados a partir desse ficheiro:

```python
from bridge.emitter import UdpEmitter
from bridge.slot_manager import SlotManager

emitter = UdpEmitter.from_config("bridge/config.yaml")
manager = SlotManager.from_config("bridge/config.yaml", emitter)
```

O processo que integrar o gestor deve chamar `manager.tick()` regularmente (por exemplo,
uma vez por segundo) para aplicar os prazos mesmo quando não chegam eventos.

## Interface para B2 e B3

Cada ligação recebe um `source_id` único e estável. O tipo é `"web"` ou `"sip"`.

- `connect(source_id, source_type) -> list[Decision]`: regista e pede lugar.
- `request_slot(source_id) -> list[Decision]`: repete o pedido depois de perder uma oferta.
- `confirm(source_id) -> list[Decision]`: aceita uma oferta web dentro de 15 segundos.
- `handle_event(source_id, event) -> list[Decision]`: envia um evento válido ao jogo.
- `touch(source_id) -> list[Decision]`: renova actividade sem enviar nada ao jogo.
- `disconnect(source_id) -> list[Decision]`: liberta e remove a sessão.
- `tick() -> list[Decision]`: processa ofertas e inactividade expiradas.
- `end_match() -> list[Decision]`: limpa ocupantes, fila e esperas no fim da partida.
- `queue_status(source_id)` e `queue_snapshot()`: expõem posição e número de pessoas à
  frente para as sessões web em fila.

As decisões mais importantes são `assigned`, `queue_status`, `offer`, `waiting`,
`forwarded`, `ignored`, `released` e `offer_expired`. Cada chamada devolve todas as
decisões causadas, incluindo actualizações destinadas a outras sessões da fila. Em
alternativa, `on_decision` recebe cada decisão e permite ao adaptador encaminhá-la pelo
seu próprio transporte. Uma falha nesse callback é registada e contida.

Uma oferta reserva o slot até à confirmação ou ao fim do prazo. Um SIP que já esteja em
espera tem prioridade quando aparece a próxima vaga; nunca expulsa um ocupante. A espera
SIP não tem posição pública. `queue_len` conta apenas as sessões web ainda em FIFO, sem
contar ofertas já emitidas.

## Contrato UDP

São enviados datagramas JSON fire-and-forget para `127.0.0.1:9100` por omissão:

```json
{"player":0,"event":"press_5"}
{"type":"slots","occupied":[0,2],"queue_len":5,"mode":"web"}
```

Uma falha de socket ou dados inválidos são registados, e os métodos do emissor devolvem
`False`; nunca propagam a excepção ao bridge.

O campo `"mode"` (`input_mode` de `config.yaml`, ver secção acima) é acrescentado pelo
`main.py`, não pelo `emitter.py`/`slot_manager.py` — o `SlotManager` continua a chamar
`emitter.send_slots(occupied, queue_len)` exactamente como sempre chamou, sem saber nada de
modos. `main.py` usa um pequeno `_ModeStampedEmitter` (subclasse de `UdpEmitter` só nesse
ficheiro) que intercepta a serialização final e acrescenta `"mode"` só às mensagens
`slots`; `emitter.py` e `slot_manager.py` ficam intocados. Do lado do jogo,
`game/udp_input.py` aceita este campo com o mesmo rigor dos outros (só `"web"`/`"sip"`,
nunca booleano nem outro tipo) e assume `"web"` quando o campo não vem — quer porque o
bridge é anterior a esta mudança, quer porque ainda não chegou nenhuma mensagem `slots`
(bridge desligado): ver `game/invite_overlay.py`.

## O adaptador web (`adapters/web_adapter.py`)

Servidor aiohttp com estas rotas:

- `GET /` — serve `bridge/webapp/` estaticamente. Se a pasta ainda estiver vazia (sem
  `index.html`), mostra uma página mínima em vez de rebentar.
- `GET /qr.png` — devolve o PNG do QR do lobby gerado no arranque.
- `GET /ws` — WebSocket. Cada ligação recebe um `source_id` estável (UUID) só seu.
- `GET /audio-manifest.json` — lista de recursos para a webapp pré-carregar (só existe
  se `audio_config` for passado a `create_app`, ver secção seguinte).
- `GET /audio/<recurso>` — devolve o `.wav` do jogo já convertido para 16 bits/mono/
  44.1kHz, com cache em disco.

O contrato JSON de `/ws` é fixo (ver `bridge/webapp/`, feita por outro worker em
paralelo). Logo que a ligação prepara (`ws.prepare(request)`), antes de qualquer
mensagem do cliente, o servidor manda `{"type":"config","input_mode":"web"}` — a
webapp usa isto para decidir directo, sem perguntar (ver secção `input_mode` acima).
Só depois disso é que o `hello` dispara o `connect()` no `SlotManager` — a ligação em
si não pede lugar sozinha, e em `input_mode=sip` a webapp nem chega a mandar `hello`.
Cada `Decision` devolvida é traduzida para a mensagem certa e encaminhada para a sessão
certa; uma oferta perdida sem confirmação (`offer_expired`) volta automaticamente ao fim
da fila, porque a webapp não tem mensagem própria para pedir isso outra vez.

Heartbeat: sem `ping` do cliente durante 15s (`HEARTBEAT_TIMEOUT_SECONDS`, injectável em
`create_app` para testes), a sessão é fechada e o slot libertado via `disconnect()`.

O envio de `emitter.send_slots(...)` para o jogo já é feito pelo próprio `SlotManager`
sempre que a ocupação ou a fila mudam — o adaptador não precisa de código extra para
isso.

## O adaptador SIP (`adapters/sip_adapter.py`)

O equivalente do `WebBridge` do lado dos telefones físicos: liga-se ao Event Socket
(ESL) do FreeSWITCH por socket puro (`asyncio.open_connection`, biblioteca padrão —
sem `python-ESL`, ver o cabeçalho do próprio ficheiro para a justificação), subscreve
`CHANNEL_ANSWER`, `DTMF`, `CHANNEL_HANGUP_COMPLETE`, e traduz:

- chamada atendida → `connect(source_id, "sip")` + `handle_event(source_id, "offhook")`.
  `connect()` já pede lugar sozinho (chama `_request_slot` internamente); há também
  uma chamada a `request_slot()` a seguir, sempre um no-op nesse ponto, mantida só por
  simetria com o resto do adaptador.
- `DTMF` → `press_0`..`press_9`, `press_star`, `press_pound` (mesma tabela que o
  adaptador web).
- fim de chamada → `handle_event(source_id, "hungup")` + `disconnect(source_id)`.

**Identificação pelo destino, não pelo caller ID**: `source_id` é `sip:<extensão
marcada>` (`Caller-Destination-Number` do evento `CHANNEL_ANSWER`), não o caller ID —
que em chamada IP directa não é de fiar (pode vir vazio ou igual em todos os
telefones). Cada telefone físico tem de marcar um alvo distinto (ver
`bridge/freeswitch/README.md`); se dois colidirem ao mesmo tempo (configuração
errada), o adaptador desambigua com o UUID da chamada em vez de perder a segunda
linha em silêncio.

**Reconexão automática com backoff**: se o ESL cair (FreeSWITCH reiniciado, rede
abaixo), `run()` regista o erro, espera com backoff exponencial (1s, 2s, 4s... até
30s, a repetir) e tenta outra vez — para sempre, até `stop()`. Logo que reconecta,
`api show channels as json` sincroniza os dois lados nos dois sentidos: uma chamada
que o adaptador achava activa mas que já não existe no FreeSWITCH (desligou às
escuras) liberta o slot sozinha; uma chamada activa no FreeSWITCH que o adaptador
nunca viu atender (chegou e foi atendida enquanto o ESL estava em baixo) entra no
`SlotManager` mesmo assim, sem esperar por um evento que não vai voltar a chegar. É
isto que evita telefones "mortos em silêncio" depois de uma queda do ESL.

**Deduplicação**: não há lógica de deduplicação no adaptador — é toda do
`SlotManager` (`dedup_window_ms`, ver secção "Interface para B2 e B3" acima), que o
adaptador atravessa sem alterar. Prova (`bridge/test_sip_adapter.py`,
`test_dtmf_dedup_30ms_collapses_100ms_does_not`): dois `DTMF` iguais empurrados pelo
caminho real do adaptador a 30ms de intervalo contam como um; a 100ms contam como
dois.

### Prova de chamada real (baresip)

Sem telefone físico disponível (ver `bridge/freeswitch/README.md`), a prova foi feita
com [baresip](https://github.com/baresip/baresip) (Homebrew, arm64) como softphone
SIP a sério, contra um FreeSWITCH a sério com esta configuração, e o
`bridge/main.py` a sério em `input_mode: sip`:

1. `./scripts/macos/run-sip.sh` — FreeSWITCH pronto, 4 perfis `RUNNING`.
2. `bridge/main.py --config <cópia com input_mode: sip>` — liga ao ESL
   (`bridge.sip_adapter: ESL ligado a 127.0.0.1:8021`).
3. `baresip -f <perfil de teste> -e "/dial sip:9001@192.168.1.198"` — chamada
   IP directa a sério, sem registo.
4. Confirmado, com um socket UDP a fazer de "jogo" a escutar em `127.0.0.1:9100`
   (o mesmo endereço que `bridge/main.py` usa de verdade):
   - `{"type":"slots","occupied":[0],...,"mode":"sip"}` seguido de
     `{"player":0,"event":"offhook"}` — a chamada atendida chegou ao `SlotManager`,
     com o campo `mode` a confirmar que veio pelo caminho SIP.
   - Ao desligar a chamada (`fs_cli -x "uuid_kill <uuid>"`, já que o `-t` do baresip
     mata o processo sem BYE): `{"player":0,"event":"hungup"}` seguido de
     `{"type":"slots","occupied":[],...}`.
   - O evento `CHANNEL_ANSWER` visto no ESL trouxe `Caller-Destination-Number` igual
     ao número marcado (`9001`, `9002`, `9004`... consoante o teste) e
     `Caller-Caller-ID-Number` diferente — confirma a identificação pelo destino.
5. `apply-inbound-acl: domains` do perfil vanilla rejeitava toda a ligação
   (`sofia.c:10679 IP ... Rejected by acl "domains"`) — só descoberto e corrigido
   (para `localnet.auto`) por causa desta prova a sério; ver
   `bridge/freeswitch/README.md`.

**Honestidade sobre DTMF por áudio real**: enviar dígitos DTMF a sério através do
baresip, sem interface gráfica, não foi conseguido no tempo disponível — a interface
de controlo do baresip usada nos testes (`cons`/`ctrl_tcp` por TCP) não expôs um
comando de DTMF fiável para scriptar (só teclas interactivas, pensadas para um
utilizador humano a escrever ao vivo). A chamada real, o atender, e o desligar estão
provados ponta a ponta como descrito acima; a tradução de `DTMF` e a deduplicação a
30/100ms estão provadas com eventos ESL injectados a sério no `SipAdapter` real
(`bridge/test_sip_adapter.py`) — o `FakeEslServer` desse ficheiro fala o mesmo
protocolo de texto do FreeSWITCH por socket a sério, só o extremo de rede (o
FreeSWITCH em si) é que é substituído por um dobre determinístico, exactamente para
poder controlar o intervalo entre dígitos ao milissegundo, coisa que nem um telefone
real garante.

## Áudio: o som sai no telemóvel de cada jogador (`audio_router.py`)

O jogo já separa o áudio por jogador — `game/game.py` dá a cada `GameData` a sua porta
UDP (9001..9004, uma por quadrante) e `game/audio_helper.py` manda para lá comandos
`PLAY`/`STOP` em JSON, à espera de resposta no fio principal com `settimeout(1.0)`. Se
quem escuta nessas portas não responder, o jogo bloqueia até 1 segundo por som.

O `AudioRouter` ocupa essas portas em vez do `audio-server`, responde-lhe sempre de
imediato (como o `audio-server` faria: `{"instance_id": N}` / `{"success": true, ...}`)
e, em vez de tocar o som no Mac, manda à sessão WebSocket do jogador certo:

```json
{"type":"audio","action":"play","resource":"ForestData/speaks/005-01.wav","loops":0,"id":7}
{"type":"audio","action":"stop","id":7}
```

Sem sessão ligada para aquele jogador não é erro — o router responde ao jogo na mesma e
descarta a mensagem. A entrega ao WebSocket corre à parte da resposta UDP (nunca a
atrasa): ver `create_app(..., audio_config=...)` em `web_adapter.py`.

**Interruptor de recurso** (`audio.mode` em `config.yaml`): `devices` (normal) manda o
som para os telemóveis; `pa` volta ao comportamento antigo — reencaminha tudo, na
mesma forma, para o `audio-server` local (colunas do computador), com um timeout curto
(`pa_timeout_seconds`) para nunca deixar o jogo bloqueado mesmo que o `audio-server`
esteja em baixo. É o que salva o evento se os altifalantes dos telemóveis não chegarem.

**Conversão e cache**: `GET /audio/<recurso>` converte o `.wav` original (alguns são
`pcm_u8` a 22050Hz — nem todo o browser descodifica isso) para 16 bits/mono/44.1kHz com
`ffmpeg`, uma vez, para `audio.cache_dir`; pedidos seguintes servem directamente da
cache, mesmo depois de reiniciar o bridge.

**Manifesto de pré-carga** (`build_audio_manifest`): lê `game/forest/*.py` e
`game/cave/*.py` (só leitura) à procura de `load_speak`/`load_sfx`, e devolve a lista de
recursos que os dois minijogos implementados (Floresta e Caverna) realmente usam — para
a webapp pré-carregar assim que o `AudioContext` desbloqueia (ver abaixo). Um recurso
fora dessa lista continua a ser servido na mesma, só que carregado tardiamente em vez de
antecipado.

**Do lado da webapp** (`webapp/game-audio.js`): o `AudioContext` só pode ser desbloqueado
por um gesto do utilizador (exigência do iOS). Não há um botão fixo "Jogar aqui" desde que
o seletor de modo saiu do caminho normal — em vez disso, `phone.js` ouve o **primeiro**
toque ou tecla em qualquer ponto da página (`pointerdown`/`keydown`, uma vez só) e é isso
que chama `HugoAudio.start()`, desbloqueia o `AudioContext` e dispara o pré-carregamento.
Toca com `decodeAudioData` + `AudioBufferSourceNode`, com suporte a `loops` (repete um
buffer novo a cada fim, já que a Web Audio não tem "repete N vezes" nativo) e a `stop`
por `id`. Como o browser não expõe volume nem o interruptor de silêncio do telemóvel a
uma página, o aviso ao utilizador é necessariamente genérico (mostrado uma vez, depois
do som ficar pronto) — não há forma de detectar isso de verdade.

Prova de que o desbloqueio continua a funcionar sem aquele botão: `window.HugoAudio.state()`
(hook de depuração, mesmo espírito de `window.__dtmfDebug` em `dtmf.js`) devolve
`"not-created"` antes de qualquer gesto e `"running"` a seguir ao primeiro toque, mesmo com
`--autoplay-policy=user-gesture-required` no Chromium (a política mais estrita que existe
para isto).

## Testes

A partir da raiz do repositório:

```sh
.venv/bin/python bridge/test_bridge.py         # núcleo: SlotManager + UdpEmitter
.venv/bin/python bridge/test_web_adapter.py    # servidor web: WebSocket a sério
.venv/bin/python bridge/test_sip_adapter.py    # adaptador SIP: ESL a sério contra um FakeEslServer
.venv/bin/python bridge/test_audio_router.py   # router de áudio: UDP + WebSocket + HTTP
.venv/bin/python bridge/qr.py                  # auto-teste do gerador de QR
```

Os testes do núcleo usam um relógio falso, sem pausas reais. A prova ponta a ponta do
emissor abre um socket UDP local numa porta livre, envia ambos os formatos e compara o
JSON recebido.

Os testes do adaptador web ligam clientes WebSocket a sério (via aiohttp) a um servidor
aiohttp a sério, numa porta efémera de `127.0.0.1`, e um socket UDP local a sério faz de
"jogo". Confirmam: 6 ligações — as 4 primeiras ficam com slots distintos, as duas
seguintes ficam na fila (posições 1 e 2); um `press` chega ao "jogo" como
`{"player":N,"event":"press_5"}`; perder o heartbeat liberta o slot sozinho (usa um
`heartbeat_timeout` curto injectado só para o teste correr depressa, o valor de produção
continua a ser 15s).

**Nota sobre `input_mode`**: a mensagem `{"type":"config",...}` chega logo na ligação,
antes de qualquer resposta a `hello` (ver secção `input_mode` acima); `test_web_adapter.py`
já lê/ignora esse `config` inicial antes de verificar a resposta ao `hello` (ver
`resposta_util()` no próprio ficheiro).

Os testes do adaptador SIP (`test_sip_adapter.py`) falam ESL a sério (asyncio,
`127.0.0.1`, porta efémera) com um `FakeEslServer` local que implementa o mesmo
protocolo de texto do FreeSWITCH — cumprimento, `auth`, `event json`, `api show
channels as json` — e deixa o teste empurrar eventos como se viessem de uma chamada
real. Confirmam: uma chamada atendida entra pelo destino marcado (não pelo caller
ID) e gera `offhook`; dois destinos iguais em simultâneo não perdem a segunda linha;
`DTMF` mapeia para `press_N`/`press_star`/`press_pound`; a deduplicação a 30ms/100ms
do `SlotManager` atravessa o caminho real do adaptador sem alterações; desligar
liberta o slot; e uma queda do ESL a meio de uma chamada reconecta sozinha (com
backoff) e reconcilia o estado nos dois sentidos — ver "O adaptador SIP" acima. A
prova de uma chamada real com um softphone (fora do alcance de um teste corrível sem
FreeSWITCH instalado) está documentada em separado, na mesma secção.
