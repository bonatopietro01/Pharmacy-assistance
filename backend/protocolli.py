"""Protocolli di banco: dalla scheda wiki al catalogo, e dal catalogo al banco.

Una scheda `wiki/schede/protocollo-<concetto>.md` con `tipo = "protocollo"` è la
forma che il farmacista legge e corregge. Quando è `pubblicata` (con revisore e
versione), questo modulo la carica nelle tabelle `protocolli_banco` e
`protocollo_voci` (migrazione 006); i complementi di banco della sezione 4
entrano in `complementi_banco` come `candidata`, da approvare a parte.

    python -m backend.protocolli anteprima wiki/schede/protocollo-raffreddore.md
    python -m backend.protocolli pubblica  wiki/schede/protocollo-raffreddore.md [--catalog copia.sqlite3]
    python -m backend.protocolli elenco
"""

import argparse
import json
import re
import sqlite3
import sys
import tomllib
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "database" / "farmacia.sqlite3"

_SECTION = re.compile(r"^##\s+(\d+)\.\s*(.+?)\s*$", re.MULTILINE)
_ITEM = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.+?)\s*$", re.MULTILINE)
_FILTER = re.compile(r"\*\(\s*filtro:\s*([^—\-)]+?)\s*(?:[—-].*?)?\)\*")
_NOTE = re.compile(r"\s*\*\((.+?)\)\*[\s.;,]*$")
_FILTER_KEYS = {
    "età": "eta", "eta": "eta", "copertura dei sintomi": "sintomi", "sintomi": "sintomi",
    "avvertenze dei decongestionanti e dei fans": "terapie_patologie", "avvertenze": "terapie_patologie",
    "terapie": "terapie_patologie", "gravidanza": "gravidanza", "durata e ripetizione": "durata", "durata": "durata",
}
_COMPLEMENT_TYPES = (("dispositivo", "dispositivo"), ("igiene", "supporto_igiene"), ("supporto", "supporto_igiene"),
                     ("integratore", "integratore"), ("formato", "formato_convenienza"), ("prevenzione", "prevenzione"))


def _clean(text):
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_protocol(path):
    """Return the structured content of a protocol page; raise ValueError if malformed."""
    raw = Path(path).read_text(encoding="utf-8")
    try:
        _, meta, body = raw.split("+++\n", 2)
        meta = tomllib.loads(meta)
    except ValueError as error:
        raise ValueError(f"Intestazione TOML assente o non valida in {path}.") from error
    if meta.get("tipo") != "protocollo" or not re.fullmatch(r"[a-z0-9-]+", meta.get("concetto") or ""):
        raise ValueError("La scheda deve avere tipo = \"protocollo\" e un concetto valido.")
    sections = {}
    marks = list(_SECTION.finditer(body))
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(body)
        sections[int(mark.group(1))] = body[mark.end():end]

    def items(number):
        return [line for line in _ITEM.findall(sections.get(number, "")) if line.strip()]

    voices = []
    for order, line in enumerate(items(1)):
        found = _FILTER.search(line)
        key = None
        if found:
            label = found.group(1).strip().casefold()
            key = next((value for name, value in _FILTER_KEYS.items() if label.startswith(name)), label[:40])
        voices.append({"tipo": "domanda", "ordine": order, "testo": _clean(_NOTE.sub("", line)), "filtro": key})
    for order, line in enumerate(items(2)):
        voices.append({"tipo": "red_flag", "ordine": order, "testo": _clean(line), "filtro": None})
    for order, line in enumerate(items(5)):
        voices.append({"tipo": "consiglio", "ordine": order, "testo": _clean(line), "filtro": None})
    follow = _clean(re.sub(r"^\s*>.*$", "", sections.get(6, ""), flags=re.MULTILINE))
    if follow:
        voices.append({"tipo": "follow_up", "ordine": 0, "testo": follow, "filtro": None})

    complements = []
    for order, line in enumerate(items(4)):
        note = _NOTE.search(line)
        label = _clean(_NOTE.sub("", line)).rstrip(".")
        kind = "supporto_igiene"
        if note:
            low = note.group(1).casefold()
            kind = next((value for word, value in _COMPLEMENT_TYPES if word in low), kind)
        complements.append({"categoria_scaffale": label, "tipo": kind, "priorita": 100 + order * 10,
                            "motivo": f"Complemento di banco del protocollo {meta['concetto']}"})
    if not any(voice["tipo"] == "domanda" for voice in voices):
        raise ValueError("Il protocollo deve contenere almeno una domanda di inquadramento.")
    return {"concetto": meta["concetto"], "titolo": meta.get("titolo", ""), "stato": meta.get("stato"),
            "revisore": (meta.get("revisore") or "").strip(), "versione": (meta.get("versione") or "").strip(),
            "scheda": Path(path).stem, "voci": voices, "complementi": complements}


def publish(path, catalog=CATALOG, *, now=None):
    """Load a `pubblicata` protocol into the catalog; drafts are refused."""
    protocol = parse_protocol(path)
    if protocol["stato"] != "pubblicata" or not protocol["revisore"] or not protocol["versione"]:
        raise ValueError("Si pubblica solo una scheda con stato = \"pubblicata\", revisore e versione.")
    stamp = (now or datetime.now(timezone.utc)).date().isoformat()
    with closing(sqlite3.connect(catalog)) as db, db:
        db.execute("PRAGMA foreign_keys = ON")
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='protocolli_banco'").fetchone():
            raise sqlite3.DatabaseError("Il catalogo non ha le tabelle dei protocolli: applicare migrate-latest.")
        if not db.execute("SELECT 1 FROM concetti WHERE id=?", (protocol["concetto"],)).fetchone():
            raise ValueError(f"Concetto assente dal catalogo: {protocol['concetto']}.")
        db.execute("""INSERT INTO protocolli_banco (concetto_id, versione, stato, scheda_wiki, revisore, revisionato_il)
                      VALUES (?,?,'approvato',?,?,?)
                      ON CONFLICT(concetto_id) DO UPDATE SET versione=excluded.versione, stato='approvato',
                          scheda_wiki=excluded.scheda_wiki, revisore=excluded.revisore,
                          revisionato_il=excluded.revisionato_il""",
                   (protocol["concetto"], protocol["versione"], protocol["scheda"], protocol["revisore"], stamp))
        db.execute("DELETE FROM protocollo_voci WHERE concetto_id=?", (protocol["concetto"],))
        db.executemany("""INSERT INTO protocollo_voci (concetto_id, ordine, tipo, testo, filtro)
                          VALUES (?,?,?,?,?)""",
                       [(protocol["concetto"], v["ordine"], v["tipo"], v["testo"], v["filtro"]) for v in protocol["voci"]])
        added = 0
        for item in protocol["complementi"]:
            exists = db.execute("""SELECT 1 FROM complementi_banco WHERE concetto_id=? AND categoria_scaffale=?""",
                                (protocol["concetto"], item["categoria_scaffale"])).fetchone()
            if not exists:
                db.execute("""INSERT INTO complementi_banco (concetto_id, categoria_scaffale, tipo, motivo, priorita)
                              VALUES (?,?,?,?,?)""",
                           (protocol["concetto"], item["categoria_scaffale"], item["tipo"], item["motivo"],
                            item["priorita"]))
                added += 1
        db.execute("""INSERT INTO registro_revisioni (tabella, chiave, da_stato, a_stato, revisore, il, nota)
                      VALUES ('protocolli_banco', ?, NULL, 'approvato', ?, ?, ?)""",
                   (protocol["concetto"], protocol["revisore"], stamp, f"versione {protocol['versione']}"))
    return {"concetto": protocol["concetto"], "voci": len(protocol["voci"]), "complementi_candidati_aggiunti": added}


def protocol_for(concept_ids, catalog=CATALOG):
    """Approved protocol content for the desk, grouped by concept. Empty when tables are missing."""
    result = {}
    ids = [cid for cid in dict.fromkeys(concept_ids) if cid]
    if not ids:
        return result
    try:
        db = sqlite3.connect(Path(catalog).resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        return result
    with closing(db):
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='protocolli_banco'").fetchone():
            return result
        marks = ",".join("?" for _ in ids)
        for row in db.execute(f"""
                SELECT p.concetto_id, p.versione, p.revisore, v.tipo, v.ordine, v.testo, v.filtro
                FROM protocolli_banco p JOIN protocollo_voci v ON v.concetto_id = p.concetto_id
                WHERE p.stato = 'approvato' AND p.concetto_id IN ({marks})
                ORDER BY p.concetto_id, v.tipo, v.ordine""", ids):
            entry = result.setdefault(row["concetto_id"], {
                "concept_id": row["concetto_id"], "version": row["versione"], "reviewer": row["revisore"],
                "questions": [], "red_flags": [], "advice": [], "follow_up": None})
            item = {"text": row["testo"], "filter": row["filtro"]}
            if row["tipo"] == "domanda":
                entry["questions"].append(item)
            elif row["tipo"] == "red_flag":
                entry["red_flags"].append(row["testo"])
            elif row["tipo"] == "consiglio":
                entry["advice"].append(row["testo"])
            else:
                entry["follow_up"] = row["testo"]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("comando", choices=("anteprima", "pubblica", "elenco"))
    parser.add_argument("scheda", nargs="?", type=Path)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    args = parser.parse_args(argv)
    try:
        if args.comando == "elenco":
            with closing(sqlite3.connect(args.catalog)) as db:
                rows = db.execute("SELECT concetto_id, versione, stato, revisore FROM protocolli_banco").fetchall()
            result = [dict(zip(("concetto", "versione", "stato", "revisore"), row)) for row in rows]
        elif not args.scheda:
            parser.error("Indicare la scheda del protocollo.")
        elif args.comando == "anteprima":
            result = parse_protocol(args.scheda)
        else:
            result = publish(args.scheda, args.catalog)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, sqlite3.Error) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
