"""Ricerca ibrida nella wiki: parole chiave (BM25) + significato (embedding locale).

- Le schede pubblicabili di wiki/schede (non le bozze, come la ricerca esistente)
  sono divise in sezioni ("chunk") sui titoli Markdown; ogni chunk porta il
  titolo della pagina e della sezione.
- I vettori sono calcolati da un modello locale e multilingue (predefinito
  `BAAI/bge-m3`, lo stesso di backend/semantica.py) e salvati in
  database/wiki_vettori.sqlite3. Si ricalcolano solo le pagine il cui hash
  del contenuto è cambiato.
- Le due classifiche (BM25 su SQLite FTS5 e similarità coseno) sono unite con
  Reciprocal Rank Fusion: le sigle esatte restano in testa, i concetti vicini
  ("costi" → "spese", "budget") entrano grazie al significato. I risultati
  trovati solo per significato sono al massimo 5 e marcati come tali.
- Se il pacchetto `sentence-transformers` o il modello mancano, la ricerca
  continua con le sole parole chiave (modo "parole").

Configurazione facoltativa in database/configurazione.json:

    "ricerca_wiki": {"modello": "BAAI/bge-m3", "semantica": true, "soglia": -1}

("soglia": similarità coseno minima per i risultati per significato; -1 = nessuna.)

Il modello si scarica una volta nella cache di Hugging Face
(%USERPROFILE%\\.cache\\huggingface\\hub, circa 2,3 GB) e poi funziona offline.

    python -m backend.wiki_search indicizza
    python -m backend.wiki_search cerca "naso chiuso"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import threading
from array import array
from contextlib import closing
from pathlib import Path

from backend import knowledge

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "database" / "configurazione.json"
INDEX = ROOT / "database" / "wiki_vettori.sqlite3"
DEFAULT_MODEL = "BAAI/bge-m3"
# Results found by meaning alone (no keyword hit) are kept only within the best few semantic
# ranks. A fixed similarity threshold does not work here: on this wiki a one-word query such
# as "costi" scores ~0.33 on its right section, about as much as unrelated text.
SEMANTIC_ONLY_MAX_RANK = 5
RRF_K = 60
CANDIDATES = 50
MAX_CHUNK_CHARS = 1200
EXCERPT_CHARS = 220
CHUNKING_VERSION = 2  # bump when chunk_page changes: every page is re-embedded

_LOCK = threading.Lock()
_INDEX_LOCK = threading.Lock()
_MODELS = {}
_HEADING = re.compile(r"^(#{1,4})\s+(.+?)\s*#*\s*$")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


# ---------- configuration ----------

def settings(path=CONFIG):
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8")).get("ricerca_wiki") or {}
    except (OSError, ValueError):
        raw = {}
    model = raw.get("modello") if isinstance(raw.get("modello"), str) and raw.get("modello") else DEFAULT_MODEL
    threshold = raw.get("soglia")
    if type(threshold) not in (int, float) or not -1 <= threshold <= 1:
        threshold = -1.0
    return {"modello": model, "semantica": raw.get("semantica", True) is not False, "soglia": float(threshold)}


# ---------- pages and chunks ----------

def load_pages(catalog=knowledge.CATALOG, wiki=knowledge.WIKI):
    """Searchable wiki pages (same visibility rules as knowledge.search), without catalog-only entries."""
    _, pages = knowledge.reference_material(catalog, wiki)
    return {key: {"titolo": page["titolo"], "testo": page.get("testo", ""), "termini": page.get("termini", [])}
            for key, page in pages.items() if not key.startswith("catalogo:") and page.get("testo")}


def page_hash(page, model):
    payload = json.dumps([CHUNKING_VERSION, model, page["titolo"], page.get("termini", []), page["testo"]], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _split_long(text, limit=MAX_CHUNK_CHARS):
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for paragraph in re.split(r"\n\s*\n", text):
        while len(paragraph) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(paragraph[:limit])
            paragraph = paragraph[limit:]
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) > limit and current:
            parts.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def chunk_page(slug, page):
    """Split a page on Markdown headings. Each chunk: {slug, titolo, sezione, testo}."""
    title = page["titolo"]
    sections, heading, lines = [], "", []
    for line in _COMMENT.sub("", page["testo"]).splitlines():
        match = _HEADING.match(line)
        if match:
            if "\n".join(lines).strip():
                sections.append((heading, "\n".join(lines).strip()))
            heading = match.group(2).strip()
            if heading.casefold() == title.casefold():
                heading = ""
            lines = []
        else:
            lines.append(line)
    if "\n".join(lines).strip():
        sections.append((heading, "\n".join(lines).strip()))
    chunks = []
    for heading, body in sections:
        for part in _split_long(body):
            chunks.append({"slug": slug, "titolo": title, "sezione": heading, "testo": part})
    if not chunks:
        chunks.append({"slug": slug, "titolo": title, "sezione": "", "testo": title})
    return chunks


def _chunk_document(chunk, terms=()):
    head = chunk["titolo"] + (f" — {chunk['sezione']}" if chunk["sezione"] else "")
    extra = f"\n{', '.join(terms)}" if terms else ""
    return f"{head}{extra}\n{chunk['testo']}"


# ---------- embeddings ----------

def local_model_path(name):
    """Cached snapshot folder (no network at all), or the name itself for the first download."""
    if Path(name).is_dir():
        return name
    try:
        from huggingface_hub import snapshot_download
        return snapshot_download(name, local_files_only=True)
    except Exception:
        return name


class Embedder:
    """sentence-transformers wrapper; adds the e5 'query:'/'passage:' prefixes when needed."""

    def __init__(self, name):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(local_model_path(name), device="cpu")
        self.e5 = "e5" in name.casefold()

    def encode(self, texts, query=False):
        if self.e5:
            texts = [("query: " if query else "passage: ") + text for text in texts]
        vectors = self.model.encode(list(texts), normalize_embeddings=True, batch_size=16)
        return [[float(value) for value in vector] for vector in vectors]


def embedder_for(name):
    with _LOCK:
        if name not in _MODELS:
            _MODELS[name] = Embedder(name)
        return _MODELS[name]


def semantic_available():
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return False
    return True


def _pack(vector):
    return array("f", vector).tobytes()


def _unpack(blob):
    values = array("f")
    values.frombytes(blob)
    return values


# ---------- vector index ----------

def _open_index(path):
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS pagine (slug TEXT PRIMARY KEY, hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sezioni (
            id INTEGER PRIMARY KEY, slug TEXT NOT NULL, titolo TEXT NOT NULL, sezione TEXT NOT NULL,
            testo TEXT NOT NULL, vettore BLOB NOT NULL);
        CREATE INDEX IF NOT EXISTS sezioni_slug ON sezioni(slug);
        CREATE TABLE IF NOT EXISTS meta (chiave TEXT PRIMARY KEY, valore TEXT NOT NULL);
    """)
    return db


def update_index(pages, embedder, model_name, index=INDEX):
    """Embed only new or changed pages; drop removed ones. Returns counts."""
    with closing(_open_index(index)) as db, db:
        stored_model = db.execute("SELECT valore FROM meta WHERE chiave = 'modello'").fetchone()
        if stored_model and stored_model[0] != model_name:
            db.execute("DELETE FROM sezioni")
            db.execute("DELETE FROM pagine")
        db.execute("INSERT OR REPLACE INTO meta VALUES ('modello', ?)", (model_name,))
        known = dict(db.execute("SELECT slug, hash FROM pagine"))
        changed = {slug: page for slug, page in pages.items() if known.get(slug) != page_hash(page, model_name)}
        removed = set(known) - set(pages)
        for slug in removed | set(changed):
            db.execute("DELETE FROM sezioni WHERE slug = ?", (slug,))
            db.execute("DELETE FROM pagine WHERE slug = ?", (slug,))
        chunks = [(chunk, page.get("termini", [])) for slug, page in changed.items()
                  for chunk in chunk_page(slug, page)]
        if chunks:
            vectors = embedder.encode([_chunk_document(chunk, terms) for chunk, terms in chunks])
            db.executemany("INSERT INTO sezioni (slug, titolo, sezione, testo, vettore) VALUES (?, ?, ?, ?, ?)",
                           [(c["slug"], c["titolo"], c["sezione"], c["testo"], _pack(v))
                            for (c, _), v in zip(chunks, vectors)])
        db.executemany("INSERT INTO pagine VALUES (?, ?)",
                       [(slug, page_hash(page, model_name)) for slug, page in changed.items()])
        total = db.execute("SELECT count(*) FROM sezioni").fetchone()[0]
    return {"pagine_ricalcolate": len(changed), "pagine_rimosse": len(removed), "sezioni": total}


def _semantic_ranking(query, embedder, index, threshold=-1.0):
    vector = embedder.encode([query], query=True)[0]
    with closing(_open_index(index)) as db:
        rows = db.execute("SELECT id, slug, titolo, sezione, testo, vettore FROM sezioni").fetchall()
    scored = []
    for row_id, slug, title, section, text, blob in rows:
        stored = _unpack(blob)
        score = sum(a * b for a, b in zip(vector, stored))
        if score >= threshold:
            scored.append((score, {"slug": slug, "titolo": title, "sezione": section, "testo": text, "id": row_id}))
    scored.sort(key=lambda item: -item[0])
    return [(chunk, score) for score, chunk in scored[:CANDIDATES]]


# ---------- keyword ranking ----------

def _keyword_ranking(query, pages):
    phrase = knowledge.normalize(query)
    terms = knowledge._query_terms(phrase) if phrase else []
    if not terms:
        return []
    chunks = [chunk for slug, page in pages.items() for chunk in chunk_page(slug, page)]
    with closing(sqlite3.connect(":memory:")) as db:
        db.execute("CREATE VIRTUAL TABLE f USING fts5(n UNINDEXED, titolo, termini, testo, "
                   "tokenize='unicode61 remove_diacritics 2')")
        db.executemany("INSERT INTO f VALUES (?, ?, ?, ?)", [
            (number, f"{chunk['titolo']} {chunk['sezione']}",
             " ".join(pages[chunk["slug"]].get("termini", [])), chunk["testo"])
            for number, chunk in enumerate(chunks)])
        rows = db.execute("SELECT n, bm25(f, 0, 4, 3, 1) FROM f WHERE f MATCH ? ORDER BY 2 LIMIT ?",
                          (" OR ".join(terms), CANDIDATES)).fetchall()
    return [(chunks[number], -rank) for number, rank in rows]


# ---------- fusion ----------

def _chunk_key(chunk):
    return (chunk["slug"], chunk["sezione"], chunk["testo"][:80])


def reciprocal_rank_fusion(*rankings, k=RRF_K):
    """rankings: lists of (chunk, score) best first. Returns [(chunk, rrf, {ranking_index: rank})]."""
    scores, chunks, ranks = {}, {}, {}
    for which, ranking in enumerate(rankings):
        for rank, (chunk, _) in enumerate(ranking, start=1):
            key = _chunk_key(chunk)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            chunks.setdefault(key, chunk)
            ranks.setdefault(key, {})[which] = rank
    ordered = sorted(scores, key=lambda key: -scores[key])
    return [(chunks[key], scores[key], ranks[key]) for key in ordered]


def excerpt(text, query, size=EXCERPT_CHARS):
    plain = re.sub(r"\s+", " ", re.sub(r"[#*_`>|\[\]]", " ", text)).strip()
    folded = knowledge.normalize(plain)
    position = -1
    for word in knowledge.normalize(query).split():
        if len(word) >= 3:
            stem = word[:-1] if len(word) >= 6 else word
            position = folded.find(stem)
            if position >= 0:
                break
    if position < 0 or len(folded) != len(plain):
        position = 0
    start = max(0, position - size // 3)
    piece = plain[start:start + size].strip()
    return ("…" if start else "") + piece + ("…" if start + size < len(plain) else "")


def hybrid_search(query, pages, embedder=None, model_name=DEFAULT_MODEL, index=INDEX, limit=10, threshold=-1.0):
    """Return one result per page: {scheda, titolo, sezione, estratto, punteggio, fonti}."""
    if not isinstance(query, str) or len(query) > 4096:
        raise ValueError("Usa un testo di ricerca fino a 4096 caratteri.")
    if not query.strip():
        return {"modo": "parole", "risultati": []}
    keyword = _keyword_ranking(query, pages)
    semantic = []
    mode = "parole"
    if embedder is not None:
        with _INDEX_LOCK:
            update_index(pages, embedder, model_name, index)
            semantic = _semantic_ranking(query, embedder, index, threshold)
        mode = "ibrida"
    fused = reciprocal_rank_fusion(keyword, semantic)
    results, seen = [], set()
    for chunk, score, ranks in fused:
        if chunk["slug"] in seen:
            continue
        if 0 not in ranks and ranks.get(1, CANDIDATES + 1) > SEMANTIC_ONLY_MAX_RANK:
            continue
        seen.add(chunk["slug"])
        results.append({
            "scheda": chunk["slug"], "titolo": chunk["titolo"], "sezione": chunk["sezione"],
            "estratto": excerpt(chunk["testo"], query), "punteggio": round(score, 5),
            "fonti": [name for which, name in ((0, "parole"), (1, "significato")) if which in ranks],
        })
        if len(results) >= limit:
            break
    return {"modo": mode, "risultati": results}


def search(query, catalog=knowledge.CATALOG, wiki=knowledge.WIKI, config=CONFIG, index=INDEX):
    """Hybrid search on the real wiki; falls back to keywords when the model is unavailable."""
    conf = settings(config)
    pages = load_pages(catalog, wiki)
    embedder = None
    if conf["semantica"] and semantic_available():
        try:
            embedder = embedder_for(conf["modello"])
        except Exception:  # model not downloaded and no network: keywords only
            embedder = None
    try:
        return hybrid_search(query, pages, embedder, conf["modello"], index, threshold=conf["soglia"])
    except (sqlite3.Error, OSError, RuntimeError):
        if embedder is None:
            raise
        return hybrid_search(query, pages, None, conf["modello"], index)


def warm_up(config=CONFIG):
    """Load the embedding model in the background so the first search is not slow."""
    conf = settings(config)
    if conf["semantica"] and semantic_available():
        try:
            embedder_for(conf["modello"])
        except Exception:
            pass


def build(catalog=knowledge.CATALOG, wiki=knowledge.WIKI, config=CONFIG, index=INDEX):
    conf = settings(config)
    if not semantic_available():
        raise RuntimeError("Installare sentence-transformers (requirements.txt) per la ricerca per significato.")
    return {"modello": conf["modello"], "indice": str(index),
            **update_index(load_pages(catalog, wiki), embedder_for(conf["modello"]), conf["modello"], index)}


# ---------- vocabulary for speech recognition ----------

_TITLE_PREFIX = re.compile(r"^(protocollo|scheda|caso)\s*[·:-]\s*", re.IGNORECASE)
_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{1,7}\b")
_ACRONYM_STOP = {"OK", "NB", "DM", "SPF", "UTC", "PDF", "PNG", "URL", "REAL", "SUP", "MED", "VET", "DEMO", "OTC", "COS"}


def wiki_vocabulary(pages, limit=600):
    """Page titles, declared terms and acronyms from the wiki, as a comma-separated prompt."""
    words = {}
    for page in pages.values():
        title = _TITLE_PREFIX.sub("", page["titolo"]).strip()
        short_title = (title,) if len(title.split()) <= 3 else ()  # skip long product names
        for item in (*short_title, *page.get("termini", [])):
            item = str(item).strip()
            if 3 <= len(item) <= 40:
                words.setdefault(item.casefold(), item)
        for acronym in _ACRONYM.findall(page.get("testo", "")):
            if acronym not in _ACRONYM_STOP:
                words.setdefault(acronym.casefold(), acronym)
    text = ""
    for item in sorted(words.values(), key=str.casefold):
        candidate = f"{text}, {item}" if text else item
        if len(candidate) > limit:
            break
        text = candidate
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("comando", choices=("indicizza", "cerca", "stato"))
    parser.add_argument("testo", nargs="?", default="")
    args = parser.parse_args(argv)
    try:
        if args.comando == "indicizza":
            result = build()
        elif args.comando == "cerca":
            result = search(args.testo)
        else:
            result = {**settings(), "pacchetti": semantic_available(), "indice_presente": INDEX.is_file()}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
