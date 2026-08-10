# FreeSWITCH — configuração do evento (B3, telefones físicos)

FreeSWITCH 1.11.1 nativo (Homebrew), sem Docker — decisão já tomada e verificada
antes deste trabalho (ver `handoff`/histórico do B1). Este directório versiona a
configuração que o aponta para a LAN do evento; a instalação Homebrew em
`/opt/homebrew/etc/freeswitch` nunca é editada à mão.

## Como apontar o FreeSWITCH para aqui

```sh
./scripts/macos/run-sip.sh
```

Isto constrói `bridge/freeswitch/conf/` (gerada, não versionada — ver
`build-conf.sh` abaixo) e arranca o FreeSWITCH com `-conf` apontado para lá,
com a mesma disciplina do `run-event.sh`: espera confirmada (pergunta ao ESL até
ele dizer "ready", não adivinha por tempo fixo), e limpeza garantida à saída
(Ctrl-C ou erro desligam o FreeSWITCH; se não desligar a tempo, força
`pkill -9`). Fica em primeiro plano.

Manualmente, o equivalente é:

```sh
./bridge/freeswitch/build-conf.sh
mkdir -p /tmp/fsdb /tmp/fslog
/opt/homebrew/bin/freeswitch -nf -nonat \
  -conf bridge/freeswitch/conf -log /tmp/fslog -db /tmp/fsdb
```

## O que é gerado vs. o que é nosso

- `overrides/` — os únicos ficheiros que escrevemos, versionados. Cada um tem
  no topo um comentário a dizer exactamente o que mudou em relação ao vanilla
  do Homebrew (procura "ALTERADO").
- `conf/` — gerado por `build-conf.sh` a cada arranque (`.gitignore` exclui-o).
  Uma "quinta de symlinks": tudo o que não mexemos aponta directamente para a
  instalação Homebrew (`brew --prefix freeswitch`), e os ficheiros de
  `overrides/` entram por cima, substituindo só o que precisa de ser
  diferente. O mesmo truque que o próprio Homebrew usa em
  `/opt/homebrew/etc/freeswitch -> Cellar`. Reproduzível: corre outra vez e
  sai sempre igual, em qualquer máquina com `brew install freeswitch` feito.

Ficheiros em `overrides/` (todos com o motivo da alteração no próprio ficheiro):

| Ficheiro | O que muda |
|---|---|
| `vars.xml` | `external_rtp_ip`/`external_sip_ip` deixam de vir de STUN (IP público, e uma chamada de rede a sério no arranque) e ficam presos a `$${local_ip_v4}`. |
| `sip_profiles/internal.xml` | `context` aponta para `hugo-lan` (era `public`, o IVR de demonstração); `auth-calls` fixo a `false`; `apply-inbound-acl` mudado de `domains` (negava tudo — sem utilizadores com `cidr=` no directory, a ACL ficava sempre vazia) para `localnet.auto` (a sub-rede local a sério). |
| `dialplan/hugo-lan.xml` | Novo contexto: atende e estaciona (`park`) qualquer chamada — ver "O dialplan" abaixo. |
| `autoload_configs/modules.conf.xml` | `mod_av` desactivado (módulo de vídeo, falha a carregar nesta máquina, não usamos vídeo). |
| `autoload_configs/event_socket.conf.xml` | `listen-ip` de `::` (todas as interfaces) para `127.0.0.1` — o ESL (password de fábrica `ClueCon`, dá para originar chamadas) não tem razão para estar acessível a partir da LAN dos convidados. |

## Decisão: chamada IP directa, sem registo

Os Yealink T30 fazem chamada IP directa de fábrica
(`features.direct_ip_call_enable=1`, confirmado na documentação oficial da
Yealink) — nada para aprovisionar no FreeSWITCH nem nos telefones. A
alternativa (registo) obrigava a: criar uma conta com password em
`directory/default/*.xml` por telefone, introduzir utilizador/password em
cada telefone à mão no dia do evento, e confiar que o registo não cai/expira
a meio de uma partida — mais peças móveis, mais coisas para falhar em palco,
por um ganho de segurança que uma LAN fechada de evento não precisa.

Com `auth-calls: false` no perfil `internal`, qualquer INVITE que chegue é
atendido sem desafio. Isto é aceitável exactamente porque:
- o perfil só está à escuta na interface da LAN do evento (`sip-ip` /
  `rtp-ip` = `$${local_ip_v4}`, não `0.0.0.0`) — quem não estiver fisicamente
  naquela rede não lhe chega;
- `apply-inbound-acl: localnet.auto` reforça isso ao nível da própria sub-rede,
  não só do interface de rede;
- o ESL (o canal que de facto poderia originar chamadas ou mais) está preso a
  `127.0.0.1` (ver tabela acima) — mesmo alguém na LAN não lhe chega.

Isto **não fecha a porta** a registo: os utilizadores de exemplo
(`1000`-`1019`) continuam no `directory/` vanilla (não tocado), por isso um
telefone que prefira registar-se com uma dessas contas (password
`default_password` do `vars.xml`, também não tocado) também funciona — só que
não é preciso para o evento.

## O dialplan

Um único contexto, `hugo-lan`, para onde o perfil `internal` manda tudo:

```xml
<extension name="atende-e-estaciona">
  <condition field="destination_number" expression="^(.*)$">
    <action application="answer"/>
    <action application="park"/>
  </condition>
</extension>
```

Atende e estaciona (`park`) — não faz mais nada de propósito. `park` segura o
canal indefinidamente sem tocar em áudio nenhum; é o suficiente para o
`bridge/adapters/sip_adapter.py` (ligado por ESL) ver `CHANNEL_ANSWER`, `DTMF`
e `CHANNEL_HANGUP_COMPLETE` e encaminhá-los ao `SlotManager`. O áudio para o
auscultador do jogador é o passo seguinte (ver `bridge/README.md`) — quando
existir, entra aqui, sem reescrever isto.

## Identificação: pelo destino da chamada, não pelo caller ID

**Cada telefone físico tem de marcar um alvo distinto** (por exemplo, `9001`,
`9002`, `9003`, `9004` — um por telefone, configurado como marcação directa ou
tecla de marcação rápida em cada aparelho). `bridge/adapters/sip_adapter.py`
usa esse número (`Caller-Destination-Number` no evento `CHANNEL_ANSWER`) para
identificar a linha, não o caller ID — que em chamada IP directa não é de
fiar (pode vir vazio, "Anonymous", ou igual em todos os telefones consoante o
aparelho). Dois telefones a marcar o mesmo alvo ao mesmo tempo não perdem a
segunda chamada em silêncio (o adaptador desambigua), mas não é o desenho —
configura sempre um alvo por telefone.

## DTMF

Os Yealink T30 suportam RFC2833, SIP INFO, ou os dois (`account.X.dtmf.type`
no telefone). Não fixámos um único modo no perfil — o core do FreeSWITCH
trata os dois lados sem escolher (ver comentário em `sip_profiles/internal.xml`).
Se em teste com um telefone real os dígitos não chegarem ao `SlotManager`, o
primeiro sítio a olhar é o `dtmf.type` configurado no telefone, não esta
configuração.

## Problemas resolvidos (dos dois conhecidos à partida)

1. **IP público anunciado** — `external_rtp_ip`/`external_sip_ip` vinham de
   uma consulta STUN a `stun.freeswitch.org`, confirmado a devolver
   `81.193.176.165`. Resolvido em `vars.xml` (ver tabela acima). Efeito
   colateral bom: também deixa de fazer essa consulta de rede no arranque —
   numa LAN de evento sem internet, isso só servia para atrasar ou falhar.
2. **`mod_av` falha a carregar** — desactivado em `modules.conf.xml`. É
   módulo de vídeo, não usado.

Um terceiro problema **apareceu durante este trabalho**, não estava na lista
original: `apply-inbound-acl: domains` do perfil vanilla nega TODAS as
chamadas quando não há utilizadores com `cidr=` no directory (é o caso aqui) —
confirmado em teste (`sofia.c:10679 IP ... Rejected by acl "domains"`, chamada
nunca chegava ao dialplan). Resolvido com `localnet.auto` (ver tabela acima).

## Testado com um softphone real (sem telefone físico)

Ver `bridge/README.md` (secção SIP) para a prova de chamada real (baresip →
FreeSWITCH → ESL → `SlotManager`) e o que fica por confirmar só com um Yealink
T30 físico na mão.
