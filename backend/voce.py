"""Aiuti per il riconoscimento vocale: rilevamento del parlato e vocabolario del catalogo.

- `SpeechGate`: decide se un blocco audio (PCM 16 bit, 16 kHz, mono) contiene
  parlato. Usa Silero VAD se attivato in configurazione e installato
  (`pip install silero-vad`), altrimenti la soglia di energia usata finora.
  Configurazione: "vad": {"attivo": true, "soglia": 0.5}
- `vocabulary_prompt`: nomi di prodotto e principi attivi del catalogo da
  suggerire al motore (prompt iniziale di whisper.cpp), entro 1200 caratteri.

Niente audio viene salvato: i blocchi passano solo in memoria.
"""

import json
import re
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "database" / "configurazione.json"
ENERGY_THRESHOLD = 220
SAMPLE_RATE = 16000
WINDOW = 512  # samples per Silero window at 16 kHz


def vad_settings(path=CONFIG):
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8")).get("vad") or {}
    except (OSError, ValueError):
        raw = {}
    return {"attivo": bool(raw.get("attivo")), "soglia": float(raw.get("soglia", 0.5))}


class SpeechGate:
    """Speech/no-speech decision per audio block, with a safe fallback."""

    def __init__(self, settings=None):
        settings = settings or vad_settings()
        self.threshold = settings["soglia"]
        self.model = None
        self.engine = "energia"
        if settings["attivo"]:
            try:
                from silero_vad import load_silero_vad
                import torch  # noqa: F401
                self.model = load_silero_vad()
                self.engine = "silero"
            except Exception:  # missing package or model: keep the energy gate
                self.model = None

    def is_speech(self, pcm16k, energy):
        if self.model is None:
            return energy >= ENERGY_THRESHOLD
        import torch
        samples = array("h")
        samples.frombytes(bytes(pcm16k))
        if len(samples) < WINDOW:
            return energy >= ENERGY_THRESHOLD
        best = 0.0
        for start in range(0, len(samples) - WINDOW + 1, WINDOW):
            chunk = torch.tensor(samples[start:start + WINDOW], dtype=torch.float32) / 32768.0
            best = max(best, float(self.model(chunk, SAMPLE_RATE).item()))
        return best >= self.threshold


_STOP = {"compresse", "compressa", "granulato", "spray", "crema", "gel", "bustine", "capsule", "sciroppo",
         "soluzione", "orale", "nasale", "acido", "banco", "demo", "sodio", "cloridrato", "adulti", "bambini", "forte", "gusto", "effervescente", "rivestite"}


def vocabulary_prompt(terms, limit=1200):
    """Distinct brand names and active ingredients from the catalog, most specific first."""
    names = {}
    for product in terms or ():
        for item in product.get("termini_dettaglio", ()):
            if item.get("basis") not in {"product_name", "catalog_alias", "active_ingredient"}:
                continue
            words = re.findall(r"[^\W\d_]+", item.get("term", ""))
            if not words:
                continue
            word = words[0]
            key = word.casefold()
            if len(key) >= 4 and key not in _STOP:
                names.setdefault(key, word.capitalize())
    text = ""
    for name in sorted(names.values(), key=str.casefold):
        candidate = f"{text}, {name}" if text else name
        if len(candidate) > limit:
            break
        text = candidate
    return text
