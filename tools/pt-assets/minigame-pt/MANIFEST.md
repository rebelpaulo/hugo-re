# MANIFEST — dobragem PT dos minijogos (2026-08-09)

Cada linha é um ficheiro do jogo que foi substituído (WAV instalado na BigFile).
Origem: 15 gravações de estúdio (8 aproveitadas) mais 1 corte directo do
episódio PT. As gravações não instaladas (7 de 15) estão descritas na secção
"Não instaladas" mais abaixo, com o motivo — os ficheiros do jogo
correspondentes ficaram em espanhol.

Formato de todos os WAV: `pcm_s16le`, mono, 44100 Hz — igual ao original,
confirmado por `ffprobe` antes de converter.

## Instaladas (9 falas: 8 das gravações + 1 do episódio)

| ficheiro do jogo | gravação de origem (~/Downloads) | duração original | duração final | atempo | transcrição confirmada (whisper -l pt) |
|---|---|---|---|---|---|
| `ForestData/speaks/005-13.wav` | `fizemos muito bem.mp4` | 1.89s | 1.88s | 1.03x | «Está no papo! Bem jogado!» — nota: desvia da proposta literal do guião («Fizemos muito bem!»), mas é a mesma ideia de vitória; é a única fala da floresta com este tema, e esta frase já tinha sido identificada como candidata válida na análise do vídeo (Parte 2 do guião) |
| `ForestData/speaks/005-10.wav` | `hora de saltar.mp4` | 1.65s | 1.63s | 1.075x | inconclusiva no whisper (devolveu "Havicala!", sem sentido em qualquer transcrição tentada) — mapeada por nome do ficheiro (copia a proposta do guião) + duração em bruto compatível com uma exclamação curta; nenhuma outra fala da floresta se encaixa |
| `ForestData/speaks/005-08.wav` | `Que fazemos nós aqui?.mp4` | 2.08s | 1.66s | não | «Como é que viemos aqui parar?» — desvia da proposta literal («Que fazemos nós aqui?»), mas é a mesma frase alternativa já identificada na análise do vídeo (Parte 2) para esta exata fala |
| `ForestData/speaks/005-11.wav` | `«Olha os passarinhos!».mp4` | 2.56s | 2.52s | não | «[Olha os] passarinhos!» confirmado por whisper — **atenção:** este ficheiro é byte-a-byte idêntico (MD5 igual) a `Ai ai ai ai! Que dor.mp4`; o conteúdo real é "passarinhos", não "ai ai ai que dor" — ver secção "Não instaladas" |
| `RopeOutroData/speak/002-12.wav` | `bravo estamos livres.mp4` | 2.96s | 2.18s | não | «Meu herói, estamos livres!» (falante: Hugoline) |
| `RopeOutroData/speak/002-08.wav` | `va escolhe la.mp4` | 5.57s | 3.96s | não | «Agora tens escolhas e eu sei que vais perder.» (falante: Bruxa/Afskylia) |
| `RopeOutroData/speak/002-07.wav` | `ola esta ai alguem.mp4` | 3.58s | 2.17s | não | «Olá! Está aí alguém?» (falante: Hugo) |
| `RopeOutroData/speak/002-05.wav` | `socorro.mp4` | 3.41s | 3.40s | não | «Socorro! Hugo, ajuda-nos!» (falante: Hugoline) |
| `ForestData/speaks/005-01.wav` | **não é gravação** — corte do episódio PT `hugo-assets/pt-floresta.mkv`, `00:00:00.12–00:00:02.99` | 2.8996s | 2.8995s | não | «Bem, vamos lá começar isto!» — o candidato limpo que a análise do vídeo (Parte 2 do guião) já tinha dado como resolvido; é a abertura do episódio, a música de fundo só entra depois (silêncio confirmado até ao fim do corte) |

Todas as 8 gravações recortadas por deteção de silêncio (`silencedetect`, vários limiares
entre -30dB e -8dB conforme o ficheiro) para isolar a fala, com margem mínima
natural. As 4 da caverna vinham em ficheiros de ~80–94s com muito silêncio à
volta e, nos 5 ficheiros de 94s, uma frase solta e recorrente no fim
("Agora que o jogo estava a aquecer!") que não é a fala do jogo — foi excluída
do corte em todos os casos.

## Não instaladas (7 de 15) — ficheiros do jogo continuam em espanhol

| gravação (~/Downloads) | fala a que se destinava | motivo |
|---|---|---|
| `juro que voltarei.mp4` | `002-09.wav` (Hugo, «Juro que volto já!») | conteúdo transcrito não corresponde: whisper devolveu «E salvou a sua família!» — frase da Parte A (clips de TV), não da fala do minijogo. Reportado, não instalado. |
| `acho que pode ser perigoso.mp4` | `002-06.wav` (Hugo, «Mas acho que isto pode ser perigoso!») | conteúdo transcrito não corresponde: whisper devolveu «Hum... isto vai ser renido!» — frase não identificada em nenhuma das 21 falas. Reportado, não instalado. |
| `Vá lá! É a tua última oportunidade..mp4` | `005-05.wav` (Hugo, «Vá lá! É a tua última oportunidade.») | apesar do nome do ficheiro citar a proposta do guião, o conteúdo transcrito é outro: «Continua lentinho e vais de carrinho!» — frase coerente mas sem relação com "última oportunidade", não corresponde a nenhuma fala da floresta. Reportado, não instalado. |
| `Não sejas lento Estou pronto para ir.mp4` | `005-03.wav` (Hugo, «Não sejas lento! Estou pronto para ir!») | conteúdo transcrito: «Não seja esmolingão, joga com o coração!» — corresponde exatamente à "parecença enganosa" já identificada e descartada na análise do vídeo (Parte 2 do guião, nota sobre `005-03`): mesmo início ("não seja(s)"), mas segunda metade genérica e sem relação com "estou pronto para partir". Reportado, não instalado. |
| `¡Oi!» (grunhido de impacto).mp4` | `005-07.wav` (grunhido de impacto, 0.41s) | conteúdo confirmado («Bimba!»), mas a palavra em si (com as duas sílabas completas) dura ~0.85–0.97s mesmo no núcleo mais alto de energia — não cabe em 0.41s nem com `atempo` no limite de 1.08x (daria ~0.79–0.90s). Precisa de regravação mais curta (uma interjeição de uma sílaba, tipo o "Oi!" original). Reportado, não instalado. |
| `grito sem palavras.mp4` | ambíguo — pode ser `005-06`, `005-09`, `002-10` ou `002-11` (os 4 gritos que não são `005-07`) | confirmado por whisper que é só grito sem palavras («AAAAAAAI»), mas o nome do ficheiro não identifica a qual dos 4 gritos se destina, e não há forma segura de decidir sem confirmação do Paulo. Não adivinhado. Reportado, não instalado — e, como nota lateral, os gritos ficam bem com o original em qualquer língua (ver guião). |
| `Ai ai ai ai! Que dor.mp4` | `005-04.wav` (Hugo, «Ai ai ai ai! Que dor!») | **ficheiro é cópia byte-a-byte (MD5 idêntico) de `«Olha os passarinhos!».mp4`** — o conteúdo real é "[olha os] passarinhos", não "ai ai ai que dor". Não existe gravação distinta para esta fala. Reportado, não instalado. |

## Falas do jogo que continuam em espanhol (das 21 no total)

Floresta (`ForestData/speaks/`):
- `005-02`, `005-12` — não fazem parte das 15 gravações entregues.
  (`005-01` também não fazia, mas foi resolvido pelo corte do episódio PT — ver
  tabela das instaladas.)
- `005-03` — gravação entregue mas conteúdo não corresponde (ver tabela acima).
- `005-04` — gravação entregue é cópia da de `005-11`, sem conteúdo próprio (ver tabela acima).
- `005-05` — gravação entregue mas conteúdo não corresponde (ver tabela acima).
- `005-06`, `005-09` — gritos, mantêm-se sempre o original (língua neutra).
- `005-07` — gravação entregue mas não cabe no tempo exigido (ver tabela acima).

Caverna (`RopeOutroData/speak/`):
- `002-06`, `002-09` — gravações entregues mas conteúdo não corresponde (ver tabela acima).
- `002-10`, `002-11` — gritos, mantêm-se sempre o original (língua neutra).

Total: 8 das 21 falas continuam em espanhol (2 não fornecidas, 2 gritos na
floresta, 2 gritos na caverna, e 2 falas fornecidas mas rejeitadas por conteúdo
errado — `005-03`/`005-05` — mais `005-04`/`005-07` por, respetivamente, cópia
sem conteúdo próprio e duração impossível de encaixar).

## Ficheiros de trabalho (fora do WRITE SET)

Áudio extraído, testes de whisper e clips intermédios ficaram em
`/private/tmp/claude-501/-Users-mac-Claude-code/027ee575-9ffb-413b-b850-8994a6785b34/scratchpad/pt15/`
— pasta temporária da sessão, não faz parte do repositório.
