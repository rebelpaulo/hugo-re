// phone.js — estado do telefone web: seletor de modo, WebSocket com reconexão,
// fila, oferta de vez e teclado. Protocolo fixo (ver bridge/webapp/README.md).

(function () {
  "use strict";

  // Caminho do WebSocket no mesmo host/porta que serviu esta página.
  var WS_PATH = "/ws";

  var COLOR_BY_INDEX = ["blue", "green", "red", "white"];
  var COLOR_NAME_PT = { blue: "azul", green: "verde", red: "vermelho", white: "branco" };

  var screens = {};
  ["mode", "signage", "connecting", "queue", "turn", "phone"].forEach(function (id) {
    screens[id] = document.getElementById("screen-" + id);
  });

  var reconnectDot = document.getElementById("reconnect-dot");

  var ws = null;
  var wantConnected = false;      // true depois de o utilizador escolher "jogar aqui"
  var reconnectDelay = 500;       // ms, com backoff exponencial até 8s
  var reconnectTimer = null;
  var pingTimer = null;
  var turnCountdownTimer = null;
  var offHook = false;

  function showScreen(id) {
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
      send({ type: "hello", mode: "web" });
      startPing();
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

  // ---------------- Mensagens do servidor ----------------

  function handleMessage(msg) {
    switch (msg.type) {
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
    document.getElementById("queue-ahead").textContent = ahead;
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
        // Prazo esgotado sem confirmar: o servidor oferece a outra pessoa.
        // Voltamos ao seletor de modo para tentar de novo.
        showScreen("mode");
      }
    }, 1000);
  }

  function onReleased() {
    clearInterval(turnCountdownTimer);
    showScreen("mode");
  }

  // ---------------- Ligar / iniciar jogo ----------------

  function startPlayHere() {
    requestFullscreenOnce();
    // Este clique é o gesto do utilizador que o iOS exige para desbloquear o
    // AudioContext — aproveitamo-lo já para desbloquear e começar a pré-carregar.
    if (window.HugoAudio) window.HugoAudio.start();
    wantConnected = true;
    showScreen("connecting");
    connectWS();
  }

  // ---------------- UI: seletor de modo ----------------

  document.getElementById("btn-play-here").addEventListener("click", startPlayHere);

  document.getElementById("btn-use-phone").addEventListener("click", function () {
    requestFullscreenOnce();
    showScreen("signage");
  });
  document.getElementById("btn-signage-back").addEventListener("click", function () {
    showScreen("mode");
  });

  // ---------------- UI: fila ----------------

  document.getElementById("btn-queue-leave").addEventListener("click", function () {
    send({ type: "hangup" });
    wantConnected = false;
    clearTimeout(reconnectTimer);
    if (ws) ws.close();
    showScreen("mode");
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

})();
