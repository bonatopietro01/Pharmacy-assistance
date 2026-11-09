"""Validate and match promotions in the local demonstration catalog."""

import re
import sqlite3
from contextlib import closing
from datetime import date

from backend.knowledge import CATALOG, catalog_connection

FIELDS = (
    "codice", "prodotto_codice", "titolo", "criterio", "prezzo_cent", "inizio", "fine",
    "stato", "beneficio", "disponibilita", "criterio_tipo", "budget_cent",
)


def offer_listing(catalog=CATALOG):
    with closing(catalog_connection(catalog)) as db:
        rows = db.execute("SELECT * FROM offerte ORDER BY codice").fetchall()
        products = db.execute("SELECT codice, nome, categoria FROM prodotti ORDER BY nome").fetchall()
    return {
        "offerte": [dict(row) for row in rows],
        "prodotti": [dict(row) for row in products],
        "data": date.today().isoformat(),
    }


def active_offers(today, explicit_interests, catalog=CATALOG):
    codes = set(explicit_interests["product_codes"])
    if not codes:
        return []
    budgets = explicit_interests.get("budgets_by_code")
    if budgets is None:
        budget = explicit_interests.get("budget_cent")
        budgets = {code: budget for code in codes} if len(codes) == 1 and budget is not None else {}
    with closing(catalog_connection(catalog)) as db:
        rows = db.execute("""
            SELECT o.*, p.nome AS prodotto_nome, p.categoria
            FROM offerte o JOIN prodotti p ON p.codice = o.prodotto_codice
            WHERE o.stato IN ('attiva','demo') AND ? BETWEEN o.inizio AND o.fine
              AND o.disponibilita > 0 AND p.quantita > 0
            ORDER BY o.codice
        """, (today.isoformat(),))
        return [
            {**dict(row), "dimostrativa": True} for row in rows
            if row["prodotto_codice"] in codes
            and (row["criterio_tipo"] != "cosmetico" or row["categoria"] == "Cosmetico")
            and (row["criterio_tipo"] != "budget" or (
                row["prodotto_codice"] in budgets
                and row["prezzo_cent"] <= min(budgets[row["prodotto_codice"]], row["budget_cent"])
            ))
        ]


def save_offer(payload, catalog=CATALOG):
    row = {field: payload.get(field) for field in FIELDS}
    for field, limit in (("codice", 50), ("prodotto_codice", 50), ("titolo", 120), ("criterio", 200), ("beneficio", 200)):
        value = row[field] if row[field] is not None or field != "beneficio" else ""
        if not isinstance(value, str) or len(value) > limit or (not value.strip() and field != "beneficio"):
            raise ValueError("Campi dell’offerta incompleti o non validi.")
        row[field] = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", row["codice"]):
        raise ValueError("Il codice offerta può contenere lettere, cifre, trattini e underscore.")
    for field in ("prezzo_cent", "disponibilita", "budget_cent"):
        value = row[field]
        if value is None and field != "disponibilita":
            continue
        if type(value) is not int or not 0 <= value <= 10_000_000:
            raise ValueError("Prezzo, budget e disponibilità richiedono numeri interi non negativi.")
    if row["prezzo_cent"] is None and not row["beneficio"]:
        raise ValueError("Inserisci prezzo o beneficio.")
    if row["stato"] not in ("demo", "bozza", "attiva") or row["criterio_tipo"] not in ("prodotto", "cosmetico", "budget"):
        raise ValueError("Stato o criterio commerciale non valido.")
    if row["criterio_tipo"] == "budget" and (row["budget_cent"] is None or row["prezzo_cent"] is None):
        raise ValueError("Il criterio budget richiede un prezzo e un limite in centesimi.")
    if row["criterio_tipo"] != "budget":
        row["budget_cent"] = None
    for field in ("inizio", "fine"):
        if row[field] in ("", None):
            row[field] = None
            continue
        if not isinstance(row[field], str) or date.fromisoformat(row[field]).isoformat() != row[field]:
            raise ValueError("Usa date nel formato AAAA-MM-GG.")
    start, end = row["inizio"], row["fine"]
    if (row["stato"] == "attiva" and not (start and end)) or (start and end and start > end):
        raise ValueError("Indica un periodo valido per l’offerta.")
    with closing(catalog_connection(catalog, writable=True)) as db, db:
        product = db.execute("SELECT categoria FROM prodotti WHERE codice = ?", (row["prodotto_codice"],)).fetchone()
        if not product:
            raise ValueError("Seleziona un prodotto presente nel catalogo.")
        if row["criterio_tipo"] == "cosmetico" and product["categoria"] != "Cosmetico":
            raise ValueError("Il criterio cosmetico richiede un prodotto cosmetico.")
        names = ", ".join(FIELDS)
        placeholders = ", ".join(f":{field}" for field in FIELDS)
        changes = ", ".join(f"{field} = excluded.{field}" for field in FIELDS[1:])
        db.execute(f"INSERT INTO offerte ({names}) VALUES ({placeholders}) ON CONFLICT(codice) DO UPDATE SET {changes}", row)
    return offer_listing(catalog)
