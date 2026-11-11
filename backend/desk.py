"""Serve the local pharmacy screen and keep the consultation in memory."""

import argparse
from difflib import SequenceMatcher
import hashlib
import ipaddress
import io
import json
import math
import os
import re
import sqlite3
import sys
import threading
import time
import wave
import webbrowser
from array import array
from collections import deque
from contextlib import closing
from copy import deepcopy
from datetime import date, datetime, timezone
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, Full, Queue
from tempfile import NamedTemporaryFile
from urllib.parse import parse_qsl, quote, urlsplit
from uuid import uuid4

from backend import knowledge, phase_agent
from backend.cart import (add_item as cart_add_item, apply_offer as cart_apply_offer,
                          empty_cart, remove_item as cart_remove_item,
                          remove_offer as cart_remove_offer, serialize_cart)
from backend.conversation import analyze
from backend.knowledge import (CATALOG, ROOT, normalize, product_aliases, product_display, reference_material,
                               search, stock_for, symptom_product_matches)
from backend.offers import active_offers, offer_listing, save_offer
from backend.speech import decode_result, find_alternative_codes
from backend.speech_whisper import WhisperError, WhisperServer

PORT = 8765
ORIGIN = f"http://127.0.0.1:{PORT}"
LOW_STOCK = 3
REQUESTS = ROOT / "database" / "reintegro.sqlite3"
SETTINGS = ROOT / "database" / "configurazione.json"
MODEL = ROOT / "models" / "vosk-model-small-it-0.22"
if (ROOT / ".audio-packages").is_dir():
    sys.path.append(str(ROOT / ".audio-packages"))

LEASE_SECONDS = 12
DEFAULT_PAUSE_SECONDS = 4
STABLE_SECONDS = 0.6
PHASES = ("Raccolta", "Domande", "Verifica prodotto", "Consiglio confermato", "Servizio")
SALES_STAGES = {"collecting", "questions", "proposal", "sale", "closing"}
PHASE_BY_EVIDENCE = {
    "topic": "research", "product_candidate": "research", "product_mention": "research",
    "spoken_match": "research", "desk_choice": "choose", "desk_preference": "choose",
    "closing_signal": "extras", "offer_decline": "closing",
}
EMPTY_COMMERCIAL = {
    "bank_price_cents": None, "bank_price_source": None,
    "reference_price_cents": None, "reference_price_source": None,
    "stock": None, "stock_source": None, "checked_at": None, "complements": [],
}
SUPPLEMENT_CATEGORIES = {"integratore", "integratore_alimentare"}
SERVICES = {"turni": "Farmacie di turno", "orari": "Orari della farmacia", "sito": "Sito della farmacia"}
RELATIONS = {"figlio", "figlia", "padre", "madre", "nonno", "nonna", "marito", "moglie", "partner",
             "amico", "amica", "fratello", "sorella"}

EVENTS = deque(maxlen=100)
EVENT_LOCK = threading.Lock()
SETTINGS_LOCK = threading.Lock()
FRONTEND_CODES = {"ricerca", "stato", "microfono", "pagina", "azione", "offerte", "configurazione"}
DIAGNOSTIC_CODES = {
    "audio": {"avvio", "attivo", "dipendenze_o_modello", "microfono_o_ricerca", "sessione_chiusa",
              "lease_scaduta", "motore_whisper_ripiego", "dispositivo_input_non_disponibile"},
    "backend": {"operazione_non_disponibile"},
    "ricerca": {"ricerca_non_disponibile"},
    "frontend": FRONTEND_CODES,
    "agente": {"timeout", "provider_non_disponibile", "risposta_non_valida"},
}

_SPEECH_BRAND_STOPWORDS = {
    "banco", "demo", "farmaco", "medicinale", "integratore", "prodotto", "generico",
    "compresse", "compressa", "capsule", "capsula", "granulato", "spray", "sciroppo",
    "bustine", "bustina", "gel", "crema", "collutorio", "gocce", "magnesio",
    "buongiorno", "cerco", "cerchiamo", "cercando", "vorrei", "voglio", "avete",
    "serve", "servono", "dammi", "dare", "mi", "per", "favore", "sto", "una", "uno",
    "nasale", "orale", "orali", "confezione", "masticabile", "masticabili", "effervescente",
    "milligrammo", "milligrammi", "cinquecento", "duecento", "quattrocento", "mille",
    "unita", "venticinque", "ventimila", "mila", "percento",
}


def _catalog_speech_prompt(terms, transcript=None):
    if not isinstance(transcript, str) or not transcript.strip():
        return ""
    names = {}
    for product in terms:
        for item in product.get("termini_dettaglio", ()):
            if item.get("basis") not in {"product_name", "catalog_alias"}:
                continue
            words = re.findall(r"[^\W\d_]+", item.get("term", ""))
            if not words:
                continue
            name = words[0].strip()
            key = normalize(name)
            if len(key) >= 5 and key not in _SPEECH_BRAND_STOPWORDS:
                names.setdefault(key, name)
    if not names:
        return ""
    words = [normalize(word) for word in re.findall(r"[^\W\d_]+", transcript.casefold())]
    words = [word for word in words if len(word) >= 3 and word not in _SPEECH_BRAND_STOPWORDS]
    fragments = {word for word in words if len(word) >= 5}
    for start in range(len(words)):
        for size in (2, 3):
            group = words[start:start + size]
            if len(group) == size and all(len(word) <= 8 for word in group):
                fragments.add("".join(group))
    ranked = []
    for key, name in names.items():
        score = max((SequenceMatcher(None, fragment, key, autojunk=False).ratio()
                     for fragment in fragments), default=0.0)
        if score >= 0.60:
            ranked.append((score, key, name))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    if not ranked:
        return ""
    return "Possibile nome nel catalogo: " + ranked[0][2] + "."


def diagnostic(component, code, level="info", duration=0):
    if code not in DIAGNOSTIC_CODES.get(component, ()) or level not in ("info", "errore", "avviso"):
        return
    event = {"ora": datetime.now(timezone.utc).isoformat(timespec="seconds"), "componente": component,
             "codice": code, "livello": level, "durata_ms": round(max(0, duration) * 1000)}
    with EVENT_LOCK:
        EVENTS.append(event)


def public_url_template(url):
    if not isinstance(url, str) or len(url) > 1000 or re.search(r"[\s\\]", url):
        raise ValueError("Indica un URL HTTPS pubblico.")
    test_url = url.replace("{comune}", "Comune").replace("{data}", "2000-01-01")
    if "{" in test_url or "}" in test_url:
        raise ValueError("I segnaposti ammessi sono {comune} e {data}.")
    parts = urlsplit(test_url)
    host = parts.hostname
    if parts.scheme != "https" or not host or parts.username or parts.password or "#" in url:
        raise ValueError("Indica un URL HTTPS pubblico senza credenziali.")
    original = urlsplit(url)
    if "{" in original.netloc or "." not in host or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("Il nome host deve essere pubblico e fisso.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r"[a-z0-9.-]+", host) or all(ch in "0123456789." for ch in host):
            raise ValueError("Il nome host non è valido.")
    else:
        if not address.is_global:
            raise ValueError("Il nome host deve essere pubblico.")
    if parts.port not in (None, 443):
        raise ValueError("Usa la porta HTTPS pubblica.")
    parameters = parse_qsl(original.query, keep_blank_values=True, strict_parsing=True)
    allowed_parameters = {"comune": "{comune}", "data": "{data}"}
    if len(parameters) != len(dict(parameters)) or any(
            key not in allowed_parameters or value != allowed_parameters[key]
            or value not in original.query for key, value in parameters):
        raise ValueError("Usa solo i parametri pubblici comune={comune} e data={data}.")


def normalize_configuration(payload):
    delay = payload.get("ritardo_secondi", 3)
    if type(delay) not in (int, float) or not 1 <= delay <= 10:
        raise ValueError("Indica un ritardo tra 1 e 10 secondi.")
    pause = payload.get("pausa_secondi", DEFAULT_PAUSE_SECONDS)
    if type(pause) not in (int, float) or not 1 <= pause <= 30:
        raise ValueError("Indica una pausa tra 1 e 30 secondi.")
    sources = payload.get("fonti", {})
    if not isinstance(sources, dict) or any(kind not in SERVICES for kind in sources):
        raise ValueError("Configura solo le fonti pubbliche previste.")
    clean = {}
    for kind in SERVICES:
        url = sources.get(kind, "")
        if url != "":
            public_url_template(url)
        clean[kind] = url
    return {"ritardo_secondi": delay, "pausa_secondi": pause, "fonti": clean}


def _read_configuration(path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("Configurazione locale non valida.")
    return payload


def load_configuration(path=SETTINGS):
    return normalize_configuration(_read_configuration(path))


def _write_configuration(path, config):
    temp_path = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temp:
            temp_path = Path(temp.name)
            json.dump(config, temp, ensure_ascii=False, indent=2)
            temp.write("\n")
        temp_path.replace(path)
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


def save_configuration(payload, path=SETTINGS):
    config = normalize_configuration(payload)
    with SETTINGS_LOCK:
        current = _read_configuration(path)
        agent = phase_agent.normalize_settings(current.get("agent", {}))
        speech_engine = current.get("speech_engine", "vosk")
        if speech_engine not in ("vosk", "whisper.cpp", "ibrido"):
            speech_engine = "vosk"
        input_device = current.get("input_device")
        _write_configuration(path, {**config, "agent": agent, "speech_engine": speech_engine,
                                    "input_device": input_device})
    return config


def load_agent_settings(path=SETTINGS):
    return phase_agent.normalize_settings(_read_configuration(path).get("agent", {}))


def load_speech_engine(path=SETTINGS):
    value = _read_configuration(path).get("speech_engine", "vosk")
    return value if value in ("vosk", "whisper.cpp", "ibrido") else "vosk"


def load_input_device(path=SETTINGS):
    value = _read_configuration(path).get("input_device")
    return value if isinstance(value, str) and value else None


def _input_device_records(sounddevice=None):
    try:
        if sounddevice is None:
            import sounddevice
        devices = sounddevice.query_devices()
        host_apis = sounddevice.query_hostapis()
        default_index = sounddevice.default.device[0]
    except Exception:
        return []

    duplicate_counts = {}
    records = []
    for index, device in enumerate(devices):
        channels = device.get("max_input_channels", 0)
        if type(channels) is not int or channels < 1:
            continue
        host_index = device.get("hostapi")
        host_name = host_apis[host_index].get("name", "") if type(host_index) is int and 0 <= host_index < len(host_apis) else ""
        name = str(device.get("name", "Ingresso audio"))
        identity = (host_name.casefold().strip(), name.casefold().strip())
        duplicate = duplicate_counts.get(identity, 0)
        duplicate_counts[identity] = duplicate + 1
        digest = hashlib.sha256("\0".join((*identity, str(duplicate))).encode("utf-8")).hexdigest()[:20]
        records.append({
            "id": f"audio-{digest}", "name": name, "channels": channels,
            "default": index == default_index, "index": index,
            "default_samplerate": device.get("default_samplerate"),
        })
    return records


def _audio_input_selection(device_id, sounddevice=None):
    if sounddevice is None:
        import sounddevice
    records = _input_device_records(sounddevice)
    selected = next((record for record in records if record["id"] == device_id), None) if device_id else None
    if device_id and selected is None:
        raise InputDeviceUnavailable
    if selected:
        index, sample_rate = selected["index"], selected["default_samplerate"]
    else:
        default = next((record for record in records if record["default"]), None)
        if default:
            index, sample_rate = None, default["default_samplerate"]
        else:
            try:
                default_info = sounddevice.query_devices(kind="input")
            except Exception as exc:
                raise InputDeviceUnavailable from exc
            index, sample_rate = None, default_info.get("default_samplerate")

    if type(sample_rate) not in (int, float) or not math.isfinite(sample_rate) or not 8000 <= sample_rate <= 192000:
        raise InputDeviceUnavailable
    return index, int(sample_rate)


class InputDeviceUnavailable(Exception):
    """Configured or default input device cannot be resolved on this host."""


def public_agent_settings(config, speech_engine="vosk", speech_active_engine=None, input_device=None):
    devices = _input_device_records()
    available_ids = {device["id"] for device in devices}
    missing = bool(input_device and input_device not in available_ids)
    return {**config, "api_key_configured": phase_agent.read_key() is not None,
            "speech_engine": speech_engine, "whisper_available": WhisperServer.available(),
            "speech_active_engine": speech_active_engine,
            "input_device": None if missing else input_device,
            "input_device_missing": missing,
            "input_devices": [{key: device[key] for key in ("id", "name", "channels", "default")}
                              for device in devices]}


def desk_phase(key="clarify", *, evidence_id=None, source="local", reason=None):
    return {"key": key, "label": phase_agent.PHASE_LABELS[key], "reason": reason or phase_agent.PHASE_REASONS[key],
            "evidence_id": evidence_id, "source": source}


def public_service(kind=None, comune="", data="", config=None):
    source, status = None, "idle"
    if kind:
        template = config["fonti"][kind]
        requires_location = kind == "turni" or "{comune}" in template
        requires_date = kind == "turni" or "{data}" in template
        if (requires_location and not comune) or (requires_date and not data):
            status = "missing"
        elif not template:
            status = "unconfigured"
        else:
            status = "link"
            url = template.replace("{comune}", quote(comune, safe="")).replace("{data}", quote(data, safe=""))
            source = {"url": url, "label": SERVICES[kind]}
    return {"kind": kind, "comune": comune, "data": data, "status": status, "answer": None, "source": source}


def phase(value="Raccolta", source="auto", reason="Sto raccogliendo il contesto.", missing=None):
    return {"value": value, "source": source, "reason": reason, "missing": missing or []}


def unknown_recipient():
    return {"kind": "sconosciuto", "relation": None, "declared_fields": {}, "source": "unknown"}


def empty_desk_results():
    return {"previous": False, "rows": [], "preferred_code": None, "supplements": [], "offers": [],
            "recognized_name": None, "phase": None, "voice_choice": None, "voice_options": [],
            "preference_codes": [], "correction_options": []}


def recognize(recognizer, audio):
    text, final, _ = recognize_with_options(recognizer, audio)
    return text, final


def recognize_with_options(recognizer, audio):
    final = bool(recognizer.AcceptWaveform(bytes(audio)))
    payload = json.loads(recognizer.Result() if final else recognizer.PartialResult())
    text, alternatives = decode_result(payload, final)
    return text, final, alternatives


def utf16_length(text):
    return len(text.encode("utf-16-le")) // 2


def _codepoint_offset(text, utf16_offset):
    units = 0
    for index, character in enumerate(text):
        if units >= utf16_offset:
            return index
        units += 2 if ord(character) > 0xFFFF else 1
    return len(text)


def _clause_bounds(text, utf16_span, segment_boundaries=()):
    start = _codepoint_offset(text, utf16_span["start"])
    end = _codepoint_offset(text, utf16_span["end"])
    left = max((*[index + 1 for index, character in enumerate(text[:start])
                 if character in ".!?;\n"],
                *(boundary + 1 for boundary in segment_boundaries if boundary < start)), default=0)
    right = min((*[index for index in range(end, len(text)) if text[index] in ".!?;\n"],
                  *(boundary for boundary in segment_boundaries if boundary >= end)), default=len(text))
    return left, right


def reference_card(page, state, evidence=()):
    code = (page["catalogo"] or {}).get("codice")
    return {
        "id": page["scheda"], "state": state, "product_codes": [code] if code else [],
        "source": {"kind": "catalog" if page["stato"] == "catalogo" else "wiki",
                   "id": code if page["stato"] == "catalogo" else page["scheda"],
                   "label": page["fonte"], "version": str(page.get("versione", "demo"))},
        "reason": evidence[0]["reason"] if evidence else "Consultazione del farmacista.",
        "evidence_ids": [item["id"] for item in evidence],
        "titolo": page["titolo"], "testo": page["testo"], "catalogo": page["catalogo"], "locked": False,
        "stato": page["stato"], "revisore": page.get("revisore"), "suggerimenti": page.get("suggerimenti", []),
    }


def restock(catalog=CATALOG, requests=REQUESTS):
    with closing(sqlite3.connect(catalog.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        low = db.execute(
            "SELECT codice, nome, quantita FROM prodotti WHERE quantita <= ? ORDER BY quantita, codice",
            (LOW_STOCK,),
        ).fetchall()
    with closing(sqlite3.connect(requests)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS richieste (
            codice TEXT PRIMARY KEY, nome TEXT NOT NULL, quantita INTEGER NOT NULL,
            creata TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        db.executemany("""INSERT INTO richieste (codice, nome, quantita) VALUES (?, ?, ?)
            ON CONFLICT(codice) DO UPDATE SET nome=excluded.nome, quantita=excluded.quantita
            WHERE nome != excluded.nome OR quantita != excluded.quantita""", low)
        current = {code for code, _, _ in low}
        obsolete = [(code,) for (code,) in db.execute("SELECT codice FROM richieste") if code not in current]
        db.executemany("DELETE FROM richieste WHERE codice = ?", obsolete)
        return [{"codice": code, "nome": name, "quantita": qty} for code, name, qty in low]


@lru_cache(maxsize=1)
def load_model(path):
    from vosk import Model, SetLogLevel
    SetLogLevel(-1)
    return Model(str(path))




class Listening:
    def __init__(self, catalog=CATALOG, requests=REQUESTS, settings=SETTINGS, clock=time.monotonic):
        self.lock = threading.RLock()
        self.analysis_lock = threading.Lock()
        self.audio_lock = threading.Lock()
        self.catalog, self.requests, self.settings, self.clock = catalog, requests, settings, clock
        self.catalog_cache_lock = threading.Lock()
        self.catalog_cache_stamp = None
        self.catalog_cache = None
        self.stop_event = threading.Event()
        self.lease_timer = None
        self.whisper_server = None
        self.whisper_worker_stop = None
        self.agent_epoch = 0
        self.state = {"version": 0, "action_version": 0, "restock": []}
        self._replace()

    def _catalog_material(self):
        paths = (self.catalog, Path(str(self.catalog) + "-wal"))
        stamp = []
        for path in paths:
            try:
                stat = path.stat()
                stamp.append((str(path.resolve()), stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns))
            except OSError:
                stamp.append((str(path), None, None, None))
        stamp = tuple(stamp)
        with self.catalog_cache_lock:
            if self.catalog_cache is None or self.catalog_cache_stamp != stamp:
                products, pages = reference_material(self.catalog)
                terms = product_aliases(products, pages)
                self.catalog_cache = (products, pages, terms)
                self.catalog_cache_stamp = stamp
            return self.catalog_cache

    def _replace(self, session="spenta", microphone="spento", error=None):
        config = load_configuration(self.settings) if session == "raccogliendo" else None
        try:
            self.agent_config = load_agent_settings(self.settings) if config else dict(phase_agent.DEFAULT_SETTINGS)
        except (OSError, ValueError):
            self.agent_config = dict(phase_agent.DEFAULT_SETTINGS)
        self.stop_event.set()
        if self.whisper_worker_stop is not None:
            self.whisper_worker_stop.set()
            self.whisper_worker_stop = None
        if self.whisper_server is not None:
            self.whisper_server.stop()
            self.whisper_server = None
        self.stop_event = threading.Event()
        try:
            self.speech_engine = load_speech_engine(self.settings)
            self.input_device = load_input_device(self.settings)
        except (OSError, ValueError):
            self.speech_engine = "vosk"
            self.input_device = None
        self.active_speech_engine = None
        if self.lease_timer is not None:
            self.lease_timer.cancel()
            self.lease_timer = None
        self.leased = False
        self.started_at = self.clock()
        self.deadline = self.started_at + LEASE_SECONDS
        self.config = config
        self.state = {
            "schema_version": 1, "session_id": uuid4().hex, "version": self.state["version"] + 1,
            "action_version": self.state["action_version"] + 1,
            "status": {"session": session, "microphone": microphone, "error_code": error},
            "transcript": {"revision": 0, "final_segments": [], "partial": None, "testo": ""},
            "phase": phase(), "recipient": unknown_recipient(), "evidence": [], "cards": [],
            "desk_phase": desk_phase(),
            "sales_stage": "collecting", "closing_signal": None, "symptom_matches": [],
            "desk_results": empty_desk_results(),
            "product": {"candidate_code": None, "selected_code": None, "confirmed_code": None,
                        "confirmed_by": None, "current_code": None, "current_state": "none",
                        "display": None, "commercial": dict(EMPTY_COMMERCIAL)},
            "cart": serialize_cart(empty_cart()),
            "offers": [], "stock": [], "service": public_service(), "restock": self.state["restock"],
        }
        self.auto_cards, self.manual_cards, self.locked_cards = [], [], {}
        self.manual_phase = self.manual_recipient = self.manual_service = None
        self.stability, self.applied_corrections, self.suppressed = {}, set(), set()
        self.segment_start = 0
        self.segment_sequence = 0
        self.discarded_transcript_units = 0
        self.final_word_count = 0
        self.agent_words_sent = 0
        self.agent_after_units = 0
        self.agent_skip_next_final = False
        self.agent_last_transition = None
        self.agent_pending = None
        self.agent_result_stamp = None
        self.agent_evidence = []
        self.local_desk_phase = desk_phase()
        self.voice_event = None
        self.speech_alternatives = ()
        self.manual_name_correction = None
        self.last_voice = None
        self.analyzed_revision = -1
        self.next_evaluation = 0
        self.next_inventory = 0
        self.cosmetic_complement = False
        self.complement_eligible = False

    def start(self, *, background=True):
        with self.lock:
            self._replace("raccogliendo", "avvio")
            self._renew_lease()
            current, stop = self.state["session_id"], self.stop_event
            diagnostic("audio", "avvio")
            if background:
                threading.Thread(target=self._run_audio, args=(current, stop), daemon=True).start()
                threading.Thread(target=self._run_analysis, args=(current, stop), daemon=True).start()
            return deepcopy(self.state)

    def stop(self):
        with self.lock:
            self._replace()

    def _active(self):
        return self.state["status"]["microphone"] in {"avvio", "attivo"}

    def _renew_lease(self):
        self.leased = True
        self.deadline = self.clock() + LEASE_SECONDS
        if self.lease_timer is None:
            self._schedule_expiry(LEASE_SECONDS)

    def _schedule_expiry(self, delay):
        self.lease_timer = threading.Timer(delay, self._lease_elapsed, args=(self.state["session_id"],))
        self.lease_timer.daemon = True
        self.lease_timer.start()

    def _lease_elapsed(self, session_id):
        with self.lock:
            if session_id != self.state["session_id"]:
                return
            remaining = self.deadline - self.clock()
            if remaining > 0:
                self._schedule_expiry(remaining)
            else:
                self._expire()

    def _expire(self):
        if self.leased and self.clock() >= self.deadline:
            diagnostic("audio", "lease_scaduta", duration=self.clock() - self.started_at)
            self._replace()

    def snapshot(self, session_id=None, *, inventory=False):
        with self.lock:
            self._expire()
            if session_id == self.state["session_id"] and self.leased:
                self._renew_lease()
            if inventory and self.clock() >= self.next_inventory:
                self.next_inventory = self.clock() + 1
                self._refresh_inventory()
            return deepcopy(self.state)

    def finish(self, session_id, error=None):
        with self.lock:
            if session_id != self.state["session_id"]:
                return
            duration = self.clock() - self.started_at
            if error:
                diagnostic("audio", error, "errore", duration)
            diagnostic("audio", "sessione_chiusa", duration=duration)
            self._replace("errore" if error else "spenta", "errore" if error else "spento", error)

    def ingest(self, session_id, fragment, *, final=False, alternatives=()):
        with self.lock:
            self._expire()
            if session_id != self.state["session_id"] or not self._active():
                return False
            fragment = fragment.strip()[-4096:]
            self._close_if_idle(before_ingest=True)
            transcript = self.state["transcript"]
            before = transcript["testo"]
            old_partial = transcript["partial"]
            if final:
                transcript["partial"] = None
                if fragment:
                    self.speech_alternatives = (fragment, tuple(value[:4096] for value in alternatives[:2])) if alternatives else ()
                    self.state["desk_results"]["correction_options"] = []
                    transcript["final_segments"].append({"text": fragment})
                    self.final_word_count += len(re.findall(r"[^\W_]+(?:['’][^\W_]+)*", fragment))
                    if len(transcript["final_segments"]) > 64:
                        discarded = transcript["final_segments"].pop(0)
                        self.discarded_transcript_units += utf16_length(discarded["text"]) + 1
                        self.segment_start = max(0, self.segment_start - 1)
                elif old_partial is None:
                    return False
                if self.agent_skip_next_final:
                    self.agent_skip_next_final = False
                    self.agent_after_units = self._absolute_final_end()
                    self.agent_words_sent = self.final_word_count
            else:
                transcript["partial"] = {"text": fragment} if fragment else None
                if transcript["partial"] == old_partial:
                    return False
            pieces = [item["text"] for item in transcript["final_segments"]]
            if transcript["partial"]:
                pieces.append(transcript["partial"]["text"])
            transcript["testo"] = " ".join(pieces)
            transcript["revision"] += 1
            self.state["desk_phase"] = self.local_desk_phase
            if fragment:
                self.last_voice = self.clock()

            # Evidence with unchanged spans can stay while the newest revision is analyzed.
            after = transcript["testo"]
            prefix_end = next((i for i, (old, new) in enumerate(zip(before, after)) if old != new),
                              min(len(before), len(after)))
            safe_end = utf16_length(after[:prefix_end])
            remaining = [item for item in self.state["evidence"] if item["span"]["end"] <= safe_end]
            for item in remaining:
                item["span"]["transcript_revision"] = transcript["revision"]
            self.state["evidence"] = remaining
            valid_ids = {item["id"] for item in remaining}
            current_evidence = {item["id"]: item for item in remaining}
            self.state["symptom_matches"] = [
                {**match,
                 "span": current_evidence[match["evidence_id"]]["span"],
                 "evidence_state": current_evidence[match["evidence_id"]].get("state")}
                for match in self.state.get("symptom_matches", [])
                if match.get("evidence_id") in current_evidence
            ]
            results = self.state["desk_results"]
            if not results["previous"] and any(
                    not set(row["evidence_ids"]) <= valid_ids for row in results["rows"]):
                self.state["desk_results"] = empty_desk_results()
            else:
                results["supplements"] = [row for row in results["supplements"]
                                          if set(row["evidence_ids"]) <= valid_ids]
                results["offers"] = [row for row in results["offers"] if set(row["evidence_ids"]) <= valid_ids]
                if self.voice_event and self.voice_event["evidence_id"] not in valid_ids:
                    results.update(voice_choice=None, voice_options=[], preference_codes=[])
                    self.voice_event = None
            self.auto_cards = [card for card in self.auto_cards if set(card["evidence_ids"]) <= valid_ids]
            self.state["offers"] = [offer for offer in self.state["offers"] if offer["matched_evidence_id"] in valid_ids]
            self._rebuild_cards()
            product = self.state["product"]
            candidate = product["candidate_code"]
            if candidate and not any(item["kind"] == "product_candidate" and candidate in item["product_codes"]
                                     for item in remaining):
                product["candidate_code"] = None
            codes = self._visible_product_codes()
            self.state["stock"] = [row for row in self.state["stock"] if row["product_code"] in codes]
            self.state["version"] += 1
            return True

    def _close_if_idle(self, *, before_ingest=False):
        transcript = self.state["transcript"]
        if (self.last_voice is None or transcript["partial"] is not None
                or self.clock() - self.last_voice < self.config["pausa_secondi"]):
            return
        if not before_ingest and (self.analyzed_revision != transcript["revision"]
                                  or self.clock() < self.next_evaluation < math.inf):
            return
        self.last_voice = None
        self.speech_alternatives = ()
        self.manual_name_correction = None
        self.segment_start = len(transcript["final_segments"])
        self.segment_sequence += 1
        self.agent_words_sent = self.final_word_count
        self.agent_after_units = self._absolute_final_end()
        self.agent_evidence = []
        self.agent_last_transition = None
        self.agent_result_stamp = None
        self.local_desk_phase = desk_phase()
        self.state["desk_phase"] = self.local_desk_phase
        self.voice_event = None
        self.stability.clear()
        self.applied_corrections.clear()
        self.suppressed.clear()
        self._clear_choice()
        self.auto_cards = []
        self._rebuild_cards()
        self.state.update(evidence=[], symptom_matches=[], offers=[], stock=[], sales_stage="collecting")
        current = self.state["desk_results"]
        if current["rows"]:
            self.state["desk_results"] = {**empty_desk_results(), "rows": current["rows"],
                                          "preferred_code": current["preferred_code"],
                                          "recognized_name": current["recognized_name"], "previous": True}
        else:
            self.state["desk_results"] = empty_desk_results()
        self.state["version"] += 1

    def _context(self):
        transcript = self.state["transcript"]
        finals = transcript["final_segments"]
        start = sum(len(segment["text"]) + 1 for segment in finals[:self.segment_start])
        segments = [segment["text"] for segment in finals]
        if transcript["partial"]:
            segments.append(transcript["partial"]["text"])
        # A final segment closes a clause. A single-character delimiter preserves displayed offsets.
        final_end = sum(len(segment["text"]) + 1 for segment in finals)
        return transcript["testo"], "\n".join(segments)[start:], start, final_end

    def evaluate(self):
        if not self.analysis_lock.acquire(blocking=False):
            return
        try:
            with self.lock:
                self._expire()
                if not self._active():
                    return
                self._close_if_idle()
                revision = self.state["transcript"]["revision"]
                if revision == self.analyzed_revision and self.clock() < self.next_evaluation:
                    self._schedule_agent()
                    return
                session_id = self.state["session_id"]
                segment_start = self.segment_start
                text, context, start, final_end = self._context()
                partial = self.state["transcript"]["partial"] is not None
                speech_alternatives = self.speech_alternatives
            products, pages, terms = self._catalog_material()
            result = analyze(context, terms, partial=partial,
                             finalized_end=max(0, final_end - start))
            if speech_alternatives and not partial:
                result["correction_codes"] = find_alternative_codes(*speech_alternatives, terms)
            with self.lock:
                self._expire()
                if (session_id != self.state["session_id"] or revision != self.state["transcript"]["revision"]
                        or segment_start != self.segment_start):
                    return
                self._apply_interpretation(result, pages, text, start, final_end, revision)
        finally:
            self.analysis_lock.release()

    def _apply_interpretation(self, result, pages, text, start, final_end, revision):
        now = self.clock()
        gate = self.started_at + self.config["ritardo_secondi"]
        self.analyzed_revision = revision
        next_evaluation = gate if now < gate else math.inf
        stable, finalized_evidence, observed = [], [], {}
        for item in result["evidence"]:
            a, b = item["span"]["start"] + start, item["span"]["end"] + start
            if not 0 <= a < b <= len(text):
                continue
            signature = (item["rule_id"], a, normalize(text[a:b]), tuple(item["product_codes"]))
            observed[signature] = self.stability.get(signature, now)
            stable_at = observed[signature] + STABLE_SECONDS
            finalized = b < final_end
            if finalized:
                finalized_evidence.append({
                    **item, "state": "active",
                    "span": {"start": utf16_length(text[:a]), "end": utf16_length(text[:b]),
                             "transcript_revision": revision},
                })
            if not finalized and now < stable_at:
                next_evaluation = min(next_evaluation, stable_at)
            if now >= gate and (finalized or now >= stable_at or item["kind"] in
                                {"correction", "negation", "refusal", "symptom_exclusion", "spoken_exclusion"}):
                stable.append({
                    **item, "state": "active" if finalized else "provisional",
                    "span": {"start": utf16_length(text[:a]), "end": utf16_length(text[:b]),
                             "transcript_revision": revision},
                })
        self.stability = observed
        self.next_evaluation = next_evaluation
        self._update_desk_phase(finalized_evidence, result["recipient"])
        self._schedule_agent()
        if now < gate:
            return

        before = deepcopy(self.state)
        self.state["status"]["session"] = "attiva"
        self.state["evidence"] = stable
        latest_topics = {}
        for item in stable:
            concept_id = item.get("concept_id")
            if item.get("kind") != "topic" or not concept_id or not item.get("id"):
                continue
            previous = latest_topics.get(concept_id)
            if previous is None or item["span"]["end"] > previous["span"]["end"]:
                latest_topics[concept_id] = item

        # Candidate indication matches are informational only. Keep them tied
        # to the exact active topic evidence and the same transcript revision.
        symptom_matches = []
        latest_by_product = {}
        for concept_id, evidence in latest_topics.items():
            if evidence.get("state") not in {"active", "provisional"}:
                continue
            for match in symptom_product_matches(
                    [concept_id], catalog=self.catalog, species_scope=evidence.get("species_scope", "umana")):
                symptom_match = {
                    **match,
                    "evidence_id": evidence["id"],
                    "span": evidence["span"],
                    "evidence_state": evidence["state"],
                    "matched_term": evidence.get("matched_term"),
                }
                symptom_matches.append(symptom_match)
                # A product linked to multiple simultaneously mentioned symptoms is
                # rendered once, tied to its latest supporting symptom evidence.
                key = symptom_match.get("product_code")
                previous = latest_by_product.get(key)
                if key and (previous is None or symptom_match["span"]["end"] > previous["span"]["end"]):
                    latest_by_product[key] = symptom_match
        self.state["symptom_matches"] = list(latest_by_product.values())
        product = self.state["product"]
        current_code = product.get("current_code") or product.get("confirmed_code") \
            or product.get("selected_code") or product.get("candidate_code")
        active_codes = self._active_product_codes()
        choice_retracted = False
        for item in stable:
            key = (item["kind"], item["span"]["start"], tuple(item["product_codes"]))
            unbound_refusal_targets_current = (
                item["kind"] == "refusal" and not item["product_codes"]
                and current_code is not None and active_codes == {current_code}
            )
            unbound_past_targets_current = (
                item["kind"] == "past" and not item["product_codes"]
                and current_code is not None and active_codes == {current_code}
            )
            excluded_current_mention = (
                item["kind"] == "product_mention" and item.get("mention_context") == "excluded"
                and current_code in item["product_codes"]
            )
            retracts_current = item["kind"] == "correction" or (
                item["kind"] in {"negation", "refusal"}
                and (current_code in item["product_codes"] or unbound_refusal_targets_current)
            ) or excluded_current_mention or unbound_past_targets_current
            if retracts_current and key not in self.applied_corrections:
                self.applied_corrections.add(key)
                self._clear_choice(suppress=(item["kind"] in {"negation", "refusal"}
                                             or excluded_current_mention
                                             or unbound_past_targets_current))
                choice_retracted = True
            elif item["kind"] == "product_mention" and item.get("mention_context") == "excluded":
                self.applied_corrections.add(key)

        # A newer explicit product event can re-enable a code suppressed by an
        # earlier negation, refusal, or past-use mention. Keep the exclusion
        # barrier tied to its transcript position so old evidence cannot return.
        code_barriers = {}
        global_barrier = -1
        for item in stable:
            if item["kind"] in {"negation", "refusal", "spoken_exclusion"} or (
                    item["kind"] == "product_mention" and item.get("mention_context") == "excluded"):
                for code in item["product_codes"]:
                    code_barriers[code] = max(code_barriers.get(code, -1), item["span"]["start"])
        for kind, position, codes in self.applied_corrections:
            if kind in {"negation", "refusal", "product_mention"}:
                for code in codes:
                    code_barriers[code] = max(code_barriers.get(code, -1), position)
            if kind == "correction" or (kind in {"refusal", "past"} and not codes):
                global_barrier = max(global_barrier, position)

        latest_positive_start = {}
        for item in stable:
            if item["kind"] not in {"product_candidate", "proposal", "acceptance", "product_mention"}:
                continue
            if item["kind"] == "product_mention" and item.get("mention_context") != "neutral":
                continue
            for code in item["product_codes"]:
                latest_positive_start[code] = max(latest_positive_start.get(code, -1), item["span"]["start"])
        for code in tuple(self.suppressed):
            if latest_positive_start.get(code, -1) > max(code_barriers.get(code, -1), global_barrier):
                self.suppressed.discard(code)

        segments = [item["text"] for item in self.state["transcript"]["final_segments"]]
        if self.state["transcript"]["partial"]:
            segments.append(self.state["transcript"]["partial"]["text"])
        segment_boundaries = []
        cursor = 0
        for index, segment in enumerate(segments):
            cursor += len(segment)
            if index + 1 < len(segments):
                segment_boundaries.append(cursor)
                cursor += 1
        product_events = [item for item in stable
                          if item["kind"] in {"product_candidate", "proposal", "acceptance", "product_mention"}
                          and item["product_codes"]
                          and (item["kind"] != "product_mention" or item.get("mention_context") == "neutral")]
        event_clauses = {}
        clause_codes = {}
        for item in product_events:
            bounds = _clause_bounds(text, item["span"], segment_boundaries)
            event_clauses[id(item)] = bounds
            clause_codes.setdefault(bounds, set()).update(item["product_codes"])
        for item in stable:
            if item["kind"] == "spoken_match" and item["state"] == "active":
                event_clauses[id(item)] = _clause_bounds(text, item["span"], segment_boundaries)
        if self.manual_name_correction:
            corrected, boundary = self.manual_name_correction
            newer_name = any(
                item["state"] == "active" and self.discarded_transcript_units + item["span"]["start"] >= boundary
                for item in [*product_events, *(entry for entry in stable if entry["kind"] == "spoken_match")]
            )
            if newer_name or product["selected_code"] != corrected:
                self.manual_name_correction = None
            else:
                product_events = [item for item in product_events
                                  if self.discarded_transcript_units + item["span"]["start"] >= boundary]
        ambiguous_clauses = {bounds for bounds, codes in clause_codes.items() if len(codes) > 1}
        ambiguous_events = {id(item) for item in product_events
                            if event_clauses[id(item)] in ambiguous_clauses}

        eligible_candidates = [item for item in product_events
                               if item["kind"] in {"product_candidate", "proposal", "acceptance"}
                               and id(item) not in ambiguous_events]
        candidate_codes = [code for code in result["candidate_codes"] if code not in self.suppressed
                           and any(code in item["product_codes"] for item in eligible_candidates)]
        candidates = [
            (item["span"]["end"], code, item["kind"])
            for item in eligible_candidates
            for code in item["product_codes"] if code in candidate_codes
        ]
        latest_candidate = max(candidates, default=None)
        neutral_mentions = [item for item in product_events if item["kind"] == "product_mention"
                            and item.get("mention_context") == "neutral"
                            and len(item["product_codes"]) == 1
                            and id(item) not in ambiguous_events
                            and item["product_codes"][0] not in self.suppressed
                            and item["span"]["start"] > max(
                                code_barriers.get(item["product_codes"][0], -1), global_barrier)]
        latest_mention = max(neutral_mentions, key=lambda item: item["span"]["end"], default=None)

        if latest_mention and (not latest_candidate or latest_mention["span"]["end"] > latest_candidate[0]):
            product["candidate_code"] = None
            product["current_code"] = latest_mention["product_codes"][0]
            product["current_state"] = "mentioned"
        elif latest_candidate:
            product["candidate_code"] = latest_candidate[1]
            product["current_code"] = latest_candidate[1]
            product["current_state"] = "proposed" if latest_candidate[2] == "proposal" else "provisional"
        elif choice_retracted:
            product["candidate_code"] = None
            product["current_code"] = None
            product["current_state"] = "none"
        self.auto_cards = []
        for page in pages.values():
            code = (page["catalogo"] or {}).get("codice")
            supporting = [item for item in stable
                          if (item["kind"] in {"product_candidate", "proposal", "acceptance"}
                              and code in candidate_codes and code in item["product_codes"])
                          or (item["kind"] == "topic" and item["source"]["id"] == page["scheda"])]
            if supporting:
                self.auto_cards.append(reference_card(page, "provisional", supporting))
        self.auto_cards = self.auto_cards[:4]

        recipient = deepcopy(result["recipient"]) if any(item["kind"] == "recipient" for item in stable) else unknown_recipient()
        if recipient["kind"] == "se":
            recipient["kind"] = "sé"
        self.state["recipient"] = self.manual_recipient or recipient

        stage_events = [item for item in stable if item["kind"] == "sales_stage_signal"
                        and item.get("sales_stage") in SALES_STAGES]
        latest_stage_event = max(stage_events, key=lambda item: item["span"]["end"], default=None)
        closing_events = [item for item in stable if item["kind"] == "closing_signal"]
        latest_closing_event = max(closing_events, key=lambda item: item["span"]["end"], default=None)
        if latest_stage_event:
            self.state["sales_stage"] = latest_stage_event["sales_stage"]
        elif latest_closing_event:
            self.state["sales_stage"] = "closing"
        if self.state["sales_stage"] == "closing" and latest_closing_event:
            signal = latest_closing_event.get("closing_signal") or latest_closing_event.get("signal")
            self.state["closing_signal"] = signal if signal in {"serve_altro", "desidera_altro", "vuole_altro"} else None
        else:
            self.state["closing_signal"] = None

        proposal_for_current = any(item["kind"] == "proposal" and product.get("current_code") in item["product_codes"]
                                   for item in stable)
        stage_allows_complements = self.state["sales_stage"] in {"proposal", "closing"}
        self.complement_eligible = bool(product.get("current_code") and product.get("current_state") != "mentioned"
                                        and not choice_retracted and stage_allows_complements
                                        and (proposal_for_current or self.state["sales_stage"] == "closing"))

        service_kind = result["service"]["kind"]
        if not any(item["kind"] == f"service_{service_kind}" for item in stable):
            service_kind = None
        if self.manual_service is None:
            self.state["service"] = public_service(service_kind, config=self.config)
        self.cosmetic_complement = any(item["kind"] == "cosmetic_removal" for item in stable)

        self._refresh_offers()

        if self.manual_phase:
            current_phase = self.manual_phase
        elif product["confirmed_code"]:
            current_phase = phase("Consiglio confermato", "manuale", "Il farmacista ha confermato il prodotto.")
        elif product["selected_code"] or product["candidate_code"]:
            current_phase = phase("Verifica prodotto", reason="Prodotto identificato stabilmente nella conversazione.")
        elif self.state["service"]["kind"] or stable and result["phase"]["value"] == "Domande":
            current_phase = result["phase"]
        else:
            current_phase = phase("Domande", reason="Manca un contesto sufficientemente chiaro.",
                                  missing=["Quale prodotto, informazione o servizio serve?"])
        self.state["phase"] = current_phase
        self._rebuild_cards()
        self._refresh_stock()
        correction_options = self.state["desk_results"]["correction_options"]
        if "correction_codes" in result:
            correction_options = [row for code in result["correction_codes"]
                                  if (row := self._desk_row(code, [], named=True))]
        self._refresh_desk_results(stable, latest_topics, symptom_matches, product_events, event_clauses,
                                   code_barriers, global_barrier, latest_closing_event)
        self.state["desk_results"]["correction_options"] = correction_options
        if self.state != before:
            self.state["version"] += 1

    def _absolute_final_end(self):
        return self.discarded_transcript_units + sum(
            utf16_length(segment["text"]) + 1 for segment in self.state["transcript"]["final_segments"])

    @staticmethod
    def _phase_key(item):
        if item["kind"] == "sale_phase":
            key = item.get("phase_key")
            return key if key in phase_agent.PHASE_LABELS else None
        if item["kind"] == "product_mention" and item.get("mention_context") == "excluded":
            return None
        if item["kind"] == "desk_choice" and not (item.get("choice_explicit") or item.get("choice_modifier_only")):
            return None
        return PHASE_BY_EVIDENCE.get(item["kind"])

    def _update_desk_phase(self, finalized_evidence, recipient):
        self.agent_evidence = finalized_evidence
        declared = recipient.get("kind") if recipient.get("source") == "dichiarato" else None
        self.agent_recipient = "sé" if declared == "se" else declared
        events = [(item, self._phase_key(item)) for item in finalized_evidence]
        priority = {"sale_phase": 2, "desk_choice": 1, "desk_preference": 1}
        selected = max(((item, key) for item, key in events if key),
                       key=lambda pair: (pair[0]["span"]["end"], priority.get(pair[0]["kind"], 0)),
                       default=None)
        self.local_desk_phase = desk_phase(
            selected[1], evidence_id=selected[0]["id"],
            reason=selected[0].get("reason") if selected[0]["kind"] == "sale_phase" else None
        ) if selected else desk_phase()
        if self.agent_result_stamp != self._agent_stamp() and self.state["desk_phase"] != self.local_desk_phase:
            self.state["desk_phase"] = self.local_desk_phase
            self.state["version"] += 1

    def _agent_stamp(self):
        return (self.state["session_id"], self.state["transcript"]["revision"],
                self.segment_sequence, self.agent_epoch)

    def _schedule_agent(self):
        settings = self.agent_config
        if not settings["enabled"] or settings["provider"] != "openai" or self.agent_pending is not None:
            return
        if self.state["transcript"]["revision"] != self.analyzed_revision:
            return
        absolute_end = self._absolute_final_end()
        if absolute_end <= self.agent_after_units:
            return
        start_units = max(self.agent_after_units, self.discarded_transcript_units,
                          absolute_end - 2400) - self.discarded_transcript_units
        strong = next((item for item in reversed(self.agent_evidence)
                       if item["kind"] in {"sale_phase", "desk_choice"} and self._phase_key(item)
                       and item["span"]["start"] >= start_units
                       and self.local_desk_phase["evidence_id"] == item["id"]), None)
        strong_key = self._phase_key(strong) if strong else None
        transition = (self.discarded_transcript_units + strong["span"]["start"], strong_key) if strong else None
        if self.final_word_count - self.agent_words_sent < settings["word_threshold"] and (
                transition is None or transition == self.agent_last_transition):
            return
        key = phase_agent.read_key()
        if not key or not phase_agent.REQUEST_SLOTS.acquire(blocking=False):
            return
        try:
            text = self.state["transcript"]["testo"]
            final_units = absolute_end - self.discarded_transcript_units - 1
            start = _codepoint_offset(text, start_units)
            end = _codepoint_offset(text, final_units)
            excerpt = text[start:end].strip()
            evidence = []
            for item in self.agent_evidence:
                span = item["span"]
                phase_key = self._phase_key(item)
                if span["start"] < start_units or span["end"] > final_units or (
                        not phase_key and item["kind"] != "recipient"):
                    continue
                a, b = (_codepoint_offset(text, span[field]) for field in ("start", "end"))
                evidence.append({"id": item["id"], "text": text[a:b], "kind": item["kind"],
                                 "phases": [phase_key] if phase_key else []})
            evidence = evidence[-24:]
            if not any(item["phases"] for item in evidence):
                evidence.append({"id": "segmento:" + str(absolute_end), "text": excerpt,
                                 "kind": "segment", "phases": ["clarify", "research"]})
            stamp = self._agent_stamp()
            recipient = self.agent_recipient if any(item["kind"] == "recipient" for item in evidence) else None
            future = phase_agent.EXECUTOR.submit(
                phase_agent.classify, settings["model"], key, excerpt, evidence, explicit_recipient=recipient)
        except Exception:
            phase_agent.REQUEST_SLOTS.release()
            diagnostic("agente", "provider_non_disponibile", "errore")
            return
        self.agent_pending = stamp
        self.agent_after_units = absolute_end
        self.agent_words_sent = self.final_word_count
        self.agent_last_transition = transition
        future.add_done_callback(lambda ready: self._receive_agent(ready, stamp, strong_key, evidence, recipient))

    def _receive_agent(self, future, stamp, strong_key, evidence, recipient):
        phase_agent.REQUEST_SLOTS.release()
        try:
            result = phase_agent.validate_response(future.result(), evidence, recipient)
        except phase_agent.ProviderError as error:
            code = str(error) if str(error) in DIAGNOSTIC_CODES["agente"] else "provider_non_disponibile"
            result = None
        except Exception:
            code, result = "provider_non_disponibile", None
        with self.lock:
            self._expire()
            if self.agent_pending == stamp:
                self.agent_pending = None
            if stamp != self._agent_stamp() or not self._active() or not self.agent_config["enabled"]:
                return
            if result is None:
                diagnostic("agente", code, "errore")
                return
            if strong_key and result["phase"] != strong_key:
                return
            self.state["desk_phase"] = desk_phase(result["phase"], evidence_id=result["evidence_id"], source="openai")
            self.agent_result_stamp = stamp
            self.state["version"] += 1

    def _desk_row(self, code, references, *, named=False, evidence_ids=(), topic_names=(), approved=False):
        summary = product_display(code, catalog=self.catalog)
        if not summary:
            return None
        symptoms = list(dict.fromkeys(item["concept_name"] for item in references if item.get("concept_name")))
        uncovered = [name for name in topic_names if name not in symptoms]
        affinity = round(100 * (len(topic_names) - len(uncovered)) / len(topic_names)) if topic_names else None
        count = len(symptoms)
        if count:
            label = "Alta" if affinity == 100 else "Parziale"
            noun = "sintomo documentato" if count == 1 else "sintomi documentati"
            relevance = f"{label} · {count} {noun}"
        elif approved:
            relevance = "Abbinamento revisionato"
        elif named:
            relevance = "Nome rilevato"
        else:
            relevance = ""
        return {"code": code, **summary, "relevance": relevance, "symptoms": symptoms, "named": named,
                "affinity_percent": affinity, "covered_symptoms": symptoms, "uncovered_symptoms": uncovered,
                "references": references, "evidence_ids": list(dict.fromkeys(evidence_ids)),
                "variants": knowledge.documented_variants(code, catalog=self.catalog)}

    def _refresh_desk_results(self, stable, topics, matches, product_events, event_clauses,
                              code_barriers, global_barrier, closing):
        previous = self.state["desk_results"]
        spoken = [item for item in stable if item["kind"] == "spoken_match" and item["state"] == "active"]
        if self.manual_name_correction:
            _, boundary = self.manual_name_correction
            spoken = [item for item in spoken
                      if self.discarded_transcript_units + item["span"]["start"] >= boundary]
        named_events = [*product_events, *spoken]
        named_events = [item for item in named_events if any(
            code not in self.suppressed and item["span"]["start"] > max(
                global_barrier, code_barriers.get(code, -1)) for code in item["product_codes"])]
        latest = max(named_events, key=lambda item: item["span"]["end"], default=None)
        active_names = ([item for item in named_events if event_clauses[id(item)] == event_clauses[id(latest)]]
                        if latest else [])

        named_by_code = {}
        if self.manual_name_correction:
            named_by_code[self.manual_name_correction[0]] = []
        for item in active_names:
            for code in item["product_codes"]:
                if code not in self.suppressed and item["span"]["start"] > max(
                        global_barrier, code_barriers.get(code, -1)):
                    named_by_code.setdefault(code, []).append(item["id"])
        references = {}
        for match in matches:
            code = match["product_code"]
            if code not in self.suppressed and (code not in code_barriers or code in named_by_code):
                references.setdefault(code, []).append(match)

        topic_labels = {match["concept_id"]: match["concept_name"] for match in matches}
        topic_names = tuple(topic_labels.get(topic_id, topic_id.replace("-", " ").capitalize()) for topic_id in topics)

        rows = []
        scores = {}
        for code in dict.fromkeys([*named_by_code, *references]):
            links = references.get(code, [])
            row = self._desk_row(code, links, named=code in named_by_code, topic_names=topic_names,
                                 evidence_ids=[*named_by_code.get(code, []), *(link["evidence_id"] for link in links)])
            if not row:
                continue
            if row["display"]["category"].casefold() in SUPPLEMENT_CATEGORIES and code not in named_by_code:
                continue
            row["variants"] = [variant for variant in row["variants"]
                               if variant["code"] == code or (variant["code"] not in code_barriers
                                                            and variant["code"] not in self.suppressed)]
            rows.append(row)
            scores[code] = (code in named_by_code, len(row["symptoms"]))
        rows.sort(key=lambda row: (not scores[row["code"]][0], -scores[row["code"]][1],
                                   row["display"]["name"].casefold()))
        preferred = rows[0]["code"] if rows and len(named_by_code) <= 1 and (
            len(rows) == 1 or scores[rows[0]["code"]] > scores[rows[1]["code"]]) else None
        grouped_codes = set()
        compact_rows = []
        for row in rows:
            if row["code"] not in grouped_codes:
                compact_rows.append(row)
                grouped_codes.update(item["code"] for item in row["variants"])
        rows = compact_rows
        if preferred is not None and not any(row["code"] == preferred for row in rows):
            preferred = None

        result = {**empty_desk_results(), "rows": rows, "preferred_code": preferred,
                  "recognized_name": latest.get("recognized_name") if latest else None}
        if not rows and previous["previous"]:
            withdrawn_codes = {code for item in stable if item["kind"] in
                               {"spoken_exclusion", "negation", "refusal", "product_mention"}
                               and (item["kind"] != "product_mention" or item.get("mention_context") == "excluded")
                               for code in item["product_codes"]}
            if (len(previous["rows"]) == 1 and previous["preferred_code"]
                    and not withdrawn_codes):
                # A pronoun can refer back to one unambiguous result even after
                # the search segment has closed. "Non voglio altro" is not such a refusal.
                text = self.state["transcript"]["testo"]
                for item in stable:
                    if item["kind"] != "refusal" or item["product_codes"]:
                        continue
                    span = item["span"]
                    start = _codepoint_offset(text, span["start"])
                    end = _codepoint_offset(text, span["end"])
                    if re.fullmatch(r"non\s+(?:lo|la|li|le|ne)\s+(?:voglio|vorrei|prendo)(?:\s+pi[uù])?",
                                    text[start:end], re.IGNORECASE):
                        withdrawn_codes.add(previous["preferred_code"])
                        break
            withdrawn_topics = {item.get("concept_id") for item in stable if item["kind"] == "symptom_exclusion"}
            if not any(item["kind"] == "correction" for item in stable):
                retained = []
                for row in previous["rows"]:
                    if row["code"] in withdrawn_codes:
                        continue
                    links = [link for link in row["references"] if link.get("concept_id") not in withdrawn_topics]
                    if len(links) != len(row["references"]):
                        if not links and not row["named"]:
                            continue
                        row = self._desk_row(row["code"], links, named=row["named"])
                    if row:
                        retained.append(row)
                if retained:
                    preferred = previous["preferred_code"]
                    if not any(row["code"] == preferred for row in retained):
                        preferred = None
                    recognized_name = (previous["recognized_name"]
                                       if any(row["named"] for row in retained) else None)
                    result = {**previous, "rows": retained, "preferred_code": preferred, "supplements": [],
                              "recognized_name": recognized_name}
        declined_at = max((item["span"]["end"] for item in stable
                           if item["kind"] == "offer_decline" and item["state"] == "active"), default=-1)
        named_codes = set(latest["product_codes"]) if latest else set()
        extra_named = any(row["code"] in named_codes for row in previous["supplements"])
        offer_named = any(row["code"] in named_codes for row in previous["offers"])
        local_key = self.local_desk_phase["key"]
        checkout = self._phase_cue(stable, "closing")
        extras = self._phase_cue(stable, "extras")
        if closing and closing["state"] == "active" and (
                not extras or closing["span"]["end"] >= extras["span"]["end"]):
            extras = closing
        if (checkout and checkout["span"]["end"] > declined_at
                and (local_key == "closing" or previous["phase"] == "offer" and offer_named)):
            result["phase"] = "offer"
            result["offers"] = self._desk_offers(stable, checkout)
        elif (extras and extras["state"] == "active" and extras["span"]["end"] > declined_at
                and (local_key == "extras" or previous["phase"] == "offer" and extra_named)):
            result["phase"] = "offer"
            result["supplements"] = self._desk_supplements(result, references, named_by_code, extras, topics,
                                                            topic_names)
            self._add_documented_needs(result["supplements"], stable, extras)
            if extra_named and previous["phase"] == "offer":
                # An exact product name after the offer can refer to the extra
                # itself. Keep the displayed extra available for consultation.
                present = {row["code"] for row in result["supplements"]}
                valid_ids = {item["id"] for item in stable}
                result["supplements"].extend(row for row in previous["supplements"]
                                             if row["code"] not in present
                                             and set(row["evidence_ids"]) <= valid_ids)
        self._update_desk_voice(result, previous, stable, named_events, topics, code_barriers, global_barrier)
        if self.manual_name_correction:
            corrected = self.manual_name_correction[0]
            result.update(preferred_code=corrected, manual_corrected_code=corrected, voice_choice=None, voice_options=[])
        self.state["desk_results"] = result

    def _add_documented_needs(self, rows, stable, cue):
        needs = {}
        for item in sorted(stable, key=lambda evidence: evidence["span"]["end"]):
            if item["state"] != "active":
                continue
            if item["kind"] == "supplement_need":
                needs[item["concept_id"]] = item["id"]
            elif item["kind"] == "supplement_need_exclusion":
                needs.pop(item["concept_id"], None)
            elif item["kind"] in {"correction", "offer_decline"}:
                needs.clear()
        if not needs:
            return
        present = {row["code"] for row in rows}
        for link in knowledge.context_product_matches(needs, catalog=self.catalog):
            code = link["product_code"]
            if code in present:
                continue
            row = self._desk_row(code, [link], evidence_ids=[cue["id"], needs[link["concept_id"]]])
            if row and row["display"]["category"].casefold() in SUPPLEMENT_CATEGORIES:
                row.update(relevance="Bisogno documentato", symptoms=[], covered_symptoms=[])
                rows.append(row)
                present.add(code)

    @staticmethod
    def _phase_cue(stable, key):
        return max((item for item in stable if item["kind"] == "sale_phase" and item["state"] == "active"
                    and item.get("phase_key") == key), key=lambda item: item["span"]["end"], default=None)

    def _desk_offers(self, stable, closing):
        cart_codes = {row["code"] for row in self.state.get("cart", {}).get("items", [])}
        interests = {code: item for item in stable if item["kind"] == "commercial_intent"
                     and item["state"] == "active"
                     for code in item["product_codes"] if code not in self.suppressed}
        eligible_codes = set(interests) | cart_codes
        budgets = {code: item["budget_cent"] for code, item in interests.items() if item.get("budget_cent") is not None}
        offers = active_offers(date.today(), {"product_codes": eligible_codes, "budgets_by_code": budgets}, self.catalog)
        rows = []
        for offer in offers:
            code = offer["prodotto_codice"]
            interest = interests.get(code)
            evidence_ids = [closing["id"], *([interest["id"]] if interest else [])]
            row = self._desk_row(code, [], named=True, evidence_ids=evidence_ids)
            if row:
                # Promotions apply to one exact SKU; variant data belongs to
                # the product row and does not inherit the promotion.
                row["variants"] = []
                row["offer"] = {**offer, "data_fine": offer["fine"]}
                rows.append(row)
        return rows

    @staticmethod
    def _desk_visible_skus(results, sections=("rows", "supplements", "offers")):
        visible = {}
        for section in sections:
            for row in results[section]:
                for item in [row, *row["variants"]]:
                    visible[item["code"]] = (section, row, item["display"])
        return visible

    def _update_desk_voice(self, result, previous, stable, named_events, topics, code_barriers, global_barrier):
        directive = max((item for item in stable if item["kind"] in {"desk_choice", "desk_preference"}
                         and item["state"] == "active"), key=lambda item: item["span"]["end"], default=None)
        if not directive:
            self.voice_event = None
            return
        start, end = directive["span"]["start"], directive["span"]["end"]
        if (any(item["span"]["start"] >= end for item in [*topics.values(), *named_events])
                or any(item["span"]["start"] >= end for item in stable if item["kind"] in
                       {"correction", "negation", "refusal", "offer_decline", "spoken_exclusion"})):
            self.voice_event = None
            return

        token = f"{self.segment_sequence}:{self.discarded_transcript_units + start}:{end - start}:{directive['kind']}"
        if not self.voice_event or self.voice_event["token"] != token:
            named_codes = {code for item in named_events if start <= item["span"]["start"] < end
                           for code in item["product_codes"] if code not in self.suppressed
                           and item["span"]["start"] > max(global_barrier, code_barriers.get(code, -1))}
            reference = directive.get("choice_reference", False)
            visible = self._desk_visible_skus(previous)
            form = directive.get("choice_form")
            classification = directive.get("choice_classification")
            options = []
            form_only = directive.get("choice_modifier_only") and not previous["previous"]
            if named_codes or ((reference or form_only) and not directive.get("choice_has_name")):
                options = [code for code, (_, _, display) in visible.items()
                           if (not named_codes or code in named_codes)
                           and (not form or display.get("form_key") == form)
                           and (not classification or display.get("classification") == classification)
                           and code not in self.suppressed
                           and start >= max(global_barrier, code_barriers.get(code, -1))]
            sections = {code: visible[code][0] for code in options}
            main_codes = self._desk_visible_skus(previous, ("rows",))
            for code in options:
                if sections[code] == "offers" and sum(row["code"] == code for row in previous["offers"]) > 1:
                    # An exact SKU does not identify a particular promotion.
                    sections[code] = "rows" if code in main_codes else "offers"
            self.voice_event = {"token": token, "evidence_id": directive["id"], "codes": options,
                                "sections": sections}

        requested = self.voice_event["codes"]
        if not requested:
            return
        if not result["rows"] and previous["rows"] and not topics and any(
                code in self._desk_visible_skus({**empty_desk_results(), "rows": previous["rows"]})
                for code in requested):
            # A choice among the list, including a correction of the form,
            # can leave the search with no new terms. Keep those options in view.
            result.update(rows=previous["rows"], previous=previous["previous"],
                          preferred_code=previous["preferred_code"])
        visible = {}
        for section in ("rows", "supplements", "offers"):
            visible.update({code: slot for code, slot in self._desk_visible_skus(result, (section,)).items()
                            if self.voice_event["sections"].get(code) == section})
        options = [code for code in requested if code in visible]
        if directive["kind"] == "desk_preference":
            result["preference_codes"] = options
            choice = previous["voice_choice"]
            if choice and choice["code"] in self._desk_visible_skus(result, (choice["section"],)):
                result["voice_choice"] = choice
        elif len(options) > 1:
            result.update(voice_options=options, preferred_code=None)
        elif len(options) == 1 and len(requested) == 1:
            code = options[0]
            section, row, _ = visible[code]
            choice = {"code": code, "row_code": row["code"], "section": section, "token": token}
            if section == "offers":
                promotions = [offer["offer"]["codice"] for offer in result["offers"] if offer["code"] == code]
                if len(promotions) != 1:
                    return
                choice["offer_code"] = promotions[0]
            result["voice_choice"] = choice

    def _desk_supplements(self, result, references, named_by_code, closing, topics, topic_names):
        supplements = {}
        preferred = result["preferred_code"]
        approved_origin = preferred if preferred in named_by_code else None
        if result["previous"] and not topics:
            # A new turn can refer back explicitly to one identifiable result.
            # Its old symptoms are not used to search the new turn.
            if not closing.get("closing_reference"):
                return []
            reference_ids = {link["concept_id"] for row in result["rows"] for link in row["references"]
                             if link.get("concept_id")}
            if len(reference_ids) == 1:
                references = {}
                for link in symptom_product_matches(reference_ids, catalog=self.catalog):
                    references.setdefault(link["product_code"], []).append(link)
                topic_names = tuple(dict.fromkeys(link["concept_name"] for links in references.values() for link in links))
            elif not reference_ids and preferred and len(result["rows"]) == 1:
                approved_origin = preferred
        if topic_names:
            for code, links in references.items():
                if links[0]["product_display"]["category"].casefold() in SUPPLEMENT_CATEGORIES:
                    row = self._desk_row(code, links, topic_names=topic_names,
                                         evidence_ids=[closing["id"], *(link["evidence_id"] for link in links
                                                                       if link.get("evidence_id"))])
                    if row:
                        supplements[code] = row
        if approved_origin:
            for stock in stock_for([approved_origin], self.catalog, complement_eligible=True,
                                   include_unknown_complements=True):
                for link in stock["complements"]:
                    if link["review_status"] != "approvata" or not link.get("reviewer") or not link.get("source"):
                        continue
                    code = link["product_code"]
                    row = self._desk_row(code, [link], approved=True, topic_names=topic_names,
                                         evidence_ids=[closing["id"], *named_by_code.get(approved_origin, [])])
                    if row and row["display"]["category"].casefold() in SUPPLEMENT_CATEGORIES:
                        supplements.setdefault(code, row)
        return list(supplements.values())

    def _rebuild_cards(self):
        by_id = {card["id"]: card for card in self.auto_cards}
        by_id.update((card["id"], card) for card in self.manual_cards)
        by_id.update(self.locked_cards)
        self.state["cards"] = list(by_id.values())

    def _visible_product_codes(self):
        product = self.state["product"]
        codes = [code for code in (product["confirmed_code"], product["selected_code"], product["candidate_code"]) if code]
        codes.extend(code for card in self.state["cards"] for code in card["product_codes"])
        return codes

    @staticmethod
    def _source_snapshot(db, source_id):
        if not source_id:
            return None
        row = db.execute("SELECT id,url,titolo,ente,consultata_il,data_o_versione FROM fonti WHERE id=?",
                         (source_id,)).fetchone()
        if not row:
            return None
        return {"id": row["id"], "url": row["url"], "title": row["titolo"], "owner": row["ente"],
                "checked_at": row["consultata_il"], "version": row["data_o_versione"]}

    def _commercial_for_product(self, related_stock, base_commercial, dataset_type):
        commercial = {**EMPTY_COMMERCIAL, **(base_commercial or {})}
        commercial["complements"] = []
        with closing(sqlite3.connect(self.catalog.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            stock = next(iter(related_stock), None)
            if stock:
                # `stock_for` is queried only for the current product here.
                commercial["stock"] = stock.get("quantity", commercial.get("stock"))
                commercial["checked_at"] = stock.get("checked_at") or commercial.get("checked_at")
                if stock.get("quantity_source"):
                    commercial["stock_source"] = stock["quantity_source"]
            complements = []
            for relation in (stock or {}).get("complements", []):
                status = relation.get("stato_revisione") or relation.get("review_status")
                demo_allowed = (status == "demo" and dataset_type == "demo"
                                and relation.get("tipo") == "complemento_cosmetico" and self.cosmetic_complement)
                if status != "approvata" and not demo_allowed:
                    continue
                source = relation.get("source")
                if source is None and relation.get("fonte_id"):
                    source = self._source_snapshot(db, relation["fonte_id"])
                if source is None and relation.get("fonte"):
                    source = {"title": relation["fonte"]}
                complements.append({
                    "product_code": relation.get("product_code") or relation.get("codice_destinazione"),
                    "name": relation.get("nome"), "source": source, "review_status": status,
                    "conditions": relation.get("condizioni") or relation.get("conditions"),
                    "stock": relation.get("quantity"), "price_cents": relation.get("price_cents"),
                })
                if len(complements) == 3:
                    break
            commercial["complements"] = complements
        return commercial

    def _refresh_product_snapshot(self, stock_rows):
        product = self.state["product"]
        code = product.get("current_code")
        if not code:
            product["current_state"] = "none"
            product["display"] = None
            product["commercial"] = dict(EMPTY_COMMERCIAL)
            return
        summary = product_display(code, catalog=self.catalog)
        if not summary:
            product.update(current_code=None, current_state="none", display=None,
                           commercial=dict(EMPTY_COMMERCIAL))
            return
        display = summary.get("display", summary)
        base_commercial = summary.get("commercial", {})
        if not isinstance(display, dict):
            product.update(current_code=None, current_state="none", display=None,
                           commercial=dict(EMPTY_COMMERCIAL))
            return
        current_rows = list(stock_rows)
        if not any(row.get("product_code") == code for row in current_rows):
            current_rows.extend(stock_for(
                [code], self.catalog, confirmed=product.get("confirmed_code"),
                cosmetic_complement=self.cosmetic_complement,
                complement_eligible=self.complement_eligible,
            ))
        product["display"] = display
        current_only = [row for row in current_rows if row.get("product_code") == code]
        product["commercial"] = self._commercial_for_product(
            current_only, base_commercial, display.get("dataset_type"))

    def _refresh_stock(self):
        confirmed = self.state["product"]["confirmed_code"]
        stocks = stock_for(self._visible_product_codes(), self.catalog, confirmed, self.cosmetic_complement,
                           complement_eligible=self.complement_eligible)
        previous = self.state["stock"]
        if [{k: v for k, v in row.items() if k != "checked_at"} for row in stocks] != [
                {k: v for k, v in row.items() if k != "checked_at"} for row in previous]:
            self.state["stock"] = stocks
        self._refresh_product_snapshot(stocks)

    def _refresh_offers(self):
        current_code = self.state["product"].get("current_code")
        interests = {code: item for item in self.state["evidence"] if item["kind"] == "commercial_intent"
                     for code in item["product_codes"] if code not in self.suppressed and code == current_code}
        budgets = {code: item["budget_cent"] for code, item in interests.items() if item.get("budget_cent") is not None}
        self.state["offers"] = [
            {**row, "matched_evidence_id": interests[row["prodotto_codice"]]["id"]}
            for row in active_offers(date.today(), {"product_codes": list(interests), "budgets_by_code": budgets}, self.catalog)
        ]

    def _refresh_inventory(self):
        before = deepcopy(self.state)
        self.state["restock"] = restock(self.catalog, self.requests)
        self._refresh_stock()
        self._refresh_offers()
        results = self.state["desk_results"]
        if results["phase"] == "offer":
            stable = self.state["evidence"]
            closing = self._phase_cue(stable, "closing")
            results["offers"] = self._desk_offers(stable, closing) if closing else []
            if results["voice_choice"] and results["voice_choice"]["section"] == "offers" and not any(
                    row["offer"]["codice"] == results["voice_choice"].get("offer_code")
                    for row in results["offers"]):
                results["voice_choice"] = None
        if self.state != before:
            self.state["version"] += 1

    def _clear_choice(self, suppress=False):
        product = self.state["product"]
        previous = {code for code in (product.get("confirmed_code"), product.get("selected_code"),
                                      product.get("candidate_code"), product.get("current_code")) if code}
        if suppress:
            self.suppressed.update(previous)
        for key in ("candidate_code", "selected_code", "confirmed_code", "confirmed_by"):
            product[key] = None
        product.update(current_code=None, current_state="none", display=None, commercial=dict(EMPTY_COMMERCIAL))
        self.manual_cards = [card for card in self.manual_cards if not previous.intersection(card["product_codes"])]
        self.auto_cards = [card for card in self.auto_cards if not previous.intersection(card["product_codes"])]
        self.locked_cards = {key: card for key, card in self.locked_cards.items()
                             if not previous.intersection(card["product_codes"])}
        self.state["offers"] = [offer for offer in self.state["offers"] if offer["prodotto_codice"] not in previous]
        self.cosmetic_complement = False
        self.complement_eligible = False
        self.state["closing_signal"] = None
        self.state["sales_stage"] = "questions"
        if self.manual_phase and self.manual_phase["value"] == "Consiglio confermato":
            self.manual_phase = None

    def _active_product_codes(self):
        """Return distinct product codes visible or selected in the current desk state."""
        product = self.state["product"]
        codes = {code for code in (product.get("current_code"), product.get("confirmed_code"),
                                   product.get("selected_code"), product.get("candidate_code")) if code}
        for card in self.state.get("cards", []):
            codes.update(code for code in card.get("product_codes", []) if code)
        for card in self.auto_cards + self.manual_cards + list(self.locked_cards.values()):
            codes.update(code for code in card.get("product_codes", []) if code)
        return codes

    def manual_search(self, text, session_id=None):
        with self.lock:
            self._expire()
            current = self.state["session_id"]
            if session_id is not None and session_id != current:
                return 409, deepcopy(self.state)
        cards = [reference_card(page, "manual") for page in search(text, catalog=self.catalog)]
        with self.lock:
            self._expire()
            if current != self.state["session_id"]:
                return 409, deepcopy(self.state)
            self.manual_cards = cards
            self._rebuild_cards()
            if cards:
                self._renew_lease()
            self._refresh_inventory()
            self.state["version"] += 1
            return 200, deepcopy(self.state)

    def action(self, request):
        with self.lock:
            self._expire()
            session = self.state
            if (request.get("session_id") != session["session_id"]
                    or type(request.get("expected_action_version")) is not int
                    or request["expected_action_version"] != session["action_version"]):
                return 409, deepcopy(session)
            action, payload = request.get("action"), request.get("payload", {})
            if not isinstance(payload, dict):
                raise ValueError("I dati dell’azione non sono validi.")
            if action in ("reset", "termina"):
                self._replace()
                diagnostic("audio", "sessione_chiusa")
                return 200, deepcopy(self.state)
            if action == "fase":
                value = payload.get("value")
                if value not in PHASES or (value == "Consiglio confermato" and not session["product"]["confirmed_code"]):
                    raise ValueError("Seleziona una fase valida o conferma prima un prodotto.")
                self.manual_phase = phase(value, "manuale", "Fase impostata dal farmacista.")
                session["phase"] = self.manual_phase
            elif action == "destinatario":
                recipient = manual_recipient(payload)
                self.manual_recipient = recipient
                session["recipient"] = recipient
            elif action in ("seleziona_prodotto", "conferma_prodotto", "correggi_prodotto", "correggi_nome"):
                code = payload.get("code")
                if action == "correggi_nome":
                    results = session["desk_results"]
                    codes = set(self._desk_visible_skus(results))
                    codes.update(row["code"] for row in results["correction_options"])
                    if not self._active() or results["previous"] or not isinstance(code, str) or code not in codes:
                        raise ValueError("Seleziona un nome disponibile nella sessione corrente.")
                    self._product_action("correggi_prodotto", code)
                    boundary = self.discarded_transcript_units + utf16_length(session["transcript"]["testo"]) + 1
                    self.manual_name_correction = (code, boundary)
                    self.agent_epoch += 1
                    self.local_desk_phase = desk_phase("choose", source="manual", reason="Nome corretto dal farmacista.")
                    session["desk_phase"] = self.local_desk_phase
                else:
                    self.manual_name_correction = None
                    self._product_action(action, code)
                if self._active() and action in ("correggi_prodotto", "correggi_nome"):
                    row = self._desk_row(code, [], named=True) if code else None
                    session["desk_results"] = {**empty_desk_results(), "rows": [row] if row else [],
                                               "preferred_code": code if row else None}
                    if action == "correggi_nome":
                        session["desk_results"]["manual_corrected_code"] = code
            elif action == "servizio":
                kind, comune, day = service_fields(payload)
                self.manual_service = public_service(kind, comune, day, load_configuration(self.settings))
                session["service"] = self.manual_service
                self.manual_phase = phase("Servizio", "manuale", "Consultazione richiesta dal farmacista.",
                                          service_missing(self.manual_service))
                session["phase"] = self.manual_phase
            elif action == "scheda":
                card_id, locked = payload.get("id"), payload.get("locked")
                card = next((card for card in session["cards"] if card["id"] == card_id), None)
                if not card or type(locked) is not bool:
                    raise ValueError("Seleziona una scheda visibile.")
                if locked:
                    self.locked_cards[card_id] = {
                        **card, "locked": True, "state": "manual", "evidence_ids": [],
                        "reason": "Scheda bloccata dal farmacista.",
                    }
                else:
                    self.locked_cards.pop(card_id, None)
            elif action == "aggiungi_carrello":
                code = payload.get("code")
                visible = self._desk_visible_skus(session["desk_results"])
                if not isinstance(code, str) or code not in visible:
                    raise ValueError("Aggiungi soltanto uno SKU esatto visibile nel catalogo.")
                source = product_display(code, catalog=self.catalog)
                if not source:
                    raise ValueError("Il prodotto non è più disponibile nel catalogo.")
                package_label = visible[code][2].get("package_label")
                session["cart"] = cart_add_item(session["cart"], source, code, package_label=package_label)
            elif action == "rimuovi_carrello":
                code = payload.get("code")
                if not isinstance(code, str):
                    raise ValueError("Seleziona uno SKU del carrello.")
                session["cart"] = cart_remove_item(session["cart"], code)
            elif action == "applica_offerta":
                code, offer_code = payload.get("code"), payload.get("offer_code")
                if (not isinstance(code, str) or not isinstance(offer_code, str)
                        or self.local_desk_phase["key"] != "closing"
                        or session["desk_results"].get("phase") != "offer"):
                    raise ValueError("L’offerta è applicabile solo alla cassa e allo SKU esatto mostrato.")
                shown = next((row for row in session["desk_results"]["offers"]
                              if row.get("code") == code and (row.get("offer") or {}).get("codice") == offer_code), None)
                if not shown:
                    raise ValueError("L’offerta non è più visibile per questo SKU.")
                live = active_offers(date.today(), {"product_codes": {code}}, self.catalog)
                offer = next((row for row in live if row.get("codice") == offer_code), None)
                if not offer:
                    raise ValueError("L’offerta non è più valida o disponibile.")
                session["cart"] = cart_apply_offer(session["cart"], code, offer)
            else:
                raise ValueError("Azione non riconosciuta.")
            self._rebuild_cards()
            self._refresh_inventory()
            session["action_version"] += 1
            session["version"] += 1
            self._renew_lease()
            return 200, deepcopy(session)

    def _product_action(self, action, code):
        products, pages = reference_material(self.catalog)
        if (code is None and action != "correggi_prodotto") or (
                code is not None and (not isinstance(code, str) or code not in products)):
            raise ValueError("Seleziona un codice presente nel catalogo.")
        product = self.state["product"]
        preserve_cosmetic_removal = (
            action == "conferma_prodotto" and self.cosmetic_complement
            and code == product.get("current_code")
        )
        if action == "correggi_prodotto" or product["confirmed_code"] not in (None, code):
            self._clear_choice(suppress=True)
        self.manual_phase = None
        self.cosmetic_complement = preserve_cosmetic_removal
        self.complement_eligible = False
        product["selected_code"] = code
        product["current_code"] = code
        product["current_state"] = "proposed" if code else "none"
        if code:
            self.suppressed.discard(code)
            chosen = next(page for page in pages.values() if (page["catalogo"] or {}).get("codice") == code)
            self.manual_cards = [reference_card(chosen, "confirmed" if action == "conferma_prodotto" else "manual")]
        if action == "conferma_prodotto":
            product.update(confirmed_code=code, confirmed_by="farmacista")
            self.state["phase"] = phase("Consiglio confermato", "manuale", "Il farmacista ha confermato il prodotto.")
        elif code:
            self.state["phase"] = phase("Verifica prodotto", "manuale", "Prodotto selezionato dal farmacista.",
                                        ["Conferma del farmacista"])
        else:
            self.state["phase"] = phase("Domande", "manuale", "Il farmacista ha ritirato la scelta.",
                                        ["Prodotto da verificare"])

    def update_configuration(self, payload):
        with self.lock:
            config = save_configuration(payload, self.settings)
            if self.config is not None:
                self.config = config
                self.next_evaluation = 0
            current = self.state["service"]
            service = public_service(current["kind"], current["comune"], current["data"], config)
            if service != current:
                self.state["service"] = service
                if self.manual_service is not None:
                    self.manual_service = service
                self.state["version"] += 1
            return config

    def update_agent_settings(self, payload):
        with self.lock, SETTINGS_LOCK:
            current = _read_configuration(self.settings)
            agent = phase_agent.normalize_settings(current.get("agent", {}))
            agent_payload = {key: payload[key] for key in phase_agent.DEFAULT_SETTINGS if key in payload}
            config = phase_agent.normalize_settings({**agent, **agent_payload})
            speech_engine = payload.get("speech_engine", current.get("speech_engine", "vosk"))
            if speech_engine not in ("vosk", "whisper.cpp", "ibrido"):
                raise ValueError("Seleziona un motore di trascrizione valido.")
            if speech_engine == "whisper.cpp" and not WhisperServer.available():
                raise ValueError("Whisper.cpp non è disponibile; mantieni Vosk o installa il modello locale.")
            input_device = payload.get("input_device", current.get("input_device"))
            input_devices = _input_device_records() if input_device is not None else []
            if "input_device" not in payload and input_device is not None and not any(
                    device["id"] == input_device for device in input_devices):
                input_device = None
            if input_device is not None:
                if not isinstance(input_device, str) or not any(device["id"] == input_device for device in input_devices):
                    raise ValueError("Il microfono selezionato non è più disponibile. Scegli un ingresso presente o il predefinito.")
            value = payload.get("api_key", "")
            clear = payload.get("clear_api_key", False)
            if (not isinstance(value, str) or type(clear) is not bool or clear and value
                    or value and not phase_agent.validate_key(value)):
                raise ValueError("Chiave API non valida.")
            if clear and config["enabled"]:
                raise ValueError("Disabilita l’agente prima di rimuovere la chiave.")
            if config["enabled"] and not (value or phase_agent.read_key()):
                raise ValueError("Configura una chiave prima di abilitare l’agente.")
            if value or clear:
                phase_agent.write_key(value or None)
            _write_configuration(self.settings, {**normalize_configuration(current), "agent": config,
                                                 "speech_engine": speech_engine, "input_device": input_device})
            self.agent_config = config
            self.speech_engine = speech_engine
            self.input_device = input_device
            self.agent_epoch += 1
            self.agent_after_units = self._absolute_final_end()
            self.agent_words_sent = self.final_word_count
            self.agent_skip_next_final = self.state["transcript"]["partial"] is not None
            self.agent_result_stamp = None
            self.state["desk_phase"] = self.local_desk_phase
            self.state["version"] += 1
            return public_agent_settings(config, speech_engine, self.active_speech_engine, input_device)

    def settings_snapshot(self):
        with self.lock:
            return public_agent_settings(load_agent_settings(self.settings),
                                         load_speech_engine(self.settings), self.active_speech_engine,
                                         load_input_device(self.settings))

    def verify_agent_connection(self):
        config = load_agent_settings(self.settings)
        return phase_agent.verify(config["model"], phase_agent.read_key())

    def _run_analysis(self, session_id, stop):
        while not stop.wait(0.1):
            try:
                self.evaluate()
            except Exception:
                diagnostic("ricerca", "ricerca_non_disponibile", "errore")
                self.finish(session_id, "microfono_o_ricerca")
                return

    def _run_audio(self, session_id, stop):
        error = None
        try:
            with self.audio_lock:
                if stop.is_set():
                    return
                if self.speech_engine == "ibrido":
                    self._capture_audio_hybrid(session_id, stop)
                elif self.speech_engine == "whisper.cpp" and WhisperServer.available():
                    try:
                        self._capture_audio_whisper(session_id, stop)
                    except InputDeviceUnavailable:
                        raise
                    except Exception:
                        if stop.is_set():
                            return
                        diagnostic("audio", "motore_whisper_ripiego", "avviso")
                        if self.whisper_worker_stop is not None:
                            self.whisper_worker_stop.set()
                            self.whisper_worker_stop = None
                        if self.whisper_server is not None:
                            self.whisper_server.stop()
                            self.whisper_server = None
                        self._capture_audio(session_id, stop)
                else:
                    self._capture_audio(session_id, stop)
        except (ImportError, FileNotFoundError):
            error = "dipendenze_o_modello"
        except InputDeviceUnavailable:
            diagnostic("audio", "dispositivo_input_non_disponibile", "errore")
            error = "dispositivo_input_non_disponibile"
        except Exception:
            error = "microfono_o_ricerca"
        finally:
            if not stop.is_set():
                self.finish(session_id, error)

    def _capture_audio(self, session_id, stop):
        import sounddevice
        from vosk import KaldiRecognizer

        path = Path(os.environ.get("SALES_VOSK_MODEL", str(MODEL))).resolve()
        if not path.is_dir():
            raise FileNotFoundError
        model = load_model(path)
        if stop.is_set():
            return
        device_index, sample_rate = _audio_input_selection(self.input_device, sounddevice)
        rate = int(sample_rate)
        recognizer = KaldiRecognizer(model, rate)
        recognizer.SetMaxAlternatives(3)
        audio = Queue(maxsize=8)

        def capture(buffer, frames, timing, status):
            if stop.is_set():
                return
            try:
                audio.put_nowait(bytes(buffer))
            except Full:
                pass

        with sounddevice.RawInputStream(device=device_index, samplerate=rate, blocksize=max(1, rate // 5),
                                        channels=1, dtype="int16", callback=capture) as stream:
            with self.lock:
                if session_id != self.state["session_id"] or stop.is_set():
                    return
                self.state["status"]["microphone"] = "attivo"
                self.active_speech_engine = "vosk"
                self.state["version"] += 1
            diagnostic("audio", "attivo", duration=self.clock() - self.started_at)
            while not stop.is_set():
                try:
                    chunk = audio.get(timeout=0.1)
                except Empty:
                    if not stream.active:
                        raise RuntimeError
                    continue
                fragment, final, alternatives = recognize_with_options(recognizer, chunk)
                self.ingest(session_id, fragment, final=final, alternatives=alternatives)

    @staticmethod
    def _speech_product_codes(text, terms):
        if not text:
            return set()
        result = analyze(text, terms)
        return {code for item in result["evidence"]
                if item.get("kind") in {"spoken_match", "product_mention", "product_candidate"}
                for code in item.get("product_codes", [])}

    def _replace_latest_final(self, session_id, original, refined, alternatives=()):
        """Apply a catalog-supported hybrid refinement only while its turn is current."""
        original, refined = original.strip(), refined.strip()
        if not original or not refined or original.casefold() == refined.casefold():
            return False
        with self.lock:
            transcript = self.state["transcript"]
            finals = transcript["final_segments"]
            if (session_id != self.state["session_id"] or not self._active()
                    or transcript["partial"] is not None or not finals
                    or finals[-1]["text"] != original or self.last_voice is None
                    or self.clock() - self.last_voice >= self.config["pausa_secondi"]):
                return False
            finals.pop()
            self.final_word_count = max(0, self.final_word_count -
                                        len(re.findall(r"[^\W_]+(?:['’][^\W_]+)*", original)))
            transcript["testo"] = " ".join(item["text"] for item in finals)
            return self.ingest(session_id, refined, final=True, alternatives=alternatives)

    def _capture_audio_hybrid(self, session_id, stop):
        """Show Vosk partials immediately; ask Whisper once per final turn as a fallback."""
        import sounddevice
        from vosk import KaldiRecognizer

        path = Path(os.environ.get("SALES_VOSK_MODEL", str(MODEL))).resolve()
        if not path.is_dir():
            raise FileNotFoundError
        model = load_model(path)
        if stop.is_set():
            return
        device_index, sample_rate = _audio_input_selection(self.input_device, sounddevice)
        rate = int(sample_rate)
        recognizer = KaldiRecognizer(model, rate)
        recognizer.SetMaxAlternatives(3)
        audio = Queue(maxsize=8)
        jobs = Queue(maxsize=1)
        worker_stop = threading.Event()
        whisper_ready = threading.Event()
        whisper_busy = threading.Event()
        self.whisper_worker_stop = worker_stop

        def refine_turns():
            server = WhisperServer(ROOT)
            try:
                server.start()
                if worker_stop.is_set():
                    return
                with self.lock:
                    if session_id != self.state["session_id"] or stop.is_set():
                        return
                    self.whisper_server = server
                whisper_ready.set()
                while not worker_stop.is_set():
                    try:
                        pcm_bytes, vosk_text = jobs.get(timeout=0.1)
                    except Empty:
                        continue
                    try:
                        _, _, terms = self._catalog_material()
                        prompt = _catalog_speech_prompt(terms, vosk_text)
                        whisper_text = server.transcribe_wav(self._whisper_wav(pcm_bytes), prompt=prompt)
                        vosk_codes = self._speech_product_codes(vosk_text, terms)
                        whisper_codes = self._speech_product_codes(whisper_text, terms)
                        compatible = (not vosk_codes or (vosk_codes.intersection(whisper_codes)
                                                         and whisper_codes.issubset(vosk_codes)))
                        if whisper_codes and compatible:
                            self._replace_latest_final(session_id, vosk_text, whisper_text,
                                                      alternatives=(vosk_text,))
                    except WhisperError as failure:
                        if failure.code != "whisper_busy":
                            diagnostic("audio", "motore_whisper_ripiego", "avviso")
                    except Exception:
                        diagnostic("audio", "motore_whisper_ripiego", "avviso")
                    finally:
                        whisper_busy.clear()
                        jobs.task_done()
            except Exception:
                diagnostic("audio", "motore_whisper_ripiego", "avviso")
            finally:
                whisper_ready.clear()
                server.stop()
                with self.lock:
                    if self.whisper_server is server:
                        self.whisper_server = None

        worker = threading.Thread(target=refine_turns, daemon=True, name="sales-whisper-refine")
        worker.start()

        def capture(buffer, frames, timing, status):
            if stop.is_set():
                return
            try:
                audio.put_nowait(bytes(buffer))
            except Full:
                pass

        segment_pcm = bytearray()
        segment_started = False
        with sounddevice.RawInputStream(device=device_index, samplerate=rate, blocksize=max(1, rate // 5),
                                        channels=1, dtype="int16", callback=capture) as stream:
            with self.lock:
                if session_id != self.state["session_id"] or stop.is_set():
                    worker_stop.set()
                    return
                self.state["status"]["microphone"] = "attivo"
                self.active_speech_engine = "ibrido"
                self.state["version"] += 1
            diagnostic("audio", "attivo", duration=self.clock() - self.started_at)
            while not stop.is_set():
                try:
                    chunk = audio.get(timeout=0.1)
                except Empty:
                    if not stream.active:
                        raise RuntimeError
                    continue
                converted, energy = self._resample_whisper_audio(chunk, rate)
                if energy >= 220 or segment_started:
                    segment_pcm.extend(converted)
                    segment_started = True
                fragment, final, alternatives = recognize_with_options(recognizer, chunk)
                self.ingest(session_id, fragment, final=final, alternatives=alternatives)
                if final:
                    if fragment and whisper_ready.is_set() and segment_pcm and not whisper_busy.is_set():
                        _, _, terms = self._catalog_material()
                        vosk_codes = self._speech_product_codes(fragment, terms)
                        if len(vosk_codes) != 1:
                            whisper_busy.set()
                            try:
                                jobs.put_nowait((bytes(segment_pcm), fragment))
                            except Full:
                                whisper_busy.clear()
                    segment_pcm.clear()
                    segment_started = False

    @staticmethod
    def _whisper_wav(pcm):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(bytes(pcm))
        return buffer.getvalue()

    @staticmethod
    def _resample_whisper_audio(chunk, sample_rate):
        samples = array("h")
        samples.frombytes(chunk)
        energy = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) if samples else 0.0
        if sample_rate == 16000 or len(samples) < 2:
            return samples.tobytes(), energy
        target_size = max(1, round(len(samples) * 16000 / sample_rate))
        resampled = array("h")
        denominator = max(1, target_size - 1)
        for index in range(target_size):
            position = index * (len(samples) - 1) / denominator
            left = int(position)
            right = min(left + 1, len(samples) - 1)
            fraction = position - left
            value = round(samples[left] + (samples[right] - samples[left]) * fraction)
            resampled.append(max(-32768, min(32767, value)))
        return resampled.tobytes(), energy

    def _capture_audio_whisper(self, session_id, stop):
        server = WhisperServer(ROOT)
        with self.lock:
            if session_id != self.state["session_id"] or stop.is_set():
                return
            self.whisper_server = server
        try:
            if stop.is_set():
                return
            server.start()
            if stop.is_set():
                return
            self._capture_audio_whisper_stream(session_id, stop, server)
        finally:
            if self.whisper_worker_stop is not None:
                self.whisper_worker_stop.set()
                self.whisper_worker_stop = None
            server.stop()
            with self.lock:
                if self.whisper_server is server:
                    self.whisper_server = None

    def _capture_audio_whisper_stream(self, session_id, stop, server):
        import sounddevice

        device_index, sample_rate = _audio_input_selection(self.input_device, sounddevice)
        rate = int(sample_rate)
        if rate < 8000 or rate > 192000:
            raise WhisperError("whisper_sample_rate_non_valido")
        audio, jobs, completed = Queue(maxsize=32), Queue(maxsize=1), Queue(maxsize=1)
        worker_stop = threading.Event()
        self.whisper_worker_stop = worker_stop
        worker_state, worker_lock = {"busy": False}, threading.Lock()

        def transcribe():
            while not worker_stop.is_set():
                try:
                    pcm_bytes, final = jobs.get(timeout=0.1)
                except Empty:
                    continue
                error = None
                try:
                    text = server.transcribe_wav(self._whisper_wav(pcm_bytes))
                    self.ingest(session_id, text, final=final)
                except WhisperError as failure:
                    error = failure.code
                except Exception:
                    error = "whisper_richiesta_non_riuscita"
                finally:
                    with worker_lock:
                        worker_state["busy"] = False
                    try:
                        completed.put_nowait(error)
                    except Full:
                        pass
                    jobs.task_done()
                if error:
                    return

        worker = threading.Thread(target=transcribe, daemon=True)
        worker.start()

        def capture(buffer, frames, timing, status):
            if stop.is_set():
                return
            block = bytes(buffer)
            try:
                audio.put_nowait(block)
            except Full:
                try:
                    audio.get_nowait()
                    audio.put_nowait(block)
                except (Empty, Full):
                    pass

        pcm = bytearray()
        last_partial_size = 0
        silence_seconds = 0.0
        last_activity = self.clock()
        final_ready = started = False
        with sounddevice.RawInputStream(device=device_index, samplerate=rate, blocksize=max(1, rate // 10),
                                        channels=1, dtype="int16", callback=capture) as stream:
            with self.lock:
                if session_id != self.state["session_id"] or stop.is_set():
                    worker_stop.set()
                    return
                self.state["status"]["microphone"] = "attivo"
                self.active_speech_engine = "whisper.cpp"
                self.state["version"] += 1
            diagnostic("audio", "attivo", duration=self.clock() - self.started_at)
            while not stop.is_set():
                try:
                    audio_chunk = audio.get(timeout=0.1)
                except Empty:
                    if not stream.active:
                        raise RuntimeError
                    audio_chunk = None
                if audio_chunk is not None:
                    converted, energy = self._resample_whisper_audio(audio_chunk, rate)
                    block_seconds = len(converted) / 32000
                    if energy >= 220 or started:
                        pcm.extend(converted)
                        if energy >= 220:
                            started = True
                            silence_seconds = 0.0
                            final_ready = False
                            last_activity = self.clock()
                        else:
                            silence_seconds += block_seconds
                    if started and silence_seconds >= 0.9:
                        final_ready = True

                try:
                    failure = completed.get_nowait()
                except Empty:
                    failure = None
                if failure:
                    raise WhisperError(failure)
                with worker_lock:
                    busy = worker_state["busy"]
                if started and not busy and final_ready and pcm:
                    try:
                        jobs.put_nowait((bytes(pcm), True))
                    except Full:
                        pass
                    else:
                        with worker_lock:
                            worker_state["busy"] = True
                        pcm.clear()
                        last_partial_size = 0
                        silence_seconds = 0.0
                        started = False
                        final_ready = False
                elif started and not busy and len(pcm) >= 48000 and len(pcm) - last_partial_size >= 24000:
                    try:
                        jobs.put_nowait((bytes(pcm[-192000:]), False))
                    except Full:
                        pass
                    else:
                        with worker_lock:
                            worker_state["busy"] = True
                        last_partial_size = len(pcm)
                if started and self.clock() - last_activity > 30:
                    pcm.clear()
                    started = final_ready = False
                    silence_seconds = 0.0
                    last_partial_size = 0
        self.whisper_worker_stop = None


def manual_recipient(payload):
    kind, relation = payload.get("kind"), payload.get("relation")
    fields = payload.get("declared_fields", {})
    if kind not in ("sconosciuto", "sé", "se", "altra_persona") or not isinstance(fields, dict):
        raise ValueError("Destinatario non valido.")
    age = fields.get("age")
    if age is not None and (type(age) is not int or not 0 <= age <= 125):
        raise ValueError("Inserisci un’età dichiarata valida.")
    gender = fields.get("gender")
    if gender not in (None, "donna", "uomo", "femminile", "maschile", "altro"):
        raise ValueError("Seleziona un genere dichiarato valido.")
    if gender in ("femminile", "maschile"):
        gender = "donna" if gender == "femminile" else "uomo"
    if relation is not None and (not isinstance(relation, str) or relation not in RELATIONS):
        raise ValueError("Seleziona una relazione valida.")
    if kind == "sconosciuto":
        return {**unknown_recipient(), "source": "manuale"}
    return {"kind": "sé" if kind == "se" else kind, "relation": relation if kind == "altra_persona" else None,
            "declared_fields": {key: value for key, value in (("age", age), ("gender", gender)) if value is not None},
            "source": "manuale"}


def service_fields(payload):
    kind, comune, day = payload.get("kind"), payload.get("comune", ""), payload.get("data", "")
    if (not isinstance(kind, str) or kind not in SERVICES or not isinstance(comune, str)
            or not isinstance(day, str) or len(comune) > 100 or not re.fullmatch(r"[^\W\d_]*(?:[ '\u2019-][^\W\d_]*)*", comune.strip())):
        raise ValueError("Indica un servizio e un comune validi.")
    if day and date.fromisoformat(day).isoformat() != day:
        raise ValueError("Usa una data nel formato AAAA-MM-GG.")
    return kind, comune.strip(), day


def service_missing(service):
    if service["status"] != "missing":
        return []
    return [label for key, label in (("comune", "Comune"), ("data", "Data o momento")) if not service[key]]

class Desk(BaseHTTPRequestHandler):
    listening = Listening()
    files = {
        "/": ("index.html", "text/html"),
        "/desk.css": ("desk.css", "text/css"),
        "/desk.js": ("desk.js", "text/javascript"),
        "/diagnostica": ("diagnostica.html", "text/html"),
        "/diagnostica.js": ("diagnostica.js", "text/javascript"),
    }

    def log_message(self, *_):
        pass

    def send(self, data, mime="application/json", status=200):
        self.send_response(status)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(data)

    def json(self, value, status=200):
        self.send(json.dumps(value, ensure_ascii=False).encode("utf-8"), status=status)

    def allowed(self):
        return self.headers.get_all("Host") == [f"127.0.0.1:{PORT}"]

    def payload(self):
        size = int(self.headers.get("Content-Length", 0))
        if not size:
            return {}
        if self.headers.get_content_type() != "application/json" or not 0 < size <= 16384:
            raise ValueError("Corpo JSON non valido.")
        raw = self.rfile.read(size)
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Oggetto JSON richiesto.")
        # Reject unpaired Unicode surrogate escapes before they can enter session state.
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return payload

    def do_GET(self):
        if not self.allowed():
            return self.json({"errore": "Apri la pagina dall’indirizzo locale indicato."}, 403)
        try:
            if self.path in self.files:
                filename, mime = self.files[self.path]
                return self.send((ROOT / "frontend" / filename).read_bytes(), mime)
            if self.path == "/api/diagnostica":
                return self.json(self.diagnostics())
            if self.path == "/api/offerte":
                return self.json(offer_listing(self.listening.catalog))
            if self.path == "/api/configurazione":
                return self.json(load_configuration(self.listening.settings))
            if self.path == "/api/impostazioni":
                return self.json(self.listening.settings_snapshot())
            self.json({"errore": "Pagina assente."}, 404)
        except (OSError, ValueError, sqlite3.Error):
            diagnostic("backend", "operazione_non_disponibile", "errore")
            self.json({"errore": "Dati locali non disponibili."}, 503)

    def do_POST(self):
        if not self.allowed() or self.headers.get_all("Origin") != [ORIGIN]:
            return self.json({"errore": "Richiesta fuori dalla schermata locale."}, 403)
        started = time.monotonic()
        try:
            payload = self.payload()
            if self.path == "/api/inizia":
                return self.json(self.listening.start())
            if self.path == "/api/stato":
                return self.json(self.listening.snapshot(payload.get("session_id"), inventory=True))
            if self.path == "/api/azione":
                status, result = self.listening.action(payload)
                return self.json(result, status)
            if self.path == "/api/cerca":
                text = payload.get("testo")
                if not isinstance(text, str):
                    return self.json({"errore": "Inserisci un testo da cercare."}, 400)
                status, result = self.listening.manual_search(text, payload.get("session_id"))
                return self.json(result, status)
            if self.path == "/api/offerte":
                return self.json(save_offer(payload, self.listening.catalog))
            if self.path == "/api/configurazione":
                return self.json(self.listening.update_configuration(payload))
            if self.path == "/api/impostazioni":
                return self.json(self.listening.update_agent_settings(payload))
            if self.path == "/api/impostazioni/verifica":
                return self.json(self.listening.verify_agent_connection())
            if self.path.startswith("/api/errore-frontend/"):
                code = self.path.rsplit("/", 1)[-1]
                if code not in FRONTEND_CODES:
                    return self.json({"errore": "Codice non riconosciuto."}, 400)
                diagnostic("frontend", code, "errore")
                return self.json({"ok": True})
            self.json({"errore": "Azione assente."}, 404)
        except (ConnectionError, TimeoutError):
            return
        except ValueError:
            diagnostic("backend", "operazione_non_disponibile", "errore", time.monotonic() - started)
            self.json({"errore": "Controlla i campi inviati."}, 400)
        except (OSError, sqlite3.Error):
            diagnostic("backend", "operazione_non_disponibile", "errore", time.monotonic() - started)
            self.json({"errore": "Operazione non disponibile. Controlla i dati locali."}, 503)

    def diagnostics(self):
        model = Path(os.environ.get("SALES_VOSK_MODEL", str(MODEL)))
        catalog_present = self.listening.catalog.is_file()
        try:
            sources = load_configuration(self.listening.settings)["fonti"]
        except (ValueError, OSError):
            sources = {}
        with self.listening.lock:
            microphone = self.listening.state["status"]["microphone"]
        with EVENT_LOCK:
            events = list(EVENTS)
        return {
            "microfono": microphone, "modello_presente": model.is_dir(), "catalogo_presente": catalog_present,
            "backend": "attivo", "frontend": "presente" if (ROOT / "frontend" / "index.html").is_file() else "assente",
            "ricerca": "errore" if any(event["componente"] == "ricerca" for event in events) else
                       "disponibile" if catalog_present else "non_disponibile",
            "fonti": {kind: bool(sources.get(kind)) for kind in SERVICES}, "eventi": events,
        }


class LocalServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        diagnostic("backend", "operazione_non_disponibile", "errore")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Avvia il banco farmacia sul PC.")
    parser.add_argument("--open", action="store_true", help="Apri la schermata nel browser.")
    args = parser.parse_args()
    with LocalServer(("127.0.0.1", PORT), Desk) as server:
        print(f"Schermata farmacista: {ORIGIN}", flush=True)
        if args.open:
            threading.Thread(target=webbrowser.open, args=(ORIGIN,), daemon=True).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            Desk.listening.stop()
