// game-audio.js — áudio do jogo tocado no telemóvel de cada jogador.
//
// Recebe mensagens {"type":"audio",...} do WebSocket (ver phone.js) e toca-as
// com a Web Audio API. Os sons são pré-carregados e descodificados a partir
// do bridge (`/audio/<recurso>`, já convertidos para 16 bits/44.1kHz/mono —
// ver bridge/adapters/web_adapter.py) assim que `start()` é chamado — o que
// phone.js faz no PRIMEIRO gesto do utilizador na página (toque ou tecla),
// porque é isso que desbloqueia o AudioContext no iOS (não há botão fixo
// "jogar aqui" para isso desde que o seletor de modo foi removido).
//
// Protocolo (novo tipo, não muda o resto):
//   {"type":"audio","action":"play","resource":"...","loops":0,"id":7}
//   {"type":"audio","action":"stop","id":7}
//
// Intro de attract local (silêncio entre a splash e o início do jogo): o
// ciclo do jogo só manda o attract_demo.wav a quem entra a meio do loop de
// 16,4s — quem chega antes disso ficava calado até à volta seguinte. Por
// isso a cópia local começa a tocar sozinha assim que a splash sai
// (requestIntro, chamado por phone.js) e cala-se logo que o jogo tome conta
// do som: ou o jogador carrega no 5, ou chega QUALQUER mensagem "audio" do
// servidor (mesmo que seja o mesmo ficheiro, na volta do loop) — o áudio
// conduzido pelo jogo manda sempre, para nunca haver duas cópias
// desfasadas ao mesmo tempo. Vive à parte de `playing{}` (ids do jogo) para
// nunca colidir com um id real.

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

  // ---------------- Intro de attract local ----------------

  var INTRO_RESOURCE = "audio_for_videos/pt/attract_demo.wav";
  // Ambiente, não é o jogo — mais baixa do que o som do jogo (que toca a
  // 1.0, sem gain próprio, em scheduleSource). ~40% abaixo.
  var INTRO_VOLUME = 0.6;
  var introWantsToPlay = false;   // entre a saída da splash e o 5 / áudio do jogo
  var introSource = null;         // BufferSourceNode ativo, ou null

  function getContext() {
    if (!ctx) {
      var AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) throw new Error("Web Audio API indisponível");
      ctx = new AC();
    }
    return ctx;
  }

  function reportFailure(label, err) {
    console.warn("[audio] " + label + "; a aplicação continua utilizável.", err);
  }

  function resumeContext(audioCtx) {
    if (audioCtx.state !== "suspended") return;
    try {
      var result = audioCtx.resume();
      if (result && result.catch) result.catch(function (err) { reportFailure("não foi possível retomar o contexto", err); });
    } catch (err) {
      reportFailure("não foi possível retomar o contexto", err);
    }
  }

  // ---------------- Arranque (chamado no primeiro gesto do utilizador) ----------------

  function start() {
    if (started) return;
    started = true;

    try {
      resumeContext(getContext());
    } catch (err) {
      reportFailure("não foi possível iniciar o áudio", err);
      return;
    }

    showBanner("A preparar o som deste telemóvel…", 0);
    var manifestRequest;
    try {
      manifestRequest = fetch("/audio-manifest.json");
    } catch (err) {
      reportFailure("falha a pedir o manifesto", err);
      hideBanner();
      return;
    }
    manifestRequest
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

    var request;
    try {
      request = fetch("/audio/" + resource);
    } catch (err) {
      reportFailure("recurso falhou: " + resource, err);
      return Promise.resolve(null);
    }
    var promise = request
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.arrayBuffer();
      })
      .then(function (data) { return getContext().decodeAudioData(data); })
      .then(function (buffer) {
        buffers[resource] = buffer;
        loadedCount += 1;
        updateBanner();
        if (resource === INTRO_RESOURCE) tryStartIntro();
        return buffer;
      })
      .catch(function (err) {
        reportFailure("recurso falhou: " + resource, err);
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
    try {
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
    } catch (err) {
      delete playing[id];
      reportFailure("não foi possível tocar " + resource, err);
    }
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

  // ---------------- Intro de attract local ----------------

  // Chamado por phone.js quando a splash sai. Se o AudioContext ainda não
  // estiver desbloqueado (sem gesto do utilizador ainda) ou o ficheiro ainda
  // não tiver acabado de pré-carregar, fica à espera em silêncio — tryStartIntro
  // volta a ser chamado quando `start()` desbloquear o contexto (unlockAudioOnce
  // em phone.js) e quando o recurso concreto acabar de carregar (loadResource).
  function requestIntro() {
    introWantsToPlay = true;
    tryStartIntro();
  }

  function tryStartIntro() {
    if (!introWantsToPlay || introSource || !started) return;
    var buffer = buffers[INTRO_RESOURCE];
    if (!buffer) return; // ainda não pré-carregado — espera pelo hook em loadResource
    try {
      var audioCtx = getContext();
      var gain = audioCtx.createGain();
      gain.gain.value = INTRO_VOLUME;
      gain.connect(audioCtx.destination);
      var source = audioCtx.createBufferSource();
      source.buffer = buffer;
      source.loop = true;
      source.connect(gain);
      source.onended = function () {
        if (introSource === source) introSource = null;
      };
      introSource = source;
      source.start(0);
    } catch (err) {
      introSource = null;
      reportFailure("intro local falhou", err);
    }
  }

  // Chamado ao carregar no 5 (phone.js) e sempre que chega qualquer mensagem
  // "audio" do servidor (handleMessage, abaixo) — o áudio conduzido pelo jogo
  // manda sempre, mesmo a meio de uma frase da intro.
  function stopIntro() {
    introWantsToPlay = false;
    if (introSource) {
      try { introSource.onended = null; introSource.stop(0); } catch (e) { /* já tinha acabado */ }
      introSource = null;
    }
  }

  // ---------------- Mensagens do servidor ----------------

  function handleMessage(msg) {
    try {
      // Qualquer mensagem de áudio do jogo cala a intro local, mesmo que a
      // ação seja "stop" ou um recurso diferente — é o próprio jogo a tomar
      // conta do som, e as duas cópias tocando juntas é a cacofonia que
      // isto existe para evitar.
      stopIntro();
      if (msg.action === "play") {
        play(msg.resource, typeof msg.loops === "number" ? msg.loops : 0, msg.id);
      } else if (msg.action === "stop") {
        stop(msg.id);
      }
    } catch (err) {
      reportFailure("mensagem do jogo falhou", err);
    }
  }

  // Exposto para prova/depuração (mesmo espírito de window.__dtmfDebug em
  // dtmf.js): estado real do AudioContext, sem adivinhar.
  function state() {
    return ctx ? ctx.state : "not-created";
  }

  // Estado real da intro local, sem adivinhar (mesmo espírito de state()).
  function introState() {
    return { wantsToPlay: introWantsToPlay, playing: !!introSource };
  }

  window.HugoAudio = {
    start: start,
    handleMessage: handleMessage,
    state: state,
    requestIntro: requestIntro,
    stopIntro: stopIntro,
    introState: introState
  };
})();
