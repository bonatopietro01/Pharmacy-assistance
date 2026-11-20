"""Trascrizione locale con faster-whisper (CTranslate2), nello stesso processo del banco.

Il microfono è già catturato dal server Python (sounddevice), quindi l'audio non
passa dal browser né dalla rete: arriva qui come WAV in memoria, a fine frase.

Configurazione facoltativa in database/configurazione.json:

    "faster_whisper": {"modello": "auto", "compute_type": "auto", "device": "auto", "beam_size": "auto"}

- "auto" sceglie `large-v3-turbo` (float16) se c'è una GPU NVIDIA con CUDA,
  altrimenti `small` con `int8` sulla CPU. Valori utili senza GPU: "small"
  (≈ 0,5 GB, più veloce) o "medium" (≈ 1,5 GB, più preciso ma più lento).
- Lingua fissa: italiano. Filtro dei silenzi (Silero VAD integrato) attivo.
- `beam_size` "auto": 5 con GPU, 1 sulla CPU (stesso testo nelle prove, circa 20% più veloce).
- `initial_prompt`: nomi commerciali e principi attivi del catalogo (priorità) più
  sigle, termini e titoli brevi della wiki, generati in automatico.

I modelli si scaricano una volta nella cache di Hugging Face
(%USERPROFILE%\\.cache\\huggingface\\hub) e poi funzionano offline. Nessun audio
o testo viene scritto su disco o nei log.
"""

from __future__ import annotations

import io
import json
import threading
import wave
from array import array
from pathlib import Path

from backend.speech_whisper import WhisperBusyError, WhisperError

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "database" / "configurazione.json"
LANGUAGE = "it"
GPU_MODEL, CPU_MODEL = "large-v3-turbo", "small"
MAX_PROMPT_CHARS = 1000


def settings(path=CONFIG):
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8")).get("faster_whisper") or {}
    except (OSError, ValueError):
        raw = {}
    text = lambda key, default: raw.get(key) if isinstance(raw.get(key), str) and raw.get(key) else default
    beam = raw.get("beam_size", "auto")
    return {"modello": text("modello", "auto"), "compute_type": text("compute_type", "auto"),
            "device": text("device", "auto"), "beam_size": beam if type(beam) is int and 1 <= beam <= 10 else "auto"}


def cuda_available():
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def resolve(conf, has_cuda=None):
    """Concrete (model, device, compute_type) for the configured 'auto' values."""
    has_cuda = cuda_available() if has_cuda is None else has_cuda
    device = conf["device"] if conf["device"] != "auto" else ("cuda" if has_cuda else "cpu")
    model = conf["modello"] if conf["modello"] != "auto" else (GPU_MODEL if device == "cuda" else CPU_MODEL)
    compute = conf["compute_type"] if conf["compute_type"] != "auto" else ("float16" if device == "cuda" else "int8")
    return model, device, compute


def wav_to_float(wav_bytes):
    """16 kHz mono 16-bit WAV (as built by the desk) → list of floats in [-1, 1]."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as source:
        if source.getsampwidth() != 2 or source.getnchannels() != 1 or source.getframerate() != 16000:
            raise WhisperError("faster_whisper_audio_non_valido")
        samples = array("h")
        samples.frombytes(source.readframes(source.getnframes()))
    import numpy
    return numpy.frombuffer(samples.tobytes(), dtype=numpy.int16).astype(numpy.float32) / 32768.0


def build_prompt(*parts, limit=MAX_PROMPT_CHARS):
    """Join comma-separated vocabulary lists, de-duplicated, within the prompt budget.

    Later parts have priority and go last: Whisper keeps the tail of a long prompt.
    """
    seen, chosen, size = set(), [], 0
    for part in reversed(parts):
        for item in reversed([x.strip() for x in (part or "").split(",")]):
            if not item or item.casefold() in seen:
                continue
            if size + len(item) + 2 > limit:
                return ", ".join(reversed(chosen))
            seen.add(item.casefold())
            chosen.append(item)
            size += len(item) + 2
    return ", ".join(reversed(chosen))


class FasterWhisperEngine:
    """Same small interface as WhisperServer: start(), stop(), transcribe_wav(wav, prompt)."""

    _shared = {}
    _shared_lock = threading.Lock()

    def __init__(self, root=None, config=CONFIG):
        self.conf = settings(config)
        self.model = None
        self.lock = threading.Lock()

    @staticmethod
    def available():
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False
        return True

    def beam_size(self):
        beam = self.conf["beam_size"]
        if beam == "auto":
            return 5 if resolve(self.conf)[1] == "cuda" else 1
        return beam

    def describe(self):
        model, device, compute = resolve(self.conf)
        return {"modello": model, "device": device, "compute_type": compute}

    def start(self):
        if not self.available():
            raise WhisperError("faster_whisper_non_installato")
        key = resolve(self.conf)
        with self._shared_lock:  # keep the loaded model across listening sessions
            if key not in self._shared:
                from faster_whisper import WhisperModel
                from faster_whisper.utils import download_model
                name, device, compute = key
                try:
                    if Path(name).is_dir():
                        path = name
                    else:
                        try:  # cached: load from disk without any network request
                            path = download_model(name, local_files_only=True)
                        except Exception:  # first run: download once into the Hugging Face cache
                            path = download_model(name)
                    model = WhisperModel(path, device=device, compute_type=compute)
                except Exception as exc:
                    raise WhisperError("faster_whisper_modello_non_disponibile") from exc
                self._shared[key] = model
            self.model = self._shared[key]

    def stop(self):
        self.model = None

    def transcribe_wav(self, wav_bytes, prompt=None):
        if self.model is None:
            raise WhisperError("faster_whisper_non_avviato")
        if not self.lock.acquire(blocking=False):
            raise WhisperBusyError("whisper_busy")
        try:
            audio = wav_to_float(wav_bytes)
            segments, _ = self.model.transcribe(
                audio, language=LANGUAGE, task="transcribe", beam_size=self.beam_size(),
                vad_filter=True, vad_parameters={"min_silence_duration_ms": 500},
                initial_prompt=prompt or None, condition_on_previous_text=False, without_timestamps=True)
            return " ".join(segment.text.strip() for segment in segments).strip()
        except WhisperError:
            raise
        except Exception as exc:
            raise WhisperError("faster_whisper_trascrizione_non_riuscita") from exc
        finally:
            self.lock.release()
