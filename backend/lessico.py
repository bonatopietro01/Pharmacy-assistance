"""Strumenti per far crescere il lessico dai casi reali del banco.

Il feedback del banco è anonimo e non contiene testo: per questo i comandi
mostrano solo conteggi per concetto, e le storpiature del riconoscimento vocale
si registrano a mano, come alias candidati da approvare.

    python -m backend.lessico frasi-mancate [--giorni 30]
    python -m backend.lessico proponi-alias REAL-MED-001 "tachi pirina" [--tipo errore_asr]
"""

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "database" / "farmacia.sqlite3"


def missed_concepts(catalog=CATALOG, days=30, today=None):
    since = ((today or date.today()) - timedelta(days=days)).isoformat()
    with closing(sqlite3.connect(catalog)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='feedback_banco'").fetchone():
            return []
        rows = db.execute("""SELECT coalesce(concetto_id, '(nessun concetto)'), evento, count(*)
                             FROM feedback_banco
                             WHERE evento IN ('non_pertinente','errore_riconoscimento') AND creato_il >= ?
                             GROUP BY 1, 2 ORDER BY 3 DESC""", (since,)).fetchall()
    return [{"concetto": c, "evento": e, "volte": n} for c, e, n in rows]


def propose_alias(code, alias, kind="errore_asr", catalog=CATALOG):
    alias = " ".join(alias.split())
    if not alias or len(alias) > 80:
        raise ValueError("Alias vuoto o troppo lungo.")
    if kind not in ("errore_asr", "nome_uso_comune", "sinonimo"):
        raise ValueError("Tipo di alias non ammesso.")
    with closing(sqlite3.connect(catalog)) as db, db:
        db.execute("PRAGMA foreign_keys = ON")
        columns = {row[1] for row in db.execute("PRAGMA table_info(alias_prodotto)")}
        if "stato_revisione" not in columns:
            raise sqlite3.DatabaseError("Applicare migrate-latest prima di proporre alias.")
        if not db.execute("SELECT 1 FROM prodotti WHERE codice=?", (code,)).fetchone():
            raise ValueError(f"Prodotto assente: {code}.")
        db.execute("""INSERT OR IGNORE INTO alias_prodotto (prodotto_codice, alias, tipo, stato_revisione)
                      VALUES (?,?,?,'candidata')""", (code, alias, kind))
    return {"prodotto": code, "alias": alias, "tipo": kind, "stato": "candidata"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("comando", choices=("frasi-mancate", "proponi-alias"))
    parser.add_argument("argomenti", nargs="*")
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--giorni", type=int, default=30)
    parser.add_argument("--tipo", default="errore_asr")
    args = parser.parse_args(argv)
    try:
        if args.comando == "frasi-mancate":
            result = missed_concepts(args.catalog, args.giorni)
        else:
            if len(args.argomenti) != 2:
                parser.error("Uso: proponi-alias CODICE \"alias\"")
            result = propose_alias(args.argomenti[0], args.argomenti[1], args.tipo, args.catalog)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, sqlite3.Error) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
