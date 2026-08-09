# Bridge — núcleo de activação

Este directório contém a parte comum às entradas web e SIP: atribui os quatro slots do
jogo, mantém a fila web e envia os eventos aceites por UDP. Não contém servidor HTTP,
WebSocket, SIP nem integração ARI.

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

## Testes

A partir da raiz do repositório:

```sh
.venv/bin/python bridge/test_bridge.py
```

Os testes usam um relógio falso, sem pausas reais. A prova ponta a ponta abre um socket
UDP local numa porta livre, envia ambos os formatos e compara o JSON recebido.
