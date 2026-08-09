// phone.js — estado do telefone web: WebSocket com reconexão, fila, oferta de
// vez e teclado. Protocolo fixo (ver bridge/adapters/web_adapter.py). O modo
// de entrada (web/sip/both) é decisão da produção em bridge/config.yaml — o
// servidor manda-o logo na ligação, mensagem {"type":"config",...}; a webapp
// já não pergunta nada ao utilizador.

(function () {
  "use strict";

  // Caminho do WebSocket no mesmo host/porta que serviu esta página.
  var WS_PATH = "/ws";

  var COLOR_BY_INDEX = ["blue", "green", "red", "white"];
  var COLOR_NAME_PT = { blue: "azul", green: "verde", red: "vermelho", white: "branco" };

  var screens = {};
  ["signage", "connecting", "queue", "turn", "phone"].forEach(function (id) {
    screens[id] = document.getElementById("screen-" + id);
  });

  var reconnectDot = document.getElementById("reconnect-dot");
  var signageBackBtn = document.getElementById("btn-signage-back");
  var signageLinks = document.querySelectorAll(".signage-link");

  var ws = null;
  var wantConnected = false;
  var reconnectDelay = 500;       // ms, com backoff exponencial até 8s
  var reconnectTimer = null;
  var pingTimer = null;
  var turnCountdownTimer = null;
  var offHook = false;

  var currentMode = null;         // "web" | "sip" | "both", vindo do servidor
  var activeScreen = "connecting";
  var preSignageScreen = "connecting"; // ecrã a que "← voltar" da sinalética regressa

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
    if (window.HugoAudio) window.HugoAudio.start();
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

  function updateSignageLinksVisibility() {
    var show = currentMode === "both";
    signageLinks.forEach(function (el) { el.hidden = !show; });
  }

  function applyMode(mode) {
    currentMode = mode;
    if (mode === "sip") {
      // Só sinalética: nunca entra na fila nem ocupa lugar.
      wantConnected = false;
      clearTimeout(reconnectTimer);
      if (ws) { try { ws.close(); } catch (e) { /* já fechado */ } }
      signageBackBtn.hidden = true; // não há outro ecrã para onde voltar
      preSignageScreen = "connecting";
      showScreen("signage");
      return;
    }
    // web ou both: entra direto na fila/teclado, sem perguntar nada.
    signageBackBtn.hidden = false;
    updateSignageLinksVisibility();
    send({ type: "hello", mode: "web" });
  }

  function goToSignage() {
    preSignageScreen = activeScreen;
    showScreen("signage");
  }
  signageLinks.forEach(function (el) { el.addEventListener("click", goToSignage); });
  signageBackBtn.addEventListener("click", function () {
    showScreen(preSignageScreen);
  });

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
        if (window.HugoAudio) window.HugoAudio.handleMessage(msg);
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
    if (currentMode === "both") {
      preSignageScreen = "connecting";
      showScreen("signage");
    } else {
      showScreen("connecting");
    }
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

  document.querySelectorAll(".key").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var key = btn.getAttribute("data-key");
      vibrate(30);
      window.playDTMF(key);
      send({ type: "press", key: key });

      btn.classList.add("pressed");
      setTimeout(function () { btn.classList.remove("pressed"); }, 120);

      digitsBuffer = (digitsBuffer + key).slice(-12);
      digitsEl.textContent = digitsBuffer;
    });
  });

  // ---------------- UI: auscultador ----------------

  document.getElementById("handset-btn").addEventListener("click", function () {
    offHook = !offHook;
    vibrate(30);
    this.classList.toggle("off-hook", offHook);
    send({ type: offHook ? "offhook" : "hangup" });
    document.getElementById("lcd-status").textContent = offHook ? "EM CHAMADA" : "PRONTO";
  });

  // ---------------- Arranque ----------------
  //
  // Sem seletor: liga-se logo ao carregar a página. O ecrã "a ligar" já está
  // ativo por omissão no HTML; assim que chegar a mensagem "config" do
  // servidor é que se decide fila/teclado (web/both) ou sinalética (sip).

  wantConnected = true;
  connectWS();

})();
