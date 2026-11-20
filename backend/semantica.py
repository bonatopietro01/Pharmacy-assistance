"""Ricerca semantica facoltativa: suggerisce un *concetto* quando il lessico tace.

Spenta di default. Si attiva in database/configurazione.json:

    "ricerca_semantica": {"attiva": true, "modello": "BAAI/bge-m3", "soglia": 0.55}

Richiede i pacchetti `sqlite-vec` e `sentence-transformers` (e il modello
scaricato una volta). L'indice vive in un file separato,
database/semantica.sqlite3, ricostruito con:

    python -m backend.semantica indicizza

Regole: il vettore propone solo un concetto del lessico, mai un prodotto, e solo
se il lessico non ha riconosciuto nulla. Il banco lo mostra come domanda
(«Intendeva: mal di gola?») che il farmacista conferma con un tocco. Se il
pacchetto o il modello mancano, tutto funziona come prima e la diagnostica lo
segnala.
"""

import argparse
import json
import sqlite3
import struct
import sys
from contextlib import closing
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "database" / "configurazione.json"
LEXICON = ROOT / "database" / "lessico-concetti.json"
INDEX = ROOT / "database" / "semantica.sqlite3"


def settings(path=CONFIG):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    raw = data.get("ricerca_semantica") or {}
    return {"attiva": bool(raw.get("attiva")), "modello": raw.get("modello") or "BAAI/bge-m3",
            "soglia": float(raw.get("soglia", 0.55))}


def _packages():
    try:
        import sqlite_vec  # noqa: F401
        import sentence_transformers  # noqa: F401
    except ImportError:
        return False
    return True


def semantic_status(path=CONFIG):
    if not settings(path)["attiva"]:
        return "spenta"
    return "attiva" if _packages() and INDEX.is_file() else "non_disponibile"


def concept_texts(path=LEXICON):
    """One short description per lexicon concept: name, colloquial phrases, roots."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    texts = {}
    for concept_id, entry in (data.get("concetti") or {}).items():
        if not isinstance(entry, dict):
            continue
        parts = [entry.get("nome") or concept_id.replace("-", " "), *entry.get("termini", [])]
        texts[concept_id] = "; ".join(dict.fromkeys(p for p in parts if p))
    return texts


@lru_cache(maxsize=1)
def _model(name):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(name)


def _vector(values):
    return struct.pack(f"{len(values)}f", *values)


def _open(index=INDEX):
    import sqlite_vec
    db = sqlite3.connect(index)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    return db


def build_index(index=INDEX, config=CONFIG, lexicon=LEXICON):
    conf = settings(config)
    if not _packages():
        raise RuntimeError("Installare sqlite-vec e sentence-transformers per la ricerca semantica.")
    texts = concept_texts(lexicon)
    vectors = _model(conf["modello"]).encode(list(texts.values()), normalize_embeddings=True)
    Path(index).unlink(missing_ok=True)
    with closing(_open(index)) as db, db:
        db.execute(f"CREATE VIRTUAL TABLE concetti USING vec0(embedding float[{len(vectors[0])}])")
        db.execute("CREATE TABLE nomi (rowid INTEGER PRIMARY KEY, concetto TEXT NOT NULL)")
        for rowid, (concept_id, vector) in enumerate(zip(texts, vectors), start=1):
            db.execute("INSERT INTO concetti(rowid, embedding) VALUES (?, ?)", (rowid, _vector(vector)))
            db.execute("INSERT INTO nomi VALUES (?, ?)", (rowid, concept_id))
    return {"concetti": len(texts), "indice": str(index)}


def suggest_concept(text, index=INDEX, config=CONFIG):
    """Return {"concept_id", "score"} or None. Never raises: off, missing or failing means None."""
    conf = settings(config)
    if not conf["attiva"] or not text or not text.strip() or not Path(index).is_file() or not _packages():
        return None
    try:
        vector = _model(conf["modello"]).encode([text], normalize_embeddings=True)[0]
        with closing(_open(index)) as db:
            row = db.execute("""SELECT n.concetto, c.distance FROM concetti c JOIN nomi n ON n.rowid = c.rowid
                                WHERE c.embedding MATCH ? AND k = 1 ORDER BY c.distance""",
                             (_vector(vector),)).fetchone()
    except Exception:  # optional feature: any failure falls back to the lexicon alone
        return None
    if not row:
        return None
    # vec0 returns L2 distance; for normalized vectors cosine similarity = 1 - d²/2.
    score = 1 - (row[1] ** 2) / 2
    return {"concept_id": row[0], "score": round(score, 3)} if score >= conf["soglia"] else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("comando", choices=("indicizza", "stato", "prova"))
    parser.add_argument("testo", nargs="?")
    args = parser.parse_args(argv)
    try:
        if args.comando == "indicizza":
            result = build_index()
        elif args.comando == "prova":
            result = suggest_concept(args.testo or "")
        else:
            result = {"stato": semantic_status(), **settings()}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
