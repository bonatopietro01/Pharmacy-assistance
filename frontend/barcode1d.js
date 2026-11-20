// Lettore di codici a barre 1D senza dipendenze: EAN-13, EAN-8, Code 39 (incluso Code 32 / bollino AIC).
// Lavora su righe orizzontali di un'immagine in scala di grigi. Nessun dato esce dalla pagina.
"use strict";

(function (root) {
  const L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"];
  const G = L.map(code => [...code].map(bit => bit === "0" ? "1" : "0").reverse().join(""));
  const R = L.map(code => [...code].map(bit => bit === "0" ? "1" : "0").join(""));
  const PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"];
  const C39 = {
    "0": "000110100", "1": "100100001", "2": "001100001", "3": "101100000", "4": "000110001", "5": "100110000",
    "6": "001110000", "7": "000100101", "8": "100100100", "9": "001100100", "A": "100001001", "B": "001001001",
    "C": "101001000", "D": "000011001", "E": "100011000", "F": "001011000", "G": "000001101", "H": "100001100",
    "I": "001001100", "J": "000011100", "K": "100000011", "L": "001000011", "M": "101000010", "N": "000010011",
    "O": "100010010", "P": "001010010", "Q": "000000111", "R": "100000110", "S": "001000110", "T": "000010110",
    "U": "110000001", "V": "011000001", "W": "111000000", "X": "010010001", "Y": "110010000", "Z": "011010000",
    "-": "010000101", ".": "110000100", " ": "011000100", "*": "010010100", "$": "010101000", "/": "010100010",
    "+": "010001010", "%": "000101010"
  };
  const C39_BY_PATTERN = Object.fromEntries(Object.entries(C39).map(([char, pattern]) => [pattern, char]));
  const CODE32 = "0123456789BCDFGHJKLMNPQRSTUVWXYZ";

  function runsToWidths(code) { // "0001101" → widths of alternating runs starting with the first bit
    const widths = [];
    let count = 1;
    for (let i = 1; i <= code.length; i++) {
      if (code[i] === code[i - 1]) count++;
      else { widths.push(count); count = 1; }
    }
    return widths;
  }
  const L_W = L.map(runsToWidths), G_W = G.map(runsToWidths), R_W = R.map(runsToWidths);

  function bestDigit(widths, tables) {
    const total = widths.reduce((a, b) => a + b, 0);
    const scaled = widths.map(width => width * 7 / total);
    let best = null;
    for (const [name, table] of tables) {
      table.forEach((pattern, digit) => {
        if (pattern.length !== 4) return;
        const error = pattern.reduce((sum, value, index) => sum + Math.abs(value - scaled[index]), 0);
        if (!best || error < best.error) best = {digit, name, error};
      });
    }
    return best && best.error < 1.6 ? best : null;
  }

  function gs1Valid(digits) {
    const body = digits.slice(0, -1);
    let sum = 0;
    for (let i = body.length - 1, weight = 3; i >= 0; i--, weight = weight === 3 ? 1 : 3) sum += Number(body[i]) * weight;
    return (10 - sum % 10) % 10 === Number(digits.at(-1));
  }

  // runs: widths of alternating segments, runs[0] is a bar (dark).
  function decodeEan(runs) {
    for (const [digitsLeft, length] of [[6, 59], [4, 43]]) {
      for (let start = 0; start + length <= runs.length; start += 2) {
        const slice = runs.slice(start, start + length);
        const modules = digitsLeft === 6 ? 95 : 67;
        const unit = slice.reduce((a, b) => a + b, 0) / modules;
        const guard = [0, 1, 2].every(index => Math.abs(slice[index] / unit - 1) < 0.7);
        const middle = 3 + digitsLeft * 4;
        const midGuard = [0, 1, 2, 3, 4].every(index => Math.abs(slice[middle + index] / unit - 1) < 0.7);
        const endGuard = [1, 2, 3].every(index => Math.abs(slice[length - index] / unit - 1) < 0.7);
        if (!guard || !midGuard || !endGuard) continue;
        // Quiet zone before the start guard: the white space must be wide.
        if (start > 0 && runs[start - 1] < unit * 4) continue;
        const left = [], parity = [];
        let ok = true;
        for (let d = 0; d < digitsLeft && ok; d++) {
          const found = bestDigit(slice.slice(3 + d * 4, 7 + d * 4),
            digitsLeft === 6 ? [["L", L_W], ["G", G_W]] : [["L", L_W]]);
          if (!found) ok = false; else { left.push(found.digit); parity.push(found.name); }
        }
        const right = [];
        for (let d = 0; d < digitsLeft && ok; d++) {
          const offset = middle + 5 + d * 4;
          const found = bestDigit(slice.slice(offset, offset + 4), [["R", R_W]]);
          if (!found) ok = false; else right.push(found.digit);
        }
        if (!ok) continue;
        let digits;
        if (digitsLeft === 6) {
          const first = PARITY.indexOf(parity.join(""));
          if (first < 0) continue;
          digits = String(first) + left.join("") + right.join("");
        } else {
          digits = left.join("") + right.join("");
        }
        if (gs1Valid(digits)) return {format: digitsLeft === 6 ? "ean_13" : "ean_8", text: digits};
      }
    }
    return null;
  }

  function decodeCode39(runs) {
    for (let start = 0; start + 9 <= runs.length; start += 2) {
      const chars = [];
      let index = start;
      while (index + 9 <= runs.length) {
        const group = runs.slice(index, index + 9);
        const sorted = [...group].sort((a, b) => a - b);
        const narrow = (sorted[0] + sorted[1] + sorted[2] + sorted[3] + sorted[4] + sorted[5]) / 6;
        const threshold = narrow * 1.6;
        const wide = group.filter(width => width > threshold).length;
        if (wide !== 3) break;
        const pattern = group.map(width => width > threshold ? "1" : "0").join("");
        const char = C39_BY_PATTERN[pattern];
        if (!char) break;
        chars.push(char);
        if (char === "*" && chars.length > 1) break;
        index += 10; // skip the narrow gap between characters
      }
      if (chars.length >= 3 && chars[0] === "*" && chars.at(-1) === "*") {
        const text = chars.slice(1, -1).join("");
        if (text && !text.includes("*")) return {format: "code_39", text};
      }
    }
    return null;
  }

  function code32ToAic(text) {
    if (!/^[0-9BCDFGHJKLMNPQRSTUVWXYZ]{6}$/.test(text)) return null;
    let value = 0;
    for (const char of text) value = value * 32 + CODE32.indexOf(char);
    return value < 1e9 ? "A" + String(value).padStart(9, "0") : null;
  }

  function lineRuns(gray, width, row, threshold) {
    const runs = [];
    let x = 0;
    while (x < width && gray[row * width + x] >= threshold) x++; // leading quiet zone
    if (x === width) return runs;
    runs.push(x); // quiet zone width is kept as a negative marker for the first element
    let dark = true, count = 0;
    for (; x < width; x++) {
      const isDark = gray[row * width + x] < threshold;
      if (isDark === dark) count++;
      else { runs.push(count); dark = isDark; count = 1; }
    }
    runs.push(count);
    return runs;
  }

  function decodeRuns(raw) {
    // raw[0] is the quiet zone; then bar, space, bar...
    const runs = raw.slice(1);
    const withQuiet = [raw[0], ...runs];
    const ean = decodeEan(runs) || decodeEanWithQuiet(withQuiet);
    if (ean) return ean;
    const c39 = decodeCode39(runs);
    if (c39) {
      const aic = code32ToAic(c39.text);
      return aic ? {format: "code_32", text: aic} : c39;
    }
    return null;
  }

  function decodeEanWithQuiet(withQuiet) { return decodeEan(withQuiet.slice(1)); }

  function reversedRuns(raw) {
    // Reverse a line (upside-down packs): keep a quiet-zone placeholder in front.
    const runs = raw.slice(1).reverse();
    if (runs.length % 2 === 0) runs.shift(); // must start with a bar
    return [0, ...runs];
  }

  // gray: Uint8Array-like luminance, row-major. Tries several lines and two thresholds.
  function decodeGray(gray, width, height) {
    const rows = [];
    for (let i = 0; i < 15; i++) rows.push(Math.round(height * (0.2 + 0.6 * i / 14)));
    for (const row of rows) {
      let min = 255, max = 0;
      for (let x = 0; x < width; x++) {
        const value = gray[row * width + x];
        if (value < min) min = value;
        if (value > max) max = value;
      }
      if (max - min < 40) continue;
      for (const ratio of [0.5, 0.4, 0.6]) {
        const raw = lineRuns(gray, width, row, min + (max - min) * ratio);
        if (raw.length < 30) continue;
        const found = decodeRuns(raw) || decodeRuns(reversedRuns(raw));
        if (found) return found;
      }
    }
    return null;
  }

  function grayFromRgba(rgba, width, height) {
    const gray = new Uint8Array(width * height);
    for (let i = 0, j = 0; i < gray.length; i++, j += 4) gray[i] = (rgba[j] * 299 + rgba[j + 1] * 587 + rgba[j + 2] * 114) / 1000;
    return gray;
  }

  // Video reader: needs 2 identical consecutive reads before accepting a code.
  function reader() {
    let last = null;
    const canvas = typeof document !== "undefined" ? document.createElement("canvas") : null;
    const context = canvas ? canvas.getContext("2d", {willReadFrequently: true}) : null;
    return {
      read(video) {
        if (!context || !video.videoWidth) return null;
        const width = Math.min(960, video.videoWidth);
        const height = Math.round(video.videoHeight * width / video.videoWidth);
        canvas.width = width;
        canvas.height = height;
        context.drawImage(video, 0, 0, width, height);
        const found = decodeGray(grayFromRgba(context.getImageData(0, 0, width, height).data, width, height), width, height);
        if (!found) return null;
        if (last && last.text === found.text) { last = null; return found; }
        last = found;
        return null;
      },
      clear() {
        last = null;
        if (canvas) { canvas.width = canvas.height = 0; }
      }
    };
  }

  const api = {decodeGray, decodeRuns, code32ToAic, gs1Valid, reader, grayFromRgba};
  root.Barcode1D = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
