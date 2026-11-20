"""Pagina /revisione: la coda di revisione del farmacista in una schermata.

Stesso flusso di `backend/revisione.py`, senza riga di comando. È l'unico punto da cui
si approva: relazioni bisogno–prodotto, complementi di banco, abbinamenti tra prodotti,
idoneità per popolazione e protocolli. Ogni decisione chiede il nome del farmacista e
finisce in `registro_revisioni`. Le avvertenze obbligatorie dello schema si compilano
nella pagina prima di approvare.
"""

import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path

from backend import protocolli

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "database" / "farmacia.sqlite3"
WIKI = ROOT / "wiki" / "schede"
KINDS = ("relazione", "complemento", "abbinamento", "popolazione", "protocollo")


def _connect(catalog):
    db = sqlite3.connect(Path(catalog))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def _has(db, table):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log(db, table, key, before, after, reviewer, note):
    db.execute("""INSERT INTO registro_revisioni (tabella, chiave, da_stato, a_stato, revisore, il, nota)
                  VALUES (?, ?, ?, ?, ?, ?, ?)""", (table, key, before, after, reviewer, _now(), (note or "")[:300]))


def _protocol_meta(path):
    text = path.read_text(encoding="utf-8")
    meta = dict(re.findall(r'^(\w+)\s*=\s*"([^"]*)"', text.split("+++")[1] if text.count("+++") >= 2 else "", re.M))
    return meta, text


def queue(catalog=CATALOG, wiki=WIKI, kind=None, concept=None, *, demand=None):
    """Everything waiting for the pharmacist, most useful first (needs seen at the desk first)."""
    items = []
    with closing(_connect(catalog)) as db:
        seen = demand if demand is not None else {
            row[0]: row[1] for row in db.execute("""SELECT concetto_id, count(*) FROM feedback_banco
                WHERE concetto_id IS NOT NULL GROUP BY concetto_id""")} if _has(db, "feedback_banco") else {}
        if kind in (None, "relazione"):
            for row in db.execute("""
                    SELECT r.concetto_id, c.nome AS concetto, r.prodotto_codice, p.nome AS prodotto, r.tipo, r.contesto,
                           r.benefici, r.rischi, r.prerequisiti, r.esclusioni, f.url, f.titolo
                    FROM relazioni_concetto_prodotto r JOIN concetti c ON c.id = r.concetto_id
                    JOIN prodotti p ON p.codice = r.prodotto_codice LEFT JOIN fonti f ON f.id = r.fonte_id
                    WHERE r.stato_revisione = 'candidata' AND (? IS NULL OR r.concetto_id = ?)""", (concept, concept)):
                items.append({"kind": "relazione", "key": f"{row['concetto_id']}|{row['prodotto_codice']}|{row['tipo']}",
                              "concept": row["concetto_id"], "concept_name": row["concetto"],
                              "title": f"{row['concetto']} → {row['prodotto']}", "detail": row["contesto"],
                              "fields": {"benefici": row["benefici"], "rischi": row["rischi"],
                                         "prerequisiti": row["prerequisiti"], "esclusioni": row["esclusioni"]},
                              "required": ["benefici", "rischi", "prerequisiti", "esclusioni"],
                              "source": {"url": row["url"], "title": row["titolo"]}})
        if kind in (None, "complemento") and _has(db, "complementi_banco"):
            for row in db.execute("""
                    SELECT b.*, c.nome AS concetto, p.nome AS prodotto FROM complementi_banco b
                    LEFT JOIN concetti c ON c.id = b.concetto_id LEFT JOIN prodotti p ON p.codice = b.prodotto_complemento
                    WHERE b.stato_revisione = 'candidata' AND (? IS NULL OR b.concetto_id = ?)
                    ORDER BY b.priorita""", (concept, concept)):
                items.append({"kind": "complemento", "key": str(row["id"]), "concept": row["concetto_id"],
                              "concept_name": row["concetto"] or row["prodotto_origine"],
                              "title": f"{row['concetto'] or row['prodotto_origine']} → "
                                       f"{row['prodotto'] or row['categoria_scaffale']}",
                              "detail": row["motivo"], "fields": {"esclusioni": row["esclusioni"]}, "required": [],
                              "source": None})
        if kind in (None, "abbinamento"):
            for row in db.execute("""
                    SELECT r.*, a.nome AS da, b.nome AS a, f.url, f.titolo FROM relazioni_prodotti r
                    JOIN prodotti a ON a.codice = r.origine JOIN prodotti b ON b.codice = r.destinazione
                    LEFT JOIN fonti f ON f.id = r.fonte_id
                    WHERE r.stato_revisione = 'candidata' AND r.tipo LIKE 'complemento%'"""):
                items.append({"kind": "abbinamento", "key": f"{row['origine']}|{row['destinazione']}|{row['tipo']}",
                              "concept": None, "concept_name": None, "title": f"{row['da']} + {row['a']}",
                              "detail": row["motivo"], "fields": {"esclusioni": row["esclusioni"]},
                              "required": ["esclusioni"], "source": {"url": row["url"], "title": row["titolo"]}})
        if kind in (None, "popolazione") and _has(db, "prodotto_popolazione"):
            for row in db.execute("""
                    SELECT pp.*, p.nome AS prodotto, f.url, f.titolo FROM prodotto_popolazione pp
                    JOIN prodotti p ON p.codice = pp.prodotto_codice LEFT JOIN fonti f ON f.id = pp.fonte_id
                    WHERE pp.stato_revisione = 'candidata' ORDER BY p.nome"""):
                items.append({"kind": "popolazione", "key": str(row["id"]), "concept": None, "concept_name": None,
                              "title": f"{row['prodotto']} · {row['popolazione']} · {row['esito']}",
                              "detail": row["nota"], "fields": {}, "required": [],
                              "source": {"url": row["url"], "title": row["titolo"]}})
    if kind in (None, "protocollo"):
        for path in sorted(Path(wiki).glob("protocollo-*.md")):
            meta, _ = _protocol_meta(path)
            if meta.get("stato") == "pubblicata" or (concept and meta.get("concetto") != concept):
                continue
            items.append({"kind": "protocollo", "key": path.name, "concept": meta.get("concetto"),
                          "concept_name": meta.get("titolo", path.stem), "title": meta.get("titolo", path.stem),
                          "detail": "Domande, segnali d'allarme, consigli e complementi: leggere la scheda prima di approvare.",
                          "fields": {}, "required": [], "source": {"url": None, "title": "wiki/schede/" + path.name}})
    for item in items:
        item["demand"] = seen.get(item["concept"], 0)
    order = {kind: index for index, kind in enumerate(("protocollo", "complemento", "relazione", "abbinamento", "popolazione"))}
    items.sort(key=lambda item: (-item["demand"], order[item["kind"]], item["title"].casefold()))
    return items


def decide(kind, key, decision, reviewer, catalog=CATALOG, wiki=WIKI, fields=None, note=""):
    """Approve or reject one item. Returns a short summary. Raises ValueError on missing data."""
    if kind not in KINDS or decision not in ("approva", "respingi"):
        raise ValueError("Decisione non valida.")
    if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 80:
        raise ValueError("Serve il nome del farmacista.")
    reviewer = reviewer.strip()
    fields = {key_: (value or "").strip() for key_, value in (fields or {}).items() if isinstance(value, str)}
    if decision == "respingi" and not (note or "").strip():
        raise ValueError("Per respingere scrivi il motivo.")
    state = "approvata" if decision == "approva" else "respinta"
    today = date.today().isoformat()
    if kind == "protocollo":
        return _decide_protocol(key, decision, reviewer, catalog, wiki, note)
    with closing(_connect(catalog)) as db, db:
        if kind == "relazione":
            concept, code, relation_type = (key.split("|") + ["", "", ""])[:3]
            row = db.execute("""SELECT * FROM relazioni_concetto_prodotto WHERE concetto_id=? AND prodotto_codice=?
                                AND tipo=? AND stato_revisione='candidata'""", (concept, code, relation_type)).fetchone()
            if not row:
                raise LookupError("Relazione non trovata o già decisa.")
            values = {name: fields.get(name) or row[name] or "" for name in
                      ("contesto", "benefici", "rischi", "prerequisiti", "esclusioni")}
            if decision == "approva" and (not row["fonte_id"] or any(not value for value in values.values())):
                raise ValueError("Per approvare servono fonte, contesto, benefici, rischi, prerequisiti ed esclusioni.")
            db.execute("""UPDATE relazioni_concetto_prodotto SET stato_revisione=?, revisore=?, revisionato_il=?,
                              contesto=?, benefici=?, rischi=?, prerequisiti=?, esclusioni=?
                          WHERE concetto_id=? AND prodotto_codice=? AND tipo=?""",
                       (state, reviewer, today, *values.values(), concept, code, relation_type))
            _log(db, "relazioni_concetto_prodotto", key, "candidata", state, reviewer, note or values["rischi"])
        elif kind == "complemento":
            row = db.execute("SELECT * FROM complementi_banco WHERE id=? AND stato_revisione='candidata'",
                             (int(key),)).fetchone()
            if not row:
                raise LookupError("Complemento non trovato o già deciso.")
            exclusions = fields.get("esclusioni", row["esclusioni"] or "")
            db.execute("""UPDATE complementi_banco SET stato_revisione=?, revisore=?, revisionato_il=?, esclusioni=?
                          WHERE id=?""", (state, reviewer, today, exclusions, row["id"]))
            _log(db, "complementi_banco", key, "candidata", state, reviewer, note)
        elif kind == "abbinamento":
            origin, target, relation_type = (key.split("|") + ["", "", ""])[:3]
            row = db.execute("""SELECT * FROM relazioni_prodotti WHERE origine=? AND destinazione=? AND tipo=?
                                AND stato_revisione='candidata'""", (origin, target, relation_type)).fetchone()
            if not row:
                raise LookupError("Abbinamento non trovato o già deciso.")
            exclusions = fields.get("esclusioni") or row["esclusioni"] or ""
            if decision == "approva" and (not row["fonte_id"] or not exclusions):
                raise ValueError("Per approvare servono fonte ed esclusioni.")
            if decision == "approva" and relation_type == "complemento_clinico":
                raise ValueError("I complementi clinici si approvano con backend/revisione.py (campi clinici completi).")
            db.execute("""UPDATE relazioni_prodotti SET stato_revisione=?, revisore=?, revisionato_il=?, esclusioni=?
                          WHERE origine=? AND destinazione=? AND tipo=?""",
                       (state, reviewer, today, exclusions, origin, target, relation_type))
            _log(db, "relazioni_prodotti", key, "candidata", state, reviewer, note)
        elif kind == "popolazione":
            row = db.execute("SELECT * FROM prodotto_popolazione WHERE id=? AND stato_revisione='candidata'",
                             (int(key),)).fetchone()
            if not row:
                raise LookupError("Riga non trovata o già decisa.")
            db.execute("UPDATE prodotto_popolazione SET stato_revisione=?, revisore=?, revisionato_il=? WHERE id=?",
                       (state, reviewer, today, row["id"]))
            _log(db, "prodotto_popolazione", key, "candidata", state, reviewer, note)
    return {"kind": kind, "key": key, "state": state}


def _decide_protocol(name, decision, reviewer, catalog, wiki, note):
    if not re.fullmatch(r"protocollo-[a-z0-9-]+\.md", name or ""):
        raise ValueError("Scheda protocollo non valida.")
    path = Path(wiki) / name
    if not path.is_file():
        raise LookupError("Scheda non trovata.")
    meta, text = _protocol_meta(path)
    if decision == "respingi":
        with closing(_connect(catalog)) as db, db:
            _log(db, "protocolli_banco", meta.get("concetto", name), "bozza", "respinta", reviewer, note)
        return {"kind": "protocollo", "key": name, "state": "respinta"}
    version = str(int(meta.get("versione") or 0) + 1) if (meta.get("versione") or "0").isdigit() else "1"
    updated = re.sub(r'^stato\s*=\s*"[^"]*"', 'stato = "pubblicata"', text, count=1, flags=re.M)
    updated = re.sub(r'^revisore\s*=\s*"[^"]*"', f'revisore = "{reviewer.replace(chr(34), "")}"', updated, count=1, flags=re.M)
    updated = re.sub(r'^versione\s*=\s*"[^"]*"', f'versione = "{version}"', updated, count=1, flags=re.M)
    path.write_text(updated, encoding="utf-8", newline="\n")
    try:
        result = protocolli.publish(path, catalog)
    except (ValueError, sqlite3.Error):
        path.write_text(text, encoding="utf-8", newline="\n")
        raise
    return {"kind": "protocollo", "key": name, "state": "pubblicata", **result}
