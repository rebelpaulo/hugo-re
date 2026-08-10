# Guião de gravação — dobragem PT do Hugo (Revenge of the 90s, 12 set 2026)

Este documento é para levar para o estúdio. Não é uma lista de nomes de ficheiros —
é o que dizer, quanto tempo se tem para o dizer, e quem está a falar em cada frase.

Há **duas coisas diferentes** aqui dentro, com regras diferentes:

- **Parte A** — os 6 clips do programa de TV. São vídeo + som cortados juntos do
  mesmo master; não se grava nada de novo, ajusta-se o timecode do corte.
- **Parte B** — as 21 falas dos minijogos (floresta + caverna). São só áudio, e são
  as que o Paulo vai mesmo gravar de novo, em português, encaixadas no tempo exato.

---

## PARTE A — os 6 clips do programa de TV

Master usado: `hugo-assets/pt-master.mkv` (24m25s). Timecodes reais em
`tools/pt-assets/cuts.yaml` (não alterado por esta tarefa). Para cada um dos 5
clips com problema fui ao master à procura de um trecho melhor: usei deteção de
cortes de câmara do ffmpeg (`select='gt(scene,0.3)'`) sobre o vídeo inteiro,
cruzei com os timestamps por palavra das legendas automáticas, e confirmei os
cortes candidatos a olho, frame a frame (grelhas de still a cada 0,1–0,5 s).
`press_5` já estava bom e não foi mexido.

| clip | timecode atual | proposta nova | dentro de um só plano? | confiança |
|---|---|---|---|---|
| `attract_demo` | `00:00:00.000–00:00:16.680` | **manter** | sim (plano único confirmado até aos 39,74s) | alta — mas ver nota 1 |
| `hello_hello` | `00:11:43.800–00:11:50.100` | **sem candidato bom, ver nota 2** | não | baixa |
| `scylla_cave` | `00:14:31.120–00:14:34.850` | `00:14:31.250–00:14:34.850` | quase — ver nota 3 | alta |
| `you_lost` | `00:15:08.350–00:15:14.150` | `00:15:08.470–00:15:14.150` | sim | alta |
| `have_luck` | `00:12:05.550–00:12:07.100` | **manter** (ver nota 4) | não | baixa |

### Nota 1 — `attract_demo`: não há candidato melhor, e não é um problema de timecode

Confirmei duas coisas:
- **É um plano contínuo verdadeiro.** A deteção de cortes de câmara no vídeo
  inteiro não encontra nenhum corte antes dos 39,74 s — o troço 0–16,68 s não
  atravessa nenhuma mudança de plano.
- **Não há segunda ocorrência.** É a abertura do programa, toca uma única vez
  nos 24m25s do master. Não existe outro trecho a que recorrer.
- Transcrevi o áudio desse troço com o whisper (não é mudo, mas também não é
  "fala" no sentido de diálogo): é a **canção do genérico** a ser cantada
  ("♪ Foge à esquerda e à direita, sem fazer asneiras / foge para cima, para
  baixo, até à caverna das caveiras ♪"), sobre a animação do túnel. Isto
  confirma a nota já existente no `cuts.yaml` ("sem fala; só música/efeitos")
  — é canção/música de fundo, não uma frase dita por alguém.

O problema do loop (as duas pontas não fecham) é estrutural — a animação tem
sentido único e só existe uma vez — não é uma escolha de timecode errada.
Não há nada para "afinar" aqui.

### Nota 2 — `hello_hello`: o master corta sempre para a mascote nesta saudação

O contact sheet mostra a mascote Hugo em vez do apresentador. Fui ver porquê,
frame a frame, e o padrão é sistemático, não um acaso deste timecode:

- No plano usado atualmente (703,80–710,10 s), o corte de câmara real
  apresentador → mascote acontece aos **~702,15 s** — ou seja, o timecode atual
  já começa depois da mascote entrar em cena.
- O corte de volta mascote → apresentador só acontece aos **~710,35 s**, quase
  no fim do trecho.
- A frase «Olá, estás bom? Estou, tudo bem, Marco? Sim.» é dita **quase toda
  durante o corte para a mascote**, não durante o apresentador.
- Fui verificar o mesmo momento para outro finalista (Ana Catarina, ~05:11) e o
  padrão repete-se ao pormenor: ~2,5 s de apresentador, depois corte para a
  mascote onde continua a saudação. **É assim que o programa está montado para
  todos os finalistas** — não há, em lado nenhum do master, um plano do
  apresentador a dizer esta saudação sem cortar para a mascote.

Ou seja: **não há um timecode que dê ao mesmo tempo o apresentador na imagem E
o áudio da saudação certa** — o master funde as duas coisas. As opções reais são:
1. Manter o atual (mascote na imagem, áudio da saudação certo) — o que já está.
2. Mudar para `00:11:50.35–00:11:55.18` (plano do apresentador, mas a dizer
   "então quanto a este jogo, tens alguma dúvida" — não é uma saudação).

Nenhuma destas é boa. Fica reportado como está — não inventei um candidato só
para preencher a tabela.

### Nota 3 — `scylla_cave`: reduz de 3 planos para efetivamente 1 (mais uma sobra de 0,5s do plano seguinte)

O clip atual atravessa mesmo 3 planos, confirmado frame a frame:
marcador de pontos (até aos 871,24s) → apresentador (871,24–874,31s) →
mascote/caverna (a partir dos 874,31s). A frase completa «Marco, como tu
sabes, vamos já já à caverna das caveiras, tá bem?» só cabe se se aceitar
~0,5s do plano seguinte no fim (a palavra "bem" cai mesmo em cima do corte
para a caverna). A proposta nova tira o marcador de pontos do início (que
sobrava só 0,12s) e mantém o fim como está, para não cortar a frase a meio.
Um corte estritamente de plano único (871,25–874,30) existe mas perde a
palavra final "bem".

### Nota 4 — `you_lost`: o corte já está quase certo; o problema é mesmo a duração, não o plano

Ao contrário do que a tabela original sugeria, o cruzamento com planos é
mínimo: há um corte real aos 908,47s (fim da animação da armadilha → início
do plano do apresentador), e o timecode atual começa aos 908,35s — só 0,12s
antes, praticamente impercetível. Proponho mover o início para 908,47s para
tirar esse resquício.

O plano do apresentador que se segue é **longo e contínuo** (vai até aos
920,59s, mais de 12s), por isso já não há problema de "atravessar corte" no
fim — o timecode atual (914,15s) fica bem dentro do mesmo plano. Mas **não há
mais texto de despedida para esticar**: logo a seguir, ainda no mesmo plano,
o apresentador emenda para "…tchau, o quinto montanhista desta final é o
Miguel Ângelo" — ou seja, esticar o clip começaria a incluir a introdução do
finalista seguinte, o que não serve para `you_lost`. A curta duração
(5,68 s vs. a referência de 17,17 s mencionada no `cuts.yaml`) é uma
limitação de conteúdo real, confirmada — não um erro de escolha.

Confirmei também, ao ler as legendas de todo o master, que **nenhum dos 5
finalistas que chega à caverna perde o jogo da corda** — todos salvam a
família ("Hugo puxou e salvou a sua família"). Não existe no master nenhuma
derrota genuína da caverna; o desfecho de Marco (consolação, "já vais ganhar
um prémio") continua a ser o mais próximo disso que há.

### Sem nota — `have_luck`: mantém-se; a frase está fundida com a transição de imagem

O timecode atual (725,55–727,10s) capta exatamente o momento em que o
apresentador desaparece num wipe para o ecrã do "televisor" que mostra o
jogo. Vi frame a frame: a transição de imagem começa aos ~725,5s, **antes**
da palavra "boa" ser dita (~725,64s) — ou seja, não existe nenhum momento em
que "boa sorte" seja dito com o apresentador em plano fixo, sem a transição já
a decorrer. Confirma a nota já existente no `cuts.yaml`: é mesmo só essas duas
palavras, sem mais texto à volta, fundidas com a mudança de imagem. Não
encontrei nada melhor para propor.

---

## PARTE B — as 21 falas dos minijogos

Estas são só áudio (WAV), vivem na BigFile e ficam em espanhol se não
gravarmos PT. **A restrição que manda em tudo:** o jogo usa ficheiros `.oos`
de sincronismo labial ao lado de cada WAV, e o código termina o estado do
jogo quando os frames desse `.oos` acabam (ex.: `game/forest/hurt_branch_talking.py:18`,
`if self.get_frame_index() >= len(ForestResources.sync_hitlog): ...`). **A
fala portuguesa tem de durar exatamente o mesmo tempo que a original** — mais
comprida corta a meio da frase, mais curta e o Hugo fica de boca aberta em
silêncio.

Transcrevi as 21 com whisper.cpp (`whisper-cli -l es`) — modelo e critério
abaixo. As propostas de fala portuguesa foram calibradas por **contagem de
sílabas contra o original espanhol** (a técnica normal de isocronia em
dobragem: mesmo número de sílabas a um ritmo semelhante tende a caber no
mesmo tempo). **Isto não é medição de áudio real** — não sintetizei voz
portuguesa nenhuma para cronometrar, por isso as marcadas "cabe (justo)"
devem ser lidas em voz alta contra um cronómetro/DAW no estúdio antes de dar
como boas. Isto é o que falta verificar, não o que já está verificado.

### Modelo de whisper usado e porquê

`ggml-medium.bin` (multilingue, ~1,53GB), guardado em
`~/.cache/whisper.cpp/models/ggml-medium.bin` (fora do repositório — binário
grande, não fazia sentido versionar). Escolhido em vez do `small`: são vozes
de personagem de desenho animado (registo aguda/exagerada, a bruxa e o Hugo
falam com timbres muito distintos do normal), onde o `base`/`small` erram
mais facilmente vogais e finais de palavra. O `medium` deu transcrições limpas
e consistentes com os comentários em inglês já existentes no código-fonte
(ex.: `005-08` → "¿Qué estamos haciendo aquí?", que bate certo com o
comentário `# what are we doing here` em `forest_resources.py:200-201`) — não
usei essa concordância como transcrição em si, só como confirmação de que o
modelo está a ouvir bem. Corri com `-l es` (espanhol forçado, não `auto`) por
ser a língua de origem conhecida.

### Floresta (`ForestData/speaks/`) — falante: **Hugo** em todas (é o único
personagem na floresta; confirmado pelo código, que só carrega SFX ambiente
além destas falas)

Caminho de cada WAV confirmado no disco (existe, casing igual ao que está lá) —
para ouvir no Finder ou arrastar para um editor.

| ficheiro | duração | espanhol (whisper) | proposta PT | cabe? | caminho |
|---|---|---|---|---|---|
| `005-01.wav` | 2.90s | «¡Ok! ¡Comencemos a jugar!» | «Muito bem, vamos jogar!» | sim | `/Users/mac/Claude code/hugo-assets/gold/BigFile/ForestData/speaks/005-01.wav` |
| `005-02.wav` | 3.09s | «¡Qué horrible sensación!» | «Que sensação horrível!» | sim | `/Users/mac/Claude code/hugo-assets/gold/BigFile/ForestData/speaks/005-02.wav` |
| `005-03.wav` | 3.67s | «¡No seas lento! ¡Estoy listo para partir!» | «Não sejas lento! Estou pronto para ir!» | sim | `/Users/mac/Claude code/hugo-assets/gold/BigFile/ForestData/speaks/005-03.wav` |
| `005-04.wav` | 3.05s | «¡Ay ay ay ay! ¡Qué dolor!» | «Ai ai ai ai! Que dor!» | sim | `/Users/mac/Claude code/hugo-assets/gold/BigFile/ForestData/speaks/005-04.wav` |
| `005-05.wav` | 4.05s | «¡Arriba! Esta es tu última oportunidad.» | «Vá lá! É a tua última oportunidade.» | sim (justo) | `/Users/mac/Claude code/hugo-assets/gold/BigFile/ForestData/speaks/005-05.wav` |
| `005-06.wav` | 4.91s | grito, sem palavras | — ver secção de gritos | — | `/Users/mac/Claude code/hugo-assets/gold/BigFile/ForestData/speaks/005-06.wav` |
| `005-07.wav` | 0.41s | «¡Oi!» (grunhido de impacto) | — ver secção de gritos | — | `/Users/mac/Claude code/hugo-assets/gold/BigFile/ForestData/speaks/005-07.wav` |
| `005-08.wav` | 2.08s | «¿Qué estamos haciendo aquí?» | «Que fazemos nós aqui?» | sim | `/Users/mac/Claude code/hugo-assets/gold/BigFile/ForestData/speaks/005-08.wav` |
| `005-09.wav` | 4.27s | grito, sem palavras | — ver secção de gritos | — | `/Users/mac/Claude code/hugo-assets/gold/BigFile/ForestData/speaks/005-09.wav` |
| `005-10.wav` | 1.65s | «¡Hora de saltar!» | «Hora de saltar!» | sim (idêntica) | `/Users/mac/Claude code/hugo-assets/gold/BigFile/ForestData/speaks/005-10.wav` |
| `005-11.wav` | 2.56s | «¡Mira los pajaritos!» | «Olha os passarinhos!» | sim (idêntica em ritmo) | `/Users/mac/Claude code/hugo-assets/gold/BigFile/ForestData/speaks/005-11.wav` |
| `005-12.wav` | 4.45s | «Trolli-drit, trolli-drata, trolli-drut, este juego... ¡está a capur!» | «Trolli-drit, trolli-drata, trolli-drut, este jogo... já era!» | sim (folgado) | `/Users/mac/Claude code/hugo-assets/gold/BigFile/ForestData/speaks/005-12.wav` |
| `005-13.wav` | 1.89s | «¡Lo hicimos muy bien!» | «Fizemos muito bem!» | sim | `/Users/mac/Claude code/hugo-assets/gold/BigFile/ForestData/speaks/005-13.wav` |

Nota sobre `005-12`: o cântico sem sentido ("trolli-drit...") é uma marca do
Hugo, não espanhol — mantém-se igual em PT, só a frase final muda.

### Caverna (`RopeOutroData/speak/`) — três vozes diferentes

Falantes deduzidos do código (nomes das variáveis em `game/cave/cave_resources.py`
já apontam para os nomes das personagens, ex. `afskylia_snak`,
`hugoline_tak`) e confirmados pelo conteúdo da fala:

Caminho de cada WAV confirmado no disco (existe, casing igual ao que está lá).

| ficheiro | duração | quem fala | espanhol (whisper) | proposta PT | cabe? | caminho |
|---|---|---|---|---|---|---|
| `002-05.wav` | 3.41s | Hugoline (família presa na gaiola) — dedução: é o par de abertura de `002-12`, que é claramente a Hugoline | «¡Ayúdanos Hugo! ¡Ayúdanos!» | «Ajuda-nos, Hugo! Ajuda-nos!» | sim (idêntica) | `/Users/mac/Claude code/hugo-assets/gold/BigFile/RopeOutroData/speak/002-05.wav` |
| `002-06.wav` | 4.46s | Hugo | «¡Pero siento que esto puede ser muy peligroso!» | «Mas acho que isto pode ser perigoso!» | sim | `/Users/mac/Claude code/hugo-assets/gold/BigFile/RopeOutroData/speak/002-06.wav` |
| `002-07.wav` | 3.58s | Hugo | «¡Hola! ¿Hay alguien allí?» | «Olá! Está aí alguém?» | sim | `/Users/mac/Claude code/hugo-assets/gold/BigFile/RopeOutroData/speak/002-07.wav` |
| `002-08.wav` | 5.57s | Bruxa (Afskylia/Scylla) | «Adelante, elegí, estoy segura de que perderás.» | «Vá, escolhe lá, tenho a certeza de que vais perder.» | sim (idêntica) | `/Users/mac/Claude code/hugo-assets/gold/BigFile/RopeOutroData/speak/002-08.wav` |
| `002-09.wav` | 1.83s | Hugo | «¡Juro que volveré!» | «Juro que volto já!» | sim (idêntica) | `/Users/mac/Claude code/hugo-assets/gold/BigFile/RopeOutroData/speak/002-09.wav` |
| `002-10.wav` | 3.30s | Hugo | grito, sem palavras (whisper devolveu só uma descrição entre asteriscos, sinal de que não há fala real) | — ver secção de gritos | — | `/Users/mac/Claude code/hugo-assets/gold/BigFile/RopeOutroData/speak/002-10.wav` |
| `002-11.wav` | 2.90s | Bruxa (Afskylia/Scylla) | grito, sem palavras | — ver secção de gritos | — | `/Users/mac/Claude code/hugo-assets/gold/BigFile/RopeOutroData/speak/002-11.wav` |
| `002-12.wav` | 2.96s | Hugoline | «¡Bravo! ¡Estamos libres!» | «Bravo! Estamos livres!» | sim (idêntica) | `/Users/mac/Claude code/hugo-assets/gold/BigFile/RopeOutroData/speak/002-12.wav` |

---

## As que são gritos e devem ficar como estão

O ticket apontava três (na floresta); ao transcrever encontrei mais duas na
caverna com o mesmo padrão — fica registado porque é a mesma decisão pelo
mesmo motivo:

| ficheiro | o que se ouve | porquê é "manter original" | caminho |
|---|---|---|---|
| `005-06.wav` (4.91s) | grito prolongado ao ser catapultado para cima | vocalização pura ("Aaaa…"), sem palavras — confirma o comentário do código `# flying up scream` | `/Users/mac/Claude code/hugo-assets/gold/BigFile/ForestData/speaks/005-06.wav` |
| `005-07.wav` (0.41s) | grunhido curto de impacto ("Oi!") | 0,41s não dá para nenhuma palavra com significado; é reação a pancada, não fala — confirma `# hit by catapult` | `/Users/mac/Claude code/hugo-assets/gold/BigFile/ForestData/speaks/005-07.wav` |
| `005-09.wav` (4.27s) | grito ao cair | vocalização pura, sem palavras — confirma `# fall noise` | `/Users/mac/Claude code/hugo-assets/gold/BigFile/ForestData/speaks/005-09.wav` |
| `002-10.wav` (3.30s) | grito do Hugo ao perder | o whisper nem tentou transcrever palavras, devolveu uma descrição entre asteriscos — sinal claro de que não há fala reconhecível; confirma o comentário `# Hugo screams on lost` | `/Users/mac/Claude code/hugo-assets/gold/BigFile/RopeOutroData/speak/002-10.wav` |
| `002-11.wav` (2.90s) | grito da bruxa ao perder o Hugo | vocalização pura — confirma `# Scylla screams on win` | `/Users/mac/Claude code/hugo-assets/gold/BigFile/RopeOutroData/speak/002-11.wav` |

Um grito é neutro em qualquer língua: não há tradução a fazer, só confirmar
que o WAV original se mantém tal e qual.

---

## O VÍDEO DA FLORESTA (`pt-floresta.mkv`) — dá para poupar metade das gravações?

**Resposta curta: não. Só uma das 13 falas se resolve com este vídeo.** É um
vídeo de 1m58s (118,21s, confirmado por `ffprobe`) e a maior parte do tempo é
música de fundo contínua, não diálogo.

`/Users/mac/Claude code/hugo-assets/pt-floresta.mkv`
`/Users/mac/Claude code/hugo-assets/pt-floresta.pt-PT.vtt`
`/Users/mac/Claude code/hugo-assets/pt-floresta.pt.vtt`

### Método

1. Extraí o áudio (`ffmpeg -ac 1 -ar 16000`) e corri `whisper-cli -m
   ggml-medium.bin -l pt` sobre o ficheiro inteiro — deu 14 linhas de
   transcrição, mas seis delas ("PAPA! PASSARINHOS!" repetido 6× entre os
   00:30 e os 01:11) são alucinação clássica do whisper sobre música sem
   fala — um padrão conhecido do modelo quando não há voz para ancorar.
   Descartei-as.
2. Cruzei com as duas legendas automáticas (`.pt-PT.vtt` e `.pt.vtt`, quase
   idênticas) para localizar os momentos de fala real por oposição às zonas
   marcadas `[Música]`.
3. Para cada candidato a fala, extraí um clip isolado (`ffmpeg -ss ... -t
   ...`) e voltei a correr o whisper só nesse excerto, para confirmar a
   transcrição sem o ruído do contexto longo.
4. **Teste de limpeza (é aqui que a maior parte cai):** corri
   `ffmpeg -af silencedetect=noise=-25dB:d=0.1` ao ficheiro inteiro. Da
   marca dos 71,5s até ao fim do vídeo (mais de 46 segundos, onde caem 3 das
   4 falas candidatas) **não há um único instante de silêncio**, nem a
   -25dB — ou seja, há uma cama de música/ambiente que nunca para, por
   baixo de tudo, fala incluída. Confirmei visualmente com espetrogramas
   (`ffmpeg -lavfi showspectrumpic`, guardados em
   `/private/tmp/claude-501/-Users-mac-Claude-code/027ee575-9ffb-413b-b850-8994a6785b34/scratchpad/floresta/spectro/`):
   a textura contínua por trás das palavras é igual à textura de um
   trecho comprovadamente só-música (00:10–00:17). Só nos primeiros ~3
   segundos do vídeo há mesmo silêncio a seguir à fala — antes de a música
   de fundo arrancar.
5. Medi a duração de cada candidato encontrado com o mesmo critério da
   Parte B: contra a duração total do WAV original (é essa que o `.oos` de
   sincronismo labial usa).

### O vídeo da floresta — tabela das 13

| fala | duração exigida | encontrada? | timecode (pt-floresta.mkv) | limpa? | cabe? |
|---|---|---|---|---|---|
| `005-01` «¡Ok! ¡Comencemos a jugar!» | 2.90s | **sim** — «Bem, vamos lá começar isto!» | `00:00:00.12–00:00:02.99` (≈2.87s) | **sim** — é a abertura do vídeo, a música de fundo só arranca a seguir (silêncio confirmado 00:02.42–00:02.99) | sim (falta 0,03s, negligenciável) |
| `005-02` «¡Qué horrible sensación!» | 3.09s | não | — | — | — |
| `005-03` «¡No seas lento! ¡Estoy listo para partir!» | 3.67s | **talvez, mas não confio** — há uma frase parecida ("Não seja molengão! Joga com o coração!", ~00:41–00:44) que começa com "não sejas/seja" como o original, mas o resto do conteúdo é diferente (é um slogan motivacional genérico, não "estou pronto para partir") — ver nota abaixo | `00:00:41.0–00:00:44.0` (não confirmado como equivalente real) | não (mesma cama contínua de música) | não se aplica — conteúdo não bate certo |
| `005-04` «¡Ay ay ay ay! ¡Qué dolor!» | 3.05s | não | — | — | — |
| `005-05` «¡Arriba! Esta es tu última oportunidad.» | 4.05s | não | — | — | — |
| `005-06` (grito) | 4.91s | não aplicável — grito, fica com o original de qualquer forma (ver secção de gritos) | — | — | — |
| `005-07` (grunhido) | 0.41s | não aplicável — idem | — | — | — |
| `005-08` «¿Qué estamos haciendo aquí?» | 2.08s | **sim, mas não serve** — «Como é que viemos aqui parar?» (mesma ideia — confusão sobre onde estão — mas frase diferente) | `~00:01:21.3–00:01:23.6` (≈2.3s) | **não** — dentro da zona sem silêncio nenhum (71,5s ao fim) | quase (teria de cortar ~0,2s) mas a falta de limpeza já chumba isto |
| `005-09` (grito) | 4.27s | não aplicável — idem | — | — | — |
| `005-10` «¡Hora de saltar!» | 1.65s | não | — | — | — |
| `005-11` «¡Mira los pajaritos!» | 2.56s | **parcial, não serve** — só se ouve a palavra solta "Passarinhos," (~00:36.5–00:38.6), falta o "Olha/Mira" inicial — frase incompleta | `~00:00:36.5–00:00:38.6` (≈1.5–2.0s, só uma palavra) | **não** — a própria legenda automática marca este instante como `[Música]` sobreposta | não (curto demais e incompleto) |
| `005-12` «Trolli-drit, trolli-drata...» | 4.45s | não | — | — | — |
| `005-13` «¡Lo hicimos muy bien!» | 1.89s | **sim, mas não serve** — «Está no papo! Bem jogado!» (mesma ideia de vitória, frase diferente) | `~00:01:54.5–00:01:57.5` (≈3.0s) | **não** — última zona do vídeo, sem silêncio desde os 71,5s | não (quase 1,1s longa demais, cortar perderia metade da frase) |

### Resumo: quantas se resolvem, quantas faltam

- **Resolvida pelo vídeo (limpa + duração praticamente exata): 1 de 13** —
  `005-01`.
- **Encontrada no vídeo mas não serve** (frase diferente e/ou tem música por
  baixo e/ou duração errada): 3 — `005-08`, `005-11`, `005-13`. Continuam a
  precisar de gravação nova.
- **Não aparece no vídeo de todo:** 6 — `005-02`, `005-04`, `005-05`,
  `005-10`, `005-12`, e `005-03` (o "quase" descrito acima não é fiável o
  suficiente para contar como encontrada).
- **Não aplicável** (gritos, ficam com o original de qualquer forma,
  independentemente deste vídeo): 3 — `005-06`, `005-07`, `005-09`.

Das 10 falas que realmente precisam de voz portuguesa (13 menos os 3
gritos), **este vídeo resolve 1**. As outras 9 continuam para gravação — a
poupança de "metade" que se esperava não se confirma. **É um "não dá" bem
fundamentado**: o vídeo tem só 1m58s, é sobretudo música de fundo contínua
(confirmada por ausência total de silêncio nos últimos 46s), e cobre apenas
alguns dos 13 momentos — os restantes simplesmente não estão lá.

### As que estão no vídeo mas não servem, e porquê

- **`005-08`** — a ideia bate certo ("que fazemos aqui" / "como viemos aqui
  parar"), a duração quase bate certo (2,3s vs. 2,08s exigidos), mas cai na
  zona do vídeo (a partir dos 71,5s) onde não há um único momento de
  silêncio detetado — confirma-se por espetrograma que há uma cama de
  música/ambiente por baixo da fala. Não dá para usar isolado sem se ouvir
  a música a tocar por cima no jogo.
- **`005-11`** — só apanha a palavra solta "Passarinhos," sem o "Olha"/"Mira"
  inicial; mesmo que fosse limpa (não é — a própria legenda automática do
  YouTube marca esse instante como música sobreposta), a frase está
  incompleta.
- **`005-13`** — mesma ideia (fim de jogo, vitória), mas a frase é diferente
  e mais longa (≈3,0s vs. 1,89s exigidos) e cai na mesma zona final sem
  silêncio nenhum. Cortar para caber perderia metade da frase.
- **`005-03`** — fica de fora da contagem de "encontradas" porque não tenho
  confiança que seja a mesma fala; ver nota abaixo.

### Nota sobre `005-03`: parecença enganosa

A fala do vídeo em torno dos 00:41–00:44 («Não seja molengão! Joga com o
coração!») começa com "não seja(s)", como o espanhol de `005-03` («¡No seas
lento!»), mas a segunda metade não corresponde a nada («estoy listo para
partir» = "estou pronto para partir", não "joga com o coração"). Parece mais
um slogan motivacional genérico do jogo (ou até um comentário acrescentado
por quem gravou o vídeo) do que a mesma linha de diálogo do Hugo. Não a
contei como "encontrada" — é o tipo de correspondência duvidosa que o ticket
pede para não listar como se fosse boa.

### Ficheiros de trabalho desta análise (não fazem parte do WRITE SET)

Áudio extraído, clips de candidatos e espetrogramas ficaram em
`/private/tmp/claude-501/-Users-mac-Claude-code/027ee575-9ffb-413b-b850-8994a6785b34/scratchpad/floresta/`
— úteis para o Paulo conferir a olho/ouvido antes de validar, mas é uma
pasta temporária da sessão, não o repositório.

---

## Onde ficou o documento

`/Users/mac/Claude code/hugo-re/tools/pt-assets/GUIAO-AUDIO-PT.md`

O modelo de whisper ficou em `~/.cache/whisper.cpp/models/ggml-medium.bin`
(fora do repositório).

---

## Como aplicar

### Parte A (clips de vídeo+áudio do programa)

Não se grava nada de novo. Quem decidir avançar com as propostas da Nota 3 e
da Nota 4 acima só precisa de:
1. Atualizar os `start`/`end` de `scylla_cave` e `you_lost` em
   `tools/pt-assets/cuts.yaml` (este documento não altera o `cuts.yaml`).
2. Correr `./build.sh` (demora uns 6 minutos) — regenera automaticamente o
   `.avi` e o `.wav` de cada clip a partir do master, com escrita atómica
   (só substitui os ficheiros de produção depois de tudo passar a
   verificação de loudness).
3. Correr `./preview.sh` e conferir `preview/contact-sheet.png` outra vez.

`attract_demo`, `hello_hello` e `have_luck` ficam como estão — não há
timecode melhor para propor (ver notas 1, 2 e a nota do `have_luck` acima).

### Parte B (falas dos minijogos)

1. Gravar cada fala nova com a duração exata indicada na tabela (ao
   centésimo) — usar a duração como alvo fixo no DAW, não "aproximadamente".
2. Guardar com o **mesmo nome de ficheiro** da fala original (ex.: a versão
   PT de `005-01.wav` chama-se também `005-01.wav`).
3. **Antes de substituir, copiar os originais para um sítio à parte**
   (ex.: `hugo-assets/gold/BigFile-es-backup/`) — não há nenhuma cópia de
   segurança automática, e depois de sobrescrever não há como voltar atrás.
4. Substituir o ficheiro no sítio exato onde já está, dentro da BigFile:
   - Floresta: `hugo-assets/gold/BigFile/ForestData/speaks/`
   - Caverna: `hugo-assets/gold/BigFile/RopeOutroData/speak/`
5. Não é preciso mexer em código nem em cache manualmente. Confirmei no
   código: tanto o `audio-server/audio_server.py` (modo PA, colunas do
   computador) como o router do `bridge/adapters/web_adapter.py` (modo
   normal, telemóveis) resolvem o caminho do recurso **primeiro contra a
   BigFile** (`audio.assets_path` em `bridge/config.yaml`) **e só depois
   contra `game/resources`** — por isso substituir o ficheiro na BigFile é
   suficiente, o jogo não precisa de saber que mudou. O router converte para
   PCM16 e guarda em cache (`bridge/audio_cache/`) só na primeira vez que o
   ficheiro é pedido depois de mudar — a verificação é pela data de
   modificação do ficheiro de origem, por isso um WAV novo é reconvertido
   automaticamente, sem limpar nada à mão.
6. Os `.oos` de sincronismo labial **não mudam** — continuam a ditar a
   duração do estado do jogo, por isso o alerta do ponto 1 (duração exata)
   é o que realmente importa aqui, mais do que o formato do WAV em si.

Os 5 ficheiros de grito (`005-06`, `005-07`, `005-09`, `002-10`, `002-11`)
não entram neste processo — ficam com o WAV original.

---

## O que não consegui determinar

- **As propostas de fala PT não foram medidas com voz real** — foram
  calibradas por contagem de sílabas contra o espanhol, não por síntese e
  cronometragem de português. É o próximo passo antes de gravar a sério (ler
  em voz alta contra um cronómetro/DAW).
- Não confirmei por áudio (só por dedução de código) que `002-05` é falado
  pela Hugoline especificamente e não por outro membro genérico da família —
  o ficheiro `.oos`/código não nomeia a personagem nesta linha em concreto,
  só a par o deixa claro em `002-12`.
- Não fui ver se existe uma gravação de referência em inglês/dinamarquês
  (idioma original do jogo, antes da dobragem espanhola) que pudesse servir
  de segunda referência de timing — só usei o WAV espanhol da BigFile, que é
  o que está lá.
- Para `hello_hello`, não explorei se há uma saudação genérica (sem nome de
  finalista) escondida fora da janela horária que examinei em detalhe — dei a
  volta a todo o master pelas legendas à procura de "caverna"/"perder", mas
  não fiz o mesmo grão-fino (frame a frame) a toda a extensão para todos os
  6 finalistas, só para Marco e Ana Catarina como amostra do padrão.
- **Os timecodes do `pt-floresta.mkv` (Parte 2) têm precisão de ~0,1–0,2s,
  não ao centésimo.** Medi-os a partir do áudio extraído (whisper por clip +
  espetrograma), não inventados, mas as legendas automáticas do próprio
  vídeo têm um desvio conhecido de ~1,6s no fim (a última legenda aponta
  para 01:59.84, mas o ficheiro só tem 118,21s) — por isso usei sempre o
  áudio, nunca as legendas, para os números finais. Mesmo assim, antes de
  qualquer corte o Paulo deve confirmar o in/out num DAW — este documento é
  só análise, não cortei nada.
- Não ouvi os candidatos com os meus próprios "ouvidos" — a decisão de
  "limpa?" apoia-se em `silencedetect`/espetrograma (ausência de silêncio =
  música por baixo), não em audição direta. É um critério objetivo mas vale
  a pena o Paulo confirmar de ouvido antes de descartar `005-08`/`005-13`
  de vez.
