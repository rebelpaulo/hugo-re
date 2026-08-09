// game-audio.js — áudio do jogo tocado no telemóvel de cada jogador.
//
// Recebe mensagens {"type":"audio",...} do WebSocket (ver phone.js) e toca-as
// com a Web Audio API. Os sons são pré-carregados e descodificados a partir
// do bridge (`/audio/<recurso>`, já convertidos para 16 bits/44.1kHz/mono —
// ver bridge/adapters/web_adapter.py) assim que o jogador escolhe "jogar
// aqui", porque é esse clique que desbloqueia o AudioContext no iOS.
//
// Protocolo (novo tipo, não muda o resto):
//   {"type":"audio","action":"play","resource":"...","loops":0,"id":7}
//   {"type":"audio","action":"stop","id":7}

(function () {
  "use strict";

  var ctx = null;
  var started = false;
  var buffers = {};          // resource -> AudioBuffer
  var pending = {};          // resource -> Promise<AudioBuffer>
  var playing = {};          // id -> { source, resource, loops, remaining }
  var manifest = [];
  var loadedCount = 0;

  var bannerEl = null;
  var bannerTimer = null;

  function getContext() {
    if (!ctx) {
      var AC = window.AudioContext || window.webkitAudioContext;
      ctx = new AC();
    }
    return ctx;
  }

  // ---------------- Arranque (chamado no primeiro gesto do utilizador) ----------------

  function start() {
    if (started) return;
    started = true;

    var audioCtx = getContext();
    if (audioCtx.state === "suspended") audioCtx.resume();

    showBanner("A preparar o som deste telemóvel…", 0);
    fetch("/audio-manifest.json")
      .then(function (r) { return r.json(); })
      .then(function (list) {
        manifest = list || [];
        if (manifest.length === 0) {
          hideBanner();
          return;
        }
        updateBanner();
        return Promise.all(manifest.map(loadResource));
      })
      .then(function () {
        hideBanner();
        checkOutputHint();
      })
      .catch(function (err) {
        console.warn("[audio] falha a carregar o manifesto:", err);
        hideBanner();
      });
  }

  function loadResource(resource) {
    if (buffers[resource]) return Promise.resolve(buffers[resource]);
    if (pending[resource]) return pending[resource];

    var promise = fetch("/audio/" + resource)
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.arrayBuffer();
      })
      .then(function (data) { return getContext().decodeAudioData(data); })
      .then(function (buffer) {
        buffers[resource] = buffer;
        loadedCount += 1;
        updateBanner();
        return buffer;
      })
      .catch(function (err) {
        console.warn("[audio] recurso falhou: " + resource, err);
        loadedCount += 1;
        updateBanner();
        return null;
      })
      .finally(function () { delete pending[resource]; });

    pending[resource] = promise;
    return promise;
  }

  // ---------------- Progresso discreto ----------------

  function showBanner(text, autoHideMs) {
    if (!bannerEl) {
      bannerEl = document.createElement("div");
      bannerEl.id = "audio-banner";
      bannerEl.style.cssText =
        "position:fixed;left:8px;right:8px;bottom:8px;padding:6px 10px;" +
        "font:12px -apple-system,sans-serif;color:#e8e6d9;background:rgba(20,20,18,.72);" +
        "border-radius:6px;text-align:center;z-index:9999;pointer-events:none;" +
        "transition:opacity .3s;";
      document.body.appendChild(bannerEl);
    }
    clearTimeout(bannerTimer);
    bannerEl.style.opacity = "1";
    bannerEl.textContent = text;
    if (autoHideMs) bannerTimer = setTimeout(hideBanner, autoHideMs);
  }

  function updateBanner() {
    if (!bannerEl || manifest.length === 0) return;
    bannerEl.textContent = "A carregar sons… " + loadedCount + "/" + manifest.length;
  }

  function hideBanner() {
    if (!bannerEl) return;
    bannerEl.style.opacity = "0";
    var el = bannerEl;
    setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 350);
    bannerEl = null;
  }

  // O browser não deixa uma página saber o volume real do telemóvel nem se o
  // interruptor de silêncio está activo — não há API para isso (limitação de
  // privacidade do próprio browser). O melhor que conseguimos é um aviso
  // genérico, uma vez, depois do som estar pronto.
  function checkOutputHint() {
    showBanner("Som pronto — confirma que o telemóvel não está em silêncio.", 4000);
  }

  // ---------------- Reprodução ----------------

  function scheduleSource(id, resource, buffer, loops, remaining) {
    var entry = playing[id];
    if (!entry) return; // foi parado entretanto
    var audioCtx = getContext();
    var source = audioCtx.createBufferSource();
    source.buffer = buffer;
    source.loop = loops === -1;
    source.connect(audioCtx.destination);
    entry.source = source;
    entry.remaining = remaining;
    source.onended = function () {
      if (!playing[id] || playing[id].source !== source) return; // já substituído/parado
      if (loops !== -1 && remaining > 0) {
        scheduleSource(id, resource, buffer, loops, remaining - 1);
      } else {
        delete playing[id];
      }
    };
    source.start(0);
  }

  function play(resource, loops, id) {
    if (typeof id !== "number") return;
    stop(id); // um PLAY reaproveitando o mesmo id substitui o que estava a tocar
    playing[id] = { source: null, resource: resource, loops: loops };

    var buffer = buffers[resource];
    if (buffer) {
      scheduleSource(id, resource, buffer, loops, loops);
      return;
    }
    // Ainda não pré-carregado (recurso fora do manifesto, ou a preparação
    // falhou) — carrega agora, best-effort, e toca assim que estiver pronto.
    loadResource(resource).then(function (loaded) {
      if (!loaded || !playing[id]) return;
      scheduleSource(id, resource, loaded, loops, loops);
    });
  }

  function stop(id) {
    var entry = playing[id];
    if (!entry) return;
    delete playing[id];
    if (entry.source) {
      try { entry.source.onended = null; entry.source.stop(0); } catch (e) { /* já tinha acabado */ }
    }
  }

  // ---------------- Mensagens do servidor ----------------

  function handleMessage(msg) {
    if (msg.action === "play") {
      play(msg.resource, typeof msg.loops === "number" ? msg.loops : 0, msg.id);
    } else if (msg.action === "stop") {
      stop(msg.id);
    }
  }

  window.HugoAudio = { start: start, handleMessage: handleMessage };
})();
