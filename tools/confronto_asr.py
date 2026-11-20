"""Confronto dei motori vocali sui dialoghi registrati al banco.

Prepara una cartella con:
- file WAV (mono, 16 bit; qualsiasi frequenza per Vosk, 16 kHz consigliati);
- `atteso.jsonl`, una riga per file:
  {"file": "01.wav", "famiglia": "REAL-MED-00", "concetto": "raffreddore"}
  (`famiglia` = prefisso del codice prodotto atteso, facoltativo; `concetto` facoltativo)

Le registrazioni sono dialoghi letti dal farmacista, senza clienti veri, e
restano fuori dal repository.

    python tools/confronto_asr.py cartella_dialoghi --motori vosk whispercpp voxtral
    python tools/confronto_asr.py cartella_dialoghi --motori finto   (prova dello script)

Voxtral Realtime si interroga tramite un server locale compatibile OpenAI
(es. vLLM): --voxtral-url http://127.0.0.1:8000/v1/audio/transcriptions
Nessun audio esce dal PC: gli URL ammessi sono solo locali.

Misure per motore: famiglia di prodotto riconosciuta, concetto riconosciuto,
latenza media e massima dalla fine dell'audio al pannello (trascrizione +
analisi). Obiettivo del piano: ≥ 7/8 famiglie, ≥ 8/10 concetti, < 1,5 s.
"""

import argparse
import io
import json
import statistics
import sys
import time
import urllib.request
import uuid
import wave
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.conversation import analyze  # noqa: E402
from backend.knowledge import product_aliases, reference_material, search  # noqa: E402
from backend.voce import vocabulary_prompt  # noqa: E402


def _engine_vosk():
    from vosk import KaldiRecognizer, Model
    model = Model(str(ROOT / "models" / "vosk-model-small-it-0.22"))

    def run(wav_bytes, _vocabulary):
        with wave.open(io.BytesIO(wav_bytes)) as source:
            recognizer = KaldiRecognizer(model, source.getframerate())
            while data := source.readframes(4000):
                recognizer.AcceptWaveform(data)
        return json.loads(recognizer.FinalResult()).get("text", "")
    return run, lambda: None


def _engine_whispercpp():
    from backend.speech_whisper import WhisperServer
    server = WhisperServer(ROOT)
    server.start()
    return (lambda wav_bytes, vocabulary: server.transcribe_wav(wav_bytes, prompt=vocabulary)), server.stop


def _engine_voxtral(url, model):
    host = urlsplit(url).hostname
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Per Voxtral sono ammessi solo server locali: l'audio non deve uscire dal PC.")

    def run(wav_bytes, vocabulary):
        boundary = uuid.uuid4().hex
        parts = []
        for name, value in (("model", model), ("language", "it"), ("prompt", vocabulary)):
            if value:
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n'
                     f"Content-Type: audio/wav\r\n\r\n".encode() + wav_bytes + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        request = urllib.request.Request(url, data=b"".join(parts), method="POST",
                                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read()).get("text", "")
    return run, lambda: None


def _engine_fake(expected_texts):
    return (lambda _wav, _vocabulary, _texts=iter(expected_texts): next(_texts, "")), lambda: None


def evaluate(folder, engines, voxtral_url=None, voxtral_model="mistralai/Voxtral-Mini-4B-Realtime-2602"):
    folder = Path(folder)
    expected = [json.loads(line) for line in (folder / "atteso.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()]
    products, pages = reference_material()
    terms = product_aliases(products, pages)
    vocabulary = vocabulary_prompt(terms)
    report = {}
    for name in engines:
        if name == "vosk":
            run, close = _engine_vosk()
        elif name == "whispercpp":
            run, close = _engine_whispercpp()
        elif name == "voxtral":
            if not voxtral_url:
                raise SystemExit("Indicare --voxtral-url del server locale.")
            run, close = _engine_voxtral(voxtral_url, voxtral_model)
        elif name == "finto":
            run, close = _engine_fake([item.get("testo", "") for item in expected])
        else:
            raise SystemExit(f"Motore sconosciuto: {name}")
        rows, latencies = [], []
        family_hit = family_total = concept_hit = concept_total = 0
        try:
            for item in expected:
                path = folder / item["file"]
                audio = path.read_bytes() if path.is_file() else b""
                started = time.perf_counter()
                text = run(audio, vocabulary)
                result = analyze(text, terms)
                latencies.append(time.perf_counter() - started)
                codes = {e.get("code") for e in result["evidence"] if e.get("code")}
                codes |= {page.get("prodotto") for page in search(text)[:3] if page.get("prodotto")}
                concepts = {e.get("concept_id") for e in result["evidence"] if e["kind"] == "topic"}
                row = {"file": item["file"], "testo": text}
                if item.get("famiglia"):
                    family_total += 1
                    ok = any(code and code.startswith(item["famiglia"]) for code in codes)
                    family_hit += ok
                    row["famiglia_ok"] = ok
                if item.get("concetto"):
                    concept_total += 1
                    ok = item["concetto"] in concepts
                    concept_hit += ok
                    row["concetto_ok"] = ok
                rows.append(row)
        finally:
            close()
        report[name] = {
            "famiglia": f"{family_hit}/{family_total}", "concetto": f"{concept_hit}/{concept_total}",
            "latenza_media_s": round(statistics.mean(latencies), 3) if latencies else None,
            "latenza_max_s": round(max(latencies), 3) if latencies else None,
            "dettaglio": rows,
        }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cartella", type=Path)
    parser.add_argument("--motori", nargs="+", default=["vosk", "whispercpp"])
    parser.add_argument("--voxtral-url")
    parser.add_argument("--voxtral-modello", default="mistralai/Voxtral-Mini-4B-Realtime-2602")
    parser.add_argument("--dettaglio", action="store_true")
    args = parser.parse_args(argv)
    report = evaluate(args.cartella, args.motori, args.voxtral_url, args.voxtral_modello)
    if not args.dettaglio:
        for value in report.values():
            value.pop("dettaglio")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
