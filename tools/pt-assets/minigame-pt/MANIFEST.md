# MANIFEST — dobragem PT dos minijogos (2026-08-09)

Cada linha é um ficheiro do jogo que foi substituído (WAV instalado na BigFile).
Origem: 17 gravações de estúdio (13 aproveitadas, 1 sem uso) mais 1 corte directo do
episódio PT. As gravações não instaladas (3 de 17) estão descritas na secção
"Não instaladas" mais abaixo, com o motivo — os ficheiros do jogo
correspondentes ficaram em espanhol.

Formato de todos os WAV: `pcm_s16le`, mono, 44100 Hz — igual ao original,
confirmado por `ffprobe` antes de converter.

## Instaladas (14 falas: 13 das gravações + 1 do episódio)

| ficheiro do jogo | gravação de origem (~/Downloads) | duração original | duração final | atempo | transcrição confirmada (whisper -l pt) |
|---|---|---|---|---|---|
| `ForestData/speaks/005-13.wav` | `fizemos muito bem.mp4` | 1.89s | 1.88s | 1.03x | «Está no papo! Bem jogado!» — nota: desvia da proposta literal do guião («Fizemos muito bem!»), mas é a mesma ideia de vitória; é a única fala da floresta com este tema, e esta frase já tinha sido identificada como candidata válida na análise do vídeo (Parte 2 do guião) |
| `ForestData/speaks/005-10.wav` | `hora de saltar.mp4` | 1.65s | 1.63s | 1.075x | inconclusiva no whisper (devolveu "Havicala!", sem sentido em qualquer transcrição tentada) — mapeada por nome do ficheiro (copia a proposta do guião) + duração em bruto compatível com uma exclamação curta; nenhuma outra fala da floresta se encaixa |
| `ForestData/speaks/005-08.wav` | `Que fazemos nós aqui?.mp4` | 2.08s | 1.66s | não | «Como é que viemos aqui parar?» — desvia da proposta literal («Que fazemos nós aqui?»), mas é a mesma frase alternativa já identificada na análise do vídeo (Parte 2) para esta exata fala |
| `ForestData/speaks/005-11.wav` | `«Olha os passarinhos!».mp4` (**segunda entrega**, 22:32 — fala nos últimos 2.25s de 8.9s) | 2.560s | 2.560s | não | «[Olha os] passarinhos!» (whisper lê «Pepe, passarinhos!»; troca o arranque, acerta na palavra). Substitui a primeira entrega, que era byte-a-byte igual à de `Ai ai ai ai! Que dor.mp4` — o Paulo voltou a enviar as duas separadas, cada uma com o seu take |
| `RopeOutroData/speak/002-12.wav` | `bravo estamos livres.mp4` | 2.96s | 2.18s | não | «Meu herói, estamos livres!» (falante: Hugoline) |
| `RopeOutroData/speak/002-08.wav` | `va escolhe la.mp4` | 5.57s | 3.96s | não | «Agora tens escolhas e eu sei que vais perder.» (falante: Bruxa/Afskylia) |
| `RopeOutroData/speak/002-07.wav` | `ola esta ai alguem.mp4` | 3.58s | 2.17s | não | «Olá! Está aí alguém?» (falante: Hugo) |
| `RopeOutroData/speak/002-05.wav` | `socorro.mp4` | 3.41s | 3.40s | não | «Socorro! Hugo, ajuda-nos!» (falante: Hugoline) |
| `ForestData/speaks/005-01.wav` | **não é gravação** — corte do episódio PT `hugo-assets/pt-floresta.mkv`, `00:00:00.12–00:00:02.99` | 2.8996s | 2.8995s | não | «Bem, vamos lá começar isto!» — o candidato limpo que a análise do vídeo (Parte 2 do guião) já tinha dado como resolvido; é a abertura do episódio, a música de fundo só entra depois (silêncio confirmado até ao fim do corte) |
| `RopeOutroData/speak/002-06.wav` | `acho que pode ser perigoso.mp4` | 4.458s | 4.458s | não | «Hum, isto vai ser renhido!» — adaptação, não tradução literal (ver nota abaixo) |
| `ForestData/speaks/005-05.wav` | `Vá lá! É a tua última oportunidade..mp4` | 4.050s | 4.050s | não | «Continua lentinho e vais de carrinho!» — adaptação (ver nota abaixo) |
| `ForestData/speaks/005-03.wav` | `Não sejas lento Estou pronto para ir.mp4` | 3.669s | 3.668s | não | «Não seja esmolingão, joga com o coração!» — adaptação (ver nota abaixo) |
| `ForestData/speaks/005-04.wav` | `ai ai ai.mp4` (fala nos últimos 2.5s de um ficheiro de 125s) | 3.048s | 3.047s | não | começa no gemido de dor («Aaaah!») seguido de uma queixa que o whisper não fixa (leituras entre «Como é que eu ando com a cabeça?» e variantes) — mas o arranque é inequívoco e o slot é o do «¡Ay ay ay ay! ¡Qué dolor!». **Este é o take que faltava:** MD5 distinto do de `«Olha os passarinhos!».mp4`, ao contrário do ficheiro homónimo entregue antes |
| `ForestData/speaks/005-12.wav` | `Trolli-drit, trolli-drata.mp4` (fala nos últimos 4s de um ficheiro de 111s) | 4.450s | 4.352s | não | «[Está] tramado! Mas este jogo está acabado!» — o whisper devolve «É gramado», normal em sílabas sem sentido, mas o fecho bate certo com o espanhol («¡Este juego está a capur!») e rima como as outras adaptações. A ladainha «trolli-drit, trolli-drata, trolli-drut» do original não foi mantida |

**Nota sobre as três adaptações (002-06, 005-05, 005-03).** Estas tinham sido
retidas por o texto gravado não bater com a proposta do guião. Não era erro: o
Paulo confirmou que o estúdio adaptou em vez de traduzir à letra — o espanhol e
o português dizem coisas diferentes de propósito, com o mesmo sentido de cena.
Instaladas por decisão dele. O que continua a mandar é só a duração.

Onze das treze gravações foram recortadas por deteção de silêncio (`silencedetect`, vários limiares
entre -30dB e -8dB conforme o ficheiro) para isolar a fala, com margem mínima
natural. As 4 da caverna vinham em ficheiros de ~80–94s com muito silêncio à
volta e, nos 5 ficheiros de 94s, uma frase solta e recorrente no fim
("Agora que o jogo estava a aquecer!") que não é a fala do jogo — foi excluída
do corte em todos os casos. As duas restantes (`005-05`, `005-03`) já vinham
justas, sem silêncio a cortar, e entraram inteiras.

## Não instaladas (3 de 17) — e aí a fala do jogo fica em espanhol

Nenhuma ficou de fora por causa do texto: duas são impossíveis de encaixar no
tempo e uma é ambígua.

| gravação (~/Downloads) | fala a que se destinava | motivo |
|---|---|---|
| `juro que voltarei.mp4` | `002-09.wav` (Hugo, «Juro que volto já!») | **duração.** O texto («E salvou a sua família!») é adaptação aceite pelo Paulo, como as outras três, mas a fala dura 3.86s e o `002-09` é o slot mais curto de toda a caverna: o WAV espanhol tem 1.83s e o lip-sync (`Syncs/002-09.oos`, 167 bytes) dá ~1.4s. Precisaria de `atempo` 2.7x. Só com regravação curta. |
| `¡Oi!» (grunhido de impacto).mp4` | `005-07.wav` (grunhido de impacto, 0.41s) | **duração.** Conteúdo confirmado («Bimba!»), mas a palavra com as duas sílabas dura ~0.85–0.97s mesmo no núcleo mais alto de energia — não cabe em 0.41s nem com `atempo` no limite de 1.08x (daria ~0.79–0.90s). Precisa de uma interjeição de uma sílaba, tipo o "Oi!" original. |
| `grito sem palavras.mp4` | ambíguo — pode ser `005-06`, `005-09`, `002-10` ou `002-11` (os 4 gritos que não são `005-07`) | confirmado por whisper que é só grito sem palavras («AAAAAAAI»), mas o nome do ficheiro não identifica a qual dos 4 gritos se destina, e não há forma segura de decidir sem confirmação do Paulo. Não adivinhado. Reportado, não instalado — e, como nota lateral, os gritos ficam bem com o original em qualquer língua (ver guião). |

### Uma entrega sem uso, mas sem consequência

`Ai ai ai ai! Que dor.mp4` (primeira entrega) era cópia byte-a-byte (MD5
idêntico) de `«Olha os passarinhos!».mp4` — o conteúdo real era "[olha os]
passarinhos", não "ai ai ai". Está resolvido: o Paulo reenviou as duas
separadas, `ai ai ai.mp4` para o `005-04` e um `«Olha os passarinhos!».mp4`
novo para o `005-11`, cada uma com o seu take, e ambas estão instaladas. Este
ficheiro fica sem uso — mas nenhuma fala ficou em espanhol por causa dele, ao
contrário das três da tabela acima.

## Falas do jogo que continuam em espanhol (das 21 no total)

Floresta (`ForestData/speaks/`):
- `005-02` — não faz parte das gravações entregues.
  (`005-01` também não fazia, mas foi resolvido pelo corte do episódio PT — ver
  tabela das instaladas.)
- `005-06`, `005-09` — gritos, mantêm-se sempre o original (língua neutra).
- `005-07` — gravação entregue mas não cabe no tempo exigido (ver tabela acima).

Caverna (`RopeOutroData/speak/`):
- `002-09` — gravação entregue mas não cabe no tempo exigido (ver tabela acima).
- `002-10`, `002-11` — gritos, mantêm-se sempre o original (língua neutra).

Total: 7 das 21 falas continuam em espanhol — 1 não fornecida, 4 gritos (que
ficam bem no original em qualquer língua), 2 que não cabem no tempo (`005-07`,
`002-09`).

## O limite real de cada fala é o lip-sync, não o WAV

A restrição não é a duração do WAV espanhol: é o `.oos` correspondente em
`Syncs/`, que o jogo lê um byte por passo e que termina o estado de fala quando
acaba (`game/tv_show/*`, `get_frame_index() >= len(sync_hitlog)`). Nem todas as
falas têm `.oos` — só as que têm boca a mexer.

Ajuste linear sobre as 11 falas com `.oos` (erro máximo 1.9 bytes ≈ 0.21s):

    bytes ≈ 154.4 + 8.92 × segundos

Ou seja: ~154 bytes de cabeçalho e um byte por cada ~112 ms. Serve para saber
quanto tempo uma fala aguenta *antes* de mandar gravar — e foi assim que se
concluiu que o `002-09` não tem salvação sem um take novo e curto.

## Ficheiros de trabalho (fora do WRITE SET)

Áudio extraído, testes de whisper e clips intermédios ficaram numa pasta
temporária da sessão de trabalho, fora do repositório, e já não existem. Para
refazer qualquer um dos cortes basta o WAV original (em
`hugo-assets/minigame-orig-backup/`, com o mesmo caminho relativo) e a
gravação de origem indicada na tabela.
