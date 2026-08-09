# Bridge — núcleo de activação + servidor web

Este directório contém a parte comum às entradas web e SIP (`slot_manager.py`,
`emitter.py`) e, agora, o servidor HTTP/WebSocket que liga a webapp ao `SlotManager`
(`adapters/web_adapter.py`, `main.py`, `qr.py`) e o router de áudio que leva o som do
jogo ao telemóvel de cada jogador (`audio_router.py`). Não contém SIP nem integração
ARI — isso é o B3.

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
{"type":"slots","occupied":[0,2],"queue_len":5}
```

Uma falha de socket ou dados inválidos são registados, e os métodos do emissor devolvem
`False`; nunca propagam a excepção ao bridge.

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
paralelo). O `hello` é que dispara o `connect()` no `SlotManager` — a ligação em si não
pede lugar sozinha. Cada `Decision` devolvida é traduzida para a mensagem certa e
encaminhada para a sessão certa; uma oferta perdida sem confirmação (`offer_expired`)
volta automaticamente ao fim da fila, porque a webapp não tem mensagem própria para
pedir isso outra vez.

Heartbeat: sem `ping` do cliente durante 15s (`HEARTBEAT_TIMEOUT_SECONDS`, injectável em
`create_app` para testes), a sessão é fechada e o slot libertado via `disconnect()`.

O envio de `emitter.send_slots(...)` para o jogo já é feito pelo próprio `SlotManager`
sempre que a ocupação ou a fila mudam — o adaptador não precisa de código extra para
isso.

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
a webapp pré-carregar assim que o jogador escolhe "jogar aqui". Um recurso fora dessa
lista continua a ser servido na mesma, só que carregado tardiamente em vez de
antecipado.

**Do lado da webapp** (`webapp/game-audio.js`): o `AudioContext` só pode ser desbloqueado
por um gesto do utilizador (exigência do iOS) — aproveita-se o clique em "Jogar aqui no
telemóvel" (já existente em `phone.js`) para desbloquear e disparar o pré-carregamento.
Toca com `decodeAudioData` + `AudioBufferSourceNode`, com suporte a `loops` (repete um
buffer novo a cada fim, já que a Web Audio não tem "repete N vezes" nativo) e a `stop`
por `id`. Como o browser não expõe volume nem o interruptor de silêncio do telemóvel a
uma página, o aviso ao utilizador é necessariamente genérico (mostrado uma vez, depois
do som ficar pronto) — não há forma de detectar isso de verdade.

## Testes

A partir da raiz do repositório:

```sh
.venv/bin/python bridge/test_bridge.py         # núcleo: SlotManager + UdpEmitter
.venv/bin/python bridge/test_web_adapter.py    # servidor web: WebSocket a sério
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
