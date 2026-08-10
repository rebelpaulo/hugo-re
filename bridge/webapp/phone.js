// phone.js — estado do telefone web: WebSocket com reconexão, fila, oferta de
// vez e teclado. Protocolo fixo (ver bridge/adapters/web_adapter.py). O modo
// de entrada (web/sip) é decisão da produção em bridge/config.yaml, e os dois
// usos nunca se cruzam no mesmo evento — o servidor manda o modo logo na
// ligação, mensagem {"type":"config",...}; a webapp já não pergunta nada ao
// utilizador. Em modo sip a webapp não é usada de todo (não há QR no ecrã
// grande); se alguém lá chegar à mesma, mostra-se só um aviso curto.

(function () {
  "use strict";

  // Caminho do WebSocket no mesmo host/porta que serviu esta página.
  var WS_PATH = "/ws";

  var COLOR_BY_INDEX = ["blue", "green", "red", "white"];
  var COLOR_NAME_PT = { blue: "azul", green: "verde", red: "vermelho", white: "branco" };

  var screens = {};
  ["sip", "connecting", "queue", "turn", "phone", "name", "top10", "bye"].forEach(function (id) {
    screens[id] = document.getElementById("screen-" + id);
  });

  var reconnectDot = document.getElementById("reconnect-dot");

  var ws = null;
  var wantConnected = false;
  var reconnectDelay = 500;       // ms, com backoff exponencial até 8s
  var reconnectTimer = null;
  var pingTimer = null;
  var turnCountdownTimer = null;
  var offHook = false;

  var activeScreen = "connecting";

  function showScreen(id) {
    activeScreen = id;
    Object.keys(screens).forEach(function (k) {
      screens[k].classList.toggle("active", k === id);
    });
  }

  function requestFullscreenOnce() {
    var el = document.documentElement;
    try {
      if (el.requestFullscreen) el.requestFullscreen().catch(function () {});
      else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
    } catch (e) { /* iOS Safari sem suporte — ignora, meta tags de PWA tratam disto quando adicionado ao ecrã principal */ }
  }

  function vibrate(ms) {
    if (navigator.vibrate) navigator.vibrate(ms);
  }

  // O som é um extra: as políticas de autoplay, um AudioContext suspenso ou
  // uma implementação incompleta do browser nunca podem impedir a entrada.
  function safeAudio(label, action) {
    try {
      action();
    } catch (e) {
      console.warn("[audio] " + label + " falhou; a entrada continua utilizável.", e);
    }
  }

  // ---------------- Desbloqueio de áudio (exigência do browser) ----------------
  //
  // O AudioContext (game-audio.js) só pode ser desbloqueado dentro de um gesto
  // real do utilizador. Já não há um botão fixo "jogar aqui" para isso — a
  // entrada é automática. Em vez disso, aproveita-se o PRIMEIRO toque/tecla
  // que a pessoa fizer em qualquer lado da página, seja no teclado, no
  // auscultador ou só a explorar o ecrã. Só corre uma vez.

  var audioUnlocked = false;
  function unlockAudioOnce() {
    if (audioUnlocked) return;
    audioUnlocked = true;
    requestFullscreenOnce();
    safeAudio("desbloqueio", function () {
      if (window.HugoAudio) window.HugoAudio.start();
    });
  }
  document.addEventListener("pointerdown", unlockAudioOnce, { once: true, passive: true });
  document.addEventListener("keydown", unlockAudioOnce, { once: true });

  // ---------------- WebSocket ----------------

  function wsUrl() {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    return proto + "//" + location.host + WS_PATH;
  }

  function connectWS() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    clearTimeout(reconnectTimer);
    ws = new WebSocket(wsUrl());

    ws.onopen = function () {
      reconnectDelay = 500;
      reconnectDot.hidden = true;
      startPing();
      // Não manda "hello" aqui: espera-se pela mensagem "config" do servidor
      // para saber se este modo sequer entra na fila (ver handleMessage).
    };

    ws.onmessage = function (evt) {
      var msg;
      try { msg = JSON.parse(evt.data); } catch (e) { return; }
      handleMessage(msg);
    };

    ws.onclose = ws.onerror = function () {
      stopPing();
      if (!wantConnected) return;
      reconnectDot.hidden = false;
      reconnectTimer = setTimeout(connectWS, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 8000);
    };
  }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }

  function startPing() {
    stopPing();
    pingTimer = setInterval(function () { send({ type: "ping" }); }, 5000);
  }
  function stopPing() { clearInterval(pingTimer); }

  // Junta-se de novo à fila com uma ligação nova (novo source_id). Preciso
  // depois de "released": a sessão antiga fica "idle" no SlotManager e não há
  // mensagem própria no protocolo para lhe pedir lugar outra vez — só uma
  // ligação a começar de raiz (o mesmo caminho do carregamento da página).
  function reconnectFresh() {
    wantConnected = false;
    clearTimeout(reconnectTimer);
    if (ws) { try { ws.close(); } catch (e) { /* já fechado */ } }
    showScreen("connecting");
    wantConnected = true;
    connectWS();
  }

  // ---------------- Modo (decisão da produção, não do utilizador) ----------------

  function applyMode(mode) {
    if (mode === "sip") {
      // Este evento é só telefones físicos da sala — nunca entra na fila
      // nem ocupa lugar. Não devia haver forma normal de chegar aqui (sem
      // QR no ecrã grande), mas se acontecer (URL de outro evento), fica
      // só o aviso, nunca um ecrã em branco.
      wantConnected = false;
      clearTimeout(reconnectTimer);
      if (ws) { try { ws.close(); } catch (e) { /* já fechado */ } }
      showScreen("sip");
      return;
    }
    // web: entra direto na fila/teclado, sem perguntar nada.
    send({ type: "hello", mode: "web" });
  }

  // ---------------- Mensagens do servidor ----------------

  function handleMessage(msg) {
    switch (msg.type) {
      case "config":
        applyMode(msg.input_mode);
        break;
      case "slot":
        onSlot(msg.player, msg.color);
        break;
      case "queued":
        onQueued(msg.position, msg.ahead);
        break;
      case "your_turn":
        onYourTurn(msg.player, msg.seconds);
        break;
      case "released":
        onReleased();
        break;
      case "finished":
        onFinished();
        break;
      case "top10":
        onTop10(msg.entries, msg.own);
        break;
      case "pong":
        break; // heartbeat, nada a fazer
      case "audio":
        safeAudio("mensagem do jogo", function () {
          if (window.HugoAudio) window.HugoAudio.handleMessage(msg);
        });
        break;
    }
  }

  // Mostra o ícone do quadrante desta pessoa ("estás a jogar no ecrã: X").
  // É o mesmo ficheiro que o jogo desenha no canto do quadrante, e a ordem
  // segue `Game.positions` em game/game.py: 0 em cima à esquerda, 1 em cima à
  // direita, 2 em baixo à esquerda, 3 em baixo à direita. Sem lugar (ou
  // índice fora de gama) esconde a linha inteira — melhor nada do que apontar
  // para o sítio errado.
  function markQuadrant(player) {
    var line = document.getElementById("screen-here");
    var icon = document.getElementById("screen-here-icon");
    if (typeof player !== "number" || player < 0 || player > 3) {
      line.hidden = true;
      icon.removeAttribute("src");
      return;
    }
    icon.src = "img/phone" + player + ".png";
    icon.alt = "quadrante " + (player + 1);
    line.hidden = false;
  }

  function onSlot(player, color) {
    clearInterval(turnCountdownTimer);
    var tag = document.getElementById("color-tag");
    tag.className = "color-tag c-" + color;
    document.getElementById("color-name").textContent = COLOR_NAME_PT[color] || color;
    markQuadrant(player);
    document.getElementById("lcd-status").textContent = "PRONTO";
    document.getElementById("lcd-digits").innerHTML = "&nbsp;";
    // Repõe sempre o estado "por atender": um "slot" é sempre uma sessão
    // nova aos olhos do servidor (offhook implícito a false), mas o var
    // `offHook` local e as classes do auscultador só mudam por clique — sem
    // isto, uma reconexão (released -> novo slot) herdava o estado antigo e
    // o desfoque ficava escondido para sempre, com o teclado destapado sem
    // ninguém ter atendido.
    offHook = false;
    var handsetBtn = document.getElementById("handset-btn");
    handsetBtn.classList.remove("off-hook");
    handsetBtn.setAttribute("aria-label", "Atender e começar a jogar");
    handsetLabelEl.textContent = "ATENDER";
    preAnswerBlur.hidden = false;
    showScreen("phone");
  }

  function onQueued(position, ahead) {
    document.getElementById("queue-position").textContent = position;
    // Plural à mão: "pessoa(s)" lê-se mal, e isto vai estar à frente de
    // centenas de pessoas. Zero à frente merece a sua própria frase.
    var linha;
    if (ahead <= 0) {
      linha = "És o próximo";
    } else if (ahead === 1) {
      linha = "1 pessoa à frente";
    } else {
      linha = ahead + " pessoas à frente";
    }
    document.getElementById("queue-ahead-line").textContent = linha;
    showScreen("queue");
  }

  function onYourTurn(player, seconds) {
    var colorName = COLOR_BY_INDEX[player];
    document.getElementById("turn-player").textContent = (player + 1);
    document.getElementById("turn-color-name").textContent = COLOR_NAME_PT[colorName] || "—";
    var secEl = document.getElementById("turn-seconds");
    var remaining = seconds;
    secEl.textContent = remaining;
    showScreen("turn");
    vibrate(60);
    clearInterval(turnCountdownTimer);
    turnCountdownTimer = setInterval(function () {
      remaining -= 1;
      secEl.textContent = Math.max(remaining, 0);
      if (remaining <= 0) {
        clearInterval(turnCountdownTimer);
        // Prazo esgotado sem confirmar: o servidor já reenfileira sozinho
        // (offer_expired -> request_slot, ver web_adapter.py) — só há que
        // esperar pela próxima mensagem "queued".
        showScreen("connecting");
      }
    }, 1000);
  }

  function onReleased() {
    clearInterval(turnCountdownTimer);
    // Apaga o quadrante: o lugar seguinte pode ser outro, e um mapa a apontar
    // para o quadrante antigo manda a pessoa olhar para o sítio errado.
    markQuadrant(-1);
    reconnectFresh();
  }

  // A partida acabou (jogo entrou no ecrã de fim — ver
  // game/tv_show/ending.py + game/tv_show/in_cave.py:19). Primeira vez que
  // o jogo "fala de volta" para o bridge: o telemóvel passa para o ecrã de
  // nome, e depois de submeter fica no top10 — sem volta, ver onTop10.
  function onFinished() {
    clearInterval(turnCountdownTimer);
    resetNameEntry();
    showScreen("name");
    vibrate(60);
  }

  function onTop10(entries, own) {
    var list = document.getElementById("top10-list");
    list.innerHTML = "";
    (entries || []).forEach(function (entry, idx) {
      var isOwn = !!own && entry.name === own.name && entry.score === own.score;
      var li = document.createElement("li");
      li.className = "top10-row" + (isOwn ? " top10-own" : "");

      var rank = document.createElement("span");
      rank.className = "top10-rank";
      rank.textContent = (idx + 1) + "º";

      var name = document.createElement("span");
      name.className = "top10-name";
      name.textContent = entry.name;

      var score = document.createElement("span");
      score.className = "top10-score";
      score.textContent = entry.score;

      li.appendChild(rank);
      li.appendChild(name);
      li.appendChild(score);
      list.appendChild(li);
    });
    showScreen("top10");
    // Último ecrã: de propósito não há nenhum listener de tecla/toque daqui
    // para a frente que volte ao jogo — o bloqueio é a rotação (ver
    // bridge/README.md e o ticket). Só lendo o QR outra vez.
  }

  // ---------------- UI: sinalética ----------------

  // (ligações dos links/botão de voltar já feitas acima, junto de applyMode)

  // ---------------- UI: fila ----------------

  document.getElementById("btn-queue-leave").addEventListener("click", function () {
    send({ type: "hangup" });
    wantConnected = false;
    clearTimeout(reconnectTimer);
    if (ws) ws.close();
    showScreen("connecting");
  });

  // ---------------- UI: confirmar vez ----------------

  document.getElementById("btn-confirm").addEventListener("click", function () {
    clearInterval(turnCountdownTimer);
    vibrate(30);
    send({ type: "confirm" });
  });

  // ---------------- UI: teclado ----------------

  var digitsEl = document.getElementById("lcd-digits");
  var digitsBuffer = "";

  // Mitigação do lado do cliente para um atalho de debug do PRÓPRIO JOGO:
  // em game/tv_show/attract.py, enquanto ninguém descolgou o auscultador
  // (offHook === false), o "4" e o "6" saltam para InScoreboard/InCave com
  // pontuações fabricadas (1000 pontos, sacos inventados) — não é dados
  // reais de ninguém, e num evento com centenas de pessoas a carregar em
  // tudo isso acontece na primeira meia hora. Não podemos tocar em game/
  // (não é write set desta mudança, é partilhado com o upstream), por isso
  // a correção definitiva é lá — aqui só se evita ENVIAR essas duas teclas
  // ao servidor antes de se entrar na chamada. A tecla continua a existir,
  // a afundar, a vibrar e a tocar o tom (código abaixo, comum a todas as
  // teclas) — só não sai para a rede, para não parecer avariada.
  var BLOCKED_BEFORE_ENTRY = { "4": true, "6": true };

  document.querySelectorAll(".key").forEach(function (btn) {
    // `pointerdown` e não `click`: o click só dispara ao LARGAR o dedo, o que
    // num teclado se sente lento e faz duvidar que a tecla tenha registado.
    // Assim a tecla afunda, vibra e soa no instante do toque, como um
    // telefone a sério. O preventDefault evita o click fantasma a seguir.
    btn.addEventListener("pointerdown", function (evento) {
      evento.preventDefault();
      var key = btn.getAttribute("data-key");
      // A tecla é a acção principal. Entra primeiro e nunca depende do som.
      // Excepto o 4 e o 6 antes de entrar (ver BLOCKED_BEFORE_ENTRY acima).
      if (!offHook && BLOCKED_BEFORE_ENTRY[key]) {
        console.warn("[phone] tecla " + key + " travada antes de entrar (atalho de debug do jogo) — ver BLOCKED_BEFORE_ENTRY em phone.js");
      } else {
        send({ type: "press", key: key });
      }

      // "5" é a tecla que inicia o jogo (ver cartão do jogo) — a partir
      // daqui o áudio passa a ser todo conduzido pelo servidor, e a intro
      // local cala-se para nunca tocar por cima do que o jogo mandar.
      if (key === "5") {
        safeAudio("parar intro attract", function () {
          if (window.HugoAudio) window.HugoAudio.stopIntro();
        });
      }

      btn.classList.add("pressed");
      setTimeout(function () { btn.classList.remove("pressed"); }, 120);

      digitsBuffer = (digitsBuffer + key).slice(-12);
      digitsEl.textContent = digitsBuffer;

      vibrate(30);
      safeAudio("tom DTMF", function () {
        if (window.playDTMF) window.playDTMF(key);
      });
    });
  });

  // ---------------- UI: nome (fim de partida) ----------------
  //
  // Teclado próprio, gerado aqui em vez de escrito à mão no HTML (são 39
  // teclas) — o teclado do sistema tapa o ecrã e não combina com o resto.
  // Mesmo limite do servidor (ver bridge/score_store.py: MAX_NAME_LEN):
  // 8 caracteres, só A-Z/0-9/espaço, o servidor normaliza/filtra na mesma
  // por segurança — este limite é só para a pessoa ver o que está a fazer.

  var NAME_MAX_LEN = 8;
  var nameBuffer = "";
  var nameSubmitted = false;
  var nameBufferEl = document.getElementById("name-buffer");
  var namepadEl = document.getElementById("namepad");

  function resetNameEntry() {
    nameBuffer = "";
    nameSubmitted = false;
    renderNameBuffer();
    setNamepadDisabled(false);
  }

  function renderNameBuffer() {
    var shown = nameBuffer.split("");
    while (shown.length < NAME_MAX_LEN) shown.push("_");
    nameBufferEl.textContent = shown.join(" ");
  }

  function setNamepadDisabled(disabled) {
    namepadEl.querySelectorAll(".namekey").forEach(function (btn) {
      btn.disabled = disabled;
    });
  }

  function buildNamepad() {
    var chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789".split("");
    chars.forEach(function (ch) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "namekey";
      btn.textContent = ch;
      btn.addEventListener("pointerdown", function (evento) {
        evento.preventDefault();
        pressNamekey(btn, function () {
          if (nameBuffer.length < NAME_MAX_LEN) nameBuffer += ch;
        });
      });
      namepadEl.appendChild(btn);
    });

    var del = document.createElement("button");
    del.type = "button";
    del.className = "namekey namekey-del";
    del.textContent = "⌫";
    del.setAttribute("aria-label", "Apagar");
    del.addEventListener("pointerdown", function (evento) {
      evento.preventDefault();
      pressNamekey(del, function () {
        nameBuffer = nameBuffer.slice(0, -1);
      });
    });
    namepadEl.appendChild(del);

    var space = document.createElement("button");
    space.type = "button";
    space.className = "namekey namekey-space";
    space.textContent = "ESPAÇO";
    space.addEventListener("pointerdown", function (evento) {
      evento.preventDefault();
      pressNamekey(space, function () {
        if (nameBuffer.length < NAME_MAX_LEN) nameBuffer += " ";
      });
    });
    namepadEl.appendChild(space);

    var ok = document.createElement("button");
    ok.type = "button";
    ok.className = "namekey namekey-ok";
    ok.textContent = "OK";
    ok.addEventListener("pointerdown", function (evento) {
      evento.preventDefault();
      pressNamekey(ok, submitName);
    });
    namepadEl.appendChild(ok);
  }

  function pressNamekey(btn, action) {
    if (nameSubmitted) return;
    action();
    renderNameBuffer();
    btn.classList.add("pressed");
    setTimeout(function () { btn.classList.remove("pressed"); }, 120);
    vibrate(20);
  }

  function submitName() {
    if (nameSubmitted) return;
    nameSubmitted = true;
    setNamepadDisabled(true);
    send({ type: "name", name: nameBuffer });
  }

  buildNamepad();

  // ---------------- UI: auscultador ----------------

  var handsetLabelEl = document.getElementById("handset-label");
  var preAnswerBlur = document.getElementById("pre-answer-blur");
  document.getElementById("handset-btn").addEventListener("click", function () {
    if (offHook) {
      // Desligar: quem sai não volta sem ler o QR outra vez. Fecha a
      // ligação (mesmo padrão do "sair da fila" acima) para o servidor
      // nunca poder mandar nada que reabra o ecrã de atender — o botão
      // ATENDER fica no ecrã "phone", que passa a inativo, e não há
      // caminho de volta a partir do ecrã de despedida.
      offHook = false;
      vibrate(30);
      send({ type: "hangup" });
      wantConnected = false;
      clearTimeout(reconnectTimer);
      clearInterval(turnCountdownTimer);
      if (ws) { try { ws.close(); } catch (e) { /* já fechado */ } }
      showScreen("bye");
      // O jogo já não conduz o áudio (desligámos) — volta a tocar o genérico
      // no ecrã de despedida, como fecho. O áudio já está desbloqueado a esta
      // altura (a pessoa jogou), portanto isto toca mesmo.
      safeAudio("genérico na despedida", function () {
        if (window.HugoAudio) window.HugoAudio.requestIntro();
      });
      return;
    }
    // Atender: começa a chamada, o jogo assume o áudio a partir daqui.
    offHook = true;
    vibrate(30);
    this.classList.add("off-hook");
    this.setAttribute("aria-label", "Desligar");
    handsetLabelEl.textContent = "DESLIGAR";
    // CRÍTICO: `hidden` (não só opacidade) para o desfoque sair mesmo do
    // layout e deixar de comer toques do teclado — ver comentário em
    // phone.css junto de .pre-answer-blur.
    preAnswerBlur.hidden = true;
    send({ type: "offhook" });
    document.getElementById("lcd-status").textContent = "EM CHAMADA";
  });

  // ---------------- Splash ----------------
  //
  // Espera pelo primeiro toque — o AudioContext só desbloqueia dentro de um
  // gesto real do utilizador (regra do browser, inultrapassável), por isso
  // já não há saída automática por tempo: sem toque, não há som, e o cliente
  // ficava a ouvir tudo em silêncio até mexer. O toque faz, por esta ordem:
  // desbloqueia o áudio, esconde a splash (mesmo crossfade de sempre) e
  // arranca o genérico local, que fica a tocar em loop no ecrã de atender
  // até o jogador carregar em ATENDER/5 (aí `stopIntro` cala-o — ver
  // game-audio.js). A ligação (connectWS, abaixo) continua a fazer-se por
  // trás, sem depender disto.

  var SPLASH_FADE_MS = 350;
  var splashEl = document.getElementById("splash");
  splashEl.addEventListener("pointerdown", function () {
    unlockAudioOnce();
    splashEl.classList.add("hide");
    setTimeout(function () { splashEl.hidden = true; }, SPLASH_FADE_MS);
    safeAudio("intro attract", function () {
      if (window.HugoAudio) window.HugoAudio.requestIntro();
    });
  }, { once: true, passive: true });

  // ---------------- Arranque ----------------
  //
  // Sem seletor: liga-se logo ao carregar a página. O ecrã "a ligar" já está
  // ativo por omissão no HTML; assim que chegar a mensagem "config" do
  // servidor é que se decide fila/teclado (web) ou o aviso curto (sip).

  wantConnected = true;
  connectWS();

})();
