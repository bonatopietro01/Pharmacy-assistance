// Lettura di codici dalla telecamera, tutta nel browser.
// Ordine dei lettori: BarcodeDetector del browser → ZXing locale (/vendor/zxing.min.js, se installato
// con INSTALLA_LETTORE.cmd) → lettore 1D integrato (barcode1d.js: EAN-13, EAN-8, Code 39/32).
// Nessun fotogramma lascia la pagina: al chiamante arriva solo il testo del codice.
// La telecamera si spegne alla prima lettura o dopo 30 secondi.
"use strict";

window.Scanner = (() => {
  const TIMEOUT_MS = 30000;
  const FORMATS = ["qr_code", "data_matrix", "ean_13", "ean_8", "code_39", "code_128", "upc_a"];
  let stream = null, timer = null, loop = null, zxing = null, builtin = null, active = false;

  function stop(video) {
    active = false;
    clearTimeout(timer);
    clearTimeout(loop);
    loop = null;
    try { zxing?.reset(); } catch { /* already stopped */ }
    zxing = null;
    builtin?.clear();
    builtin = null;
    for (const track of stream?.getTracks() || []) track.stop();
    stream = null;
    if (video) { video.pause(); video.srcObject = null; }
  }

  async function vendorAvailable() {
    if (window.ZXing?.BrowserMultiFormatReader) return true;
    try {
      const head = await fetch("/vendor/zxing.min.js", {method: "HEAD", cache: "no-store"});
      if (!head.ok) return false;
    } catch { return false; }
    return new Promise(resolve => {
      const script = document.createElement("script");
      script.src = "/vendor/zxing.min.js";
      script.onload = () => resolve(Boolean(window.ZXing?.BrowserMultiFormatReader));
      script.onerror = () => resolve(false);
      document.head.append(script);
    });
  }

  async function engine() {
    if ("BarcodeDetector" in window) {
      try {
        const supported = await window.BarcodeDetector.getSupportedFormats();
        const formats = FORMATS.filter(item => supported.includes(item));
        if (formats.length) return {kind: "nativo", detector: new window.BarcodeDetector({formats})};
      } catch { /* next reader */ }
    }
    if (await vendorAvailable()) return {kind: "zxing"};
    if (window.Barcode1D) return {kind: "integrato"};
    return null;
  }

  async function start(video, onCode, onStatus) {
    stop(video);
    const chosen = await engine();
    if (!chosen) {
      onStatus("Nessun lettore disponibile: usa il lettore USB o scrivi il codice.", "error", null);
      return false;
    }
    active = true;
    const done = text => {
      if (!active) return;
      stop(video);
      onCode(String(text || "").slice(0, 512), chosen.kind);
    };
    timer = setTimeout(() => { stop(video); onStatus("Nessun codice letto in 30 secondi: telecamera spenta.", "timeout", chosen.kind); },
      TIMEOUT_MS);
    try {
      if (chosen.kind === "zxing") {
        zxing = new window.ZXing.BrowserMultiFormatReader();
        onStatus("Inquadra il codice (QR, DataMatrix, EAN, AIC)…", "on", "zxing");
        await zxing.decodeFromVideoDevice(undefined, video, result => { if (result) done(result.getText()); });
        return true;
      }
      stream = await navigator.mediaDevices.getUserMedia({video: {facingMode: "environment", width: {ideal: 1280}},
        audio: false});
      if (!active) { stop(video); return false; }
      video.srcObject = stream;
      await video.play();
      if (chosen.kind === "nativo") {
        onStatus("Inquadra il codice (QR, DataMatrix, EAN, AIC)…", "on", "nativo");
        const scan = async () => {
          if (!active) return;
          try {
            const codes = await chosen.detector.detect(video);
            if (codes.length) return done(codes[0].rawValue);
          } catch { /* frame not ready */ }
          loop = setTimeout(scan, 120);
        };
        scan();
      } else {
        onStatus("Solo codici a barre (EAN/AIC). Per QR e DataMatrix: INSTALLA_LETTORE.cmd", "on", "integrato");
        builtin = window.Barcode1D.reader();
        const scan = () => {
          if (!active) return;
          const found = builtin?.read(video);
          if (found) return done(found.text);
          loop = setTimeout(scan, 125); // about 8 reads per second
        };
        scan();
      }
      return true;
    } catch (error) {
      stop(video);
      onStatus(error?.name === "NotAllowedError" ? "Permesso telecamera negato dal browser."
        : "Telecamera non disponibile.", "error", chosen.kind);
      return false;
    }
  }

  return {start, stop, isActive: () => active};
})();
