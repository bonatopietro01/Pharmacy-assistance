// Test del lettore 1D integrato su immagini sintetiche: dritte, ruotate ±10°, sfocate, a basso contrasto.
// node tests/barcode1d.test.js
"use strict";
const assert = require("assert");
const B = require("../frontend/barcode1d.js");

const L = ["0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011"];
const G = L.map(c => [...c].map(b => b === "0" ? "1" : "0").reverse().join(""));
const R = L.map(c => [...c].map(b => b === "0" ? "1" : "0").join(""));
const PARITY = ["LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG", "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL"];
const C39 = {"0": "000110100", "1": "100100001", "2": "001100001", "3": "101100000", "4": "000110001", "5": "100110000",
  "6": "001110000", "7": "000100101", "8": "100100100", "9": "001100100", "B": "001001001", "C": "101001000",
  "D": "000011001", "F": "001011000", "G": "000001101", "H": "100001100", "J": "000011100", "K": "100000011",
  "L": "001000011", "M": "101000010", "N": "000010011", "P": "001010010", "Q": "000000111", "R": "100000110",
  "S": "001000110", "T": "000010110", "V": "011000001", "W": "111000000", "X": "010010001", "Y": "110010000",
  "Z": "011010000", "*": "010010100"};

function check(body) {
  let sum = 0;
  for (let i = body.length - 1, w = 3; i >= 0; i--, w = w === 3 ? 1 : 3) sum += Number(body[i]) * w;
  return body + (10 - sum % 10) % 10;
}
function ean13Bits(code) {
  const p = PARITY[Number(code[0])];
  let bits = "101";
  for (let i = 1; i <= 6; i++) bits += (p[i - 1] === "L" ? L : G)[Number(code[i])];
  bits += "01010";
  for (let i = 7; i <= 12; i++) bits += R[Number(code[i])];
  return bits + "101";
}
function ean8Bits(code) {
  let bits = "101";
  for (let i = 0; i < 4; i++) bits += L[Number(code[i])];
  bits += "01010";
  for (let i = 4; i < 8; i++) bits += R[Number(code[i])];
  return bits + "101";
}
function code39Bits(text) {
  let bits = "";
  for (const char of "*" + text + "*") {
    const pattern = C39[char];
    [...pattern].forEach((wide, i) => { bits += (i % 2 === 0 ? "1" : "0").repeat(wide === "1" ? 3 : 1); });
    bits += "0";
  }
  return bits;
}
function aicToCode32(aic) {
  let value = Number(aic), out = "";
  const alphabet = "0123456789BCDFGHJKLMNPQRSTUVWXYZ";
  for (let i = 0; i < 6; i++) { out = alphabet[value % 32] + out; value = Math.floor(value / 32); }
  return out;
}

// Render bits into a gray image with options.
function render(bits, {module = 3, width = 640, height = 240, angle = 0, blur = 0, low = 0, high = 255, noise = 0, seed = 7}) {
  const quiet = 12 * module, barWidth = bits.length * module;
  const x0 = Math.round((width - barWidth) / 2), cy = height / 2, cx = width / 2;
  const rad = angle * Math.PI / 180, cos = Math.cos(rad), sin = Math.sin(rad);
  let state = seed;
  const rand = () => (state = (state * 1103515245 + 12345) % 2147483648) / 2147483648;
  const img = new Uint8Array(width * height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const u = cos * (x - cx) + sin * (y - cy) + cx, v = -sin * (x - cx) + cos * (y - cy) + cy;
      const col = Math.floor((u - x0) / module);
      const dark = v > height * 0.15 && v < height * 0.85 && col >= 0 && col < bits.length && bits[col] === "1";
      img[y * width + x] = dark ? low : high;
    }
  }
  if (blur) {
    const out = new Uint8Array(img.length);
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      let sum = 0, n = 0;
      for (let d = -blur; d <= blur; d++) { const xx = Math.min(width - 1, Math.max(0, x + d)); sum += img[y * width + xx]; n++; }
      out[y * width + x] = sum / n;
    }
    img.set(out);
  }
  if (noise) for (let i = 0; i < img.length; i++) img[i] = Math.max(0, Math.min(255, img[i] + (rand() - 0.5) * noise));
  void quiet;
  return {gray: img, width, height};
}

const ean = check("800123456789");
const cases = [
  ["EAN-13 dritto", ean13Bits(ean), {}, ean],
  ["EAN-13 ruotato +10°", ean13Bits(ean), {angle: 10, height: 320}, ean],
  ["EAN-13 ruotato -10°", ean13Bits(ean), {angle: -10, height: 320}, ean],
  ["EAN-13 sfocato", ean13Bits(ean), {blur: 1, module: 4, width: 720}, ean],
  ["EAN-13 contrasto basso", ean13Bits(ean), {low: 90, high: 170, noise: 20}, ean],
  ["EAN-13 capovolto", [...ean13Bits(ean)].reverse().join(""), {}, ean],
  ["EAN-8", ean8Bits(check("9638507")), {}, check("9638507")],
  ["Code 32 (AIC)", code39Bits(aicToCode32("024823080")), {module: 2, width: 800}, "A024823080"],
  ["Code 32 ruotato -8°", code39Bits(aicToCode32("012745028")), {module: 2, width: 800, height: 320, angle: -8}, "A012745028"],
];
let failed = 0;
for (const [name, bits, options, expected] of cases) {
  const image = render(bits, options);
  const found = B.decodeGray(image.gray, image.width, image.height);
  const ok = found && found.text === expected;
  console.log((ok ? "PASS " : "FAIL ") + name + " → " + (found ? found.format + " " + found.text : "nessuna lettura"));
  if (!ok) failed++;
}
// Nothing invented from noise.
const blank = render("", {noise: 120});
assert.strictEqual(B.decodeGray(blank.gray, blank.width, blank.height), null);
console.log("PASS rumore senza codice → nessuna lettura");
assert.strictEqual(B.code32ToAic(aicToCode32("024823080")), "A024823080");
process.exit(failed ? 1 : 0);
