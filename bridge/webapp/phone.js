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
  ["sip", "connecting", "queue", "turn", "phone"].forEach(function (id) {
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
      case "pong":
        break; // heartbeat, nada a fazer
      case "audio":
        safeAudio("mensagem do jogo", function () {
          if (window.HugoAudio) window.HugoAudio.handleMessage(msg);
        });
        break;
    }
  }

  function onSlot(player, color) {
    clearInterval(turnCountdownTimer);
    var tag = document.getElementById("color-tag");
    tag.className = "color-tag c-" + color;
    document.getElementById("color-name").textContent = COLOR_NAME_PT[color] || color;
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
    reconnectFresh();
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

  // ---------------- UI: auscultador ----------------

  var handsetLabelEl = document.getElementById("handset-label");
  var preAnswerBlur = document.getElementById("pre-answer-blur");
  document.getElementById("handset-btn").addEventListener("click", function () {
    offHook = !offHook;
    vibrate(30);
    this.classList.toggle("off-hook", offHook);
    this.setAttribute("aria-label", offHook ? "Desligar" : "Atender e começar a jogar");
    handsetLabelEl.textContent = offHook ? "DESLIGAR" : "ATENDER";
    // CRÍTICO: `hidden` (não só opacidade) para o desfoque sair mesmo do
    // layout e deixar de comer toques do teclado — ver comentário em
    // phone.css junto de .pre-answer-blur.
    preAnswerBlur.hidden = offHook;
    send({ type: offHook ? "offhook" : "hangup" });
    document.getElementById("lcd-status").textContent = offHook ? "EM CHAMADA" : "PRONTO";
  });

  // ---------------- Splash ----------------
  //
  // 1,8s fixos e sai, nunca à espera do WebSocket — numa rede de evento lenta
  // ninguém deve ficar a olhar para um ecrã parado sem perceber porquê. A
  // ligação (connectWS, abaixo) continua a fazer-se por trás.

  var SPLASH_MS = 1800;
  var SPLASH_FADE_MS = 350;
  var splashEl = document.getElementById("splash");
  setTimeout(function () {
    splashEl.classList.add("hide");
    setTimeout(function () { splashEl.hidden = true; }, SPLASH_FADE_MS);
    // Acaba o silêncio até à próxima volta do loop de attract (16,4s): a
    // intro começa a tocar localmente já aqui. Se o AudioContext ainda não
    // estiver desbloqueado (sem gesto do utilizador), fica à espera em
    // silêncio dentro do próprio game-audio.js — nunca um erro por isto.
    safeAudio("intro attract", function () {
      if (window.HugoAudio) window.HugoAudio.requestIntro();
    });
  }, SPLASH_MS);

  // ---------------- Arranque ----------------
  //
  // Sem seletor: liga-se logo ao carregar a página. O ecrã "a ligar" já está
  // ativo por omissão no HTML; assim que chegar a mensagem "config" do
  // servidor é que se decide fila/teclado (web) ou o aviso curto (sip).

  wantConnected = true;
  connectWS();

})();
