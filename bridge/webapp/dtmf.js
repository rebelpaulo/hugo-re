// dtmf.js — tom DTMF autêntico gerado localmente (duas sinusoides somadas),
// tal como um telefone de teclas a sério. Zero dependências, Web Audio API pura.

(function () {
  "use strict";

  // Linhas e colunas standard DTMF (Hz).
  var ROW_FREQ = { "1": 697, "2": 697, "3": 697,
                    "4": 770, "5": 770, "6": 770,
                    "7": 852, "8": 852, "9": 852,
                    "*": 941, "0": 941, "#": 941 };
  var COL_FREQ = { "1": 1209, "4": 1209, "7": 1209, "*": 1209,
                    "2": 1336, "5": 1336, "8": 1336, "0": 1336,
                    "3": 1477, "6": 1477, "9": 1477, "#": 1477 };

  var ctx = null;

  // Exposto para prova/depuração: guarda o último tom gerado (tecla + duas
  // frequências reais dos osciladores), para inspecionar sem adivinhar.
  window.__dtmfDebug = null;

  function getContext() {
    if (!ctx) {
      var AC = window.AudioContext || window.webkitAudioContext;
      ctx = new AC();
    }
    if (ctx.state === "suspended") ctx.resume();
    return ctx;
  }

  // Toca o tom DTMF da tecla: duas sinusoides (linha + coluna) somadas,
  // com envelope curto para não estalar.
  function playDTMF(key) {
    var low = ROW_FREQ[key];
    var high = COL_FREQ[key];
    if (!low || !high) return null;

    var audioCtx = getContext();
    var now = audioCtx.currentTime;
    var dur = 0.12;

    var oscLow = audioCtx.createOscillator();
    var oscHigh = audioCtx.createOscillator();
    oscLow.type = "sine";
    oscHigh.type = "sine";
    oscLow.frequency.value = low;
    oscHigh.frequency.value = high;

    var gain = audioCtx.createGain();
    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(0.28, now + 0.008);
    gain.gain.setValueAtTime(0.28, now + dur - 0.02);
    gain.gain.linearRampToValueAtTime(0, now + dur);

    oscLow.connect(gain);
    oscHigh.connect(gain);
    gain.connect(audioCtx.destination);

    oscLow.start(now);
    oscHigh.start(now);
    oscLow.stop(now + dur);
    oscHigh.stop(now + dur);

    var debugInfo = { key: key, lowHz: low, highHz: high, at: now };
    window.__dtmfDebug = debugInfo;
    console.log("[dtmf] tecla=" + key + " linha=" + low + "Hz coluna=" + high + "Hz");

    return debugInfo;
  }

  window.playDTMF = playDTMF;
})();
