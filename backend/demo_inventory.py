"""Seed a labelled, synthetic inventory without overwriting pharmacy values."""

import argparse
import json
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from zlib import crc32

from backend.knowledge import CATALOG, ROOT, catalog_connection


SOURCE = "SRC-SALES-DEMOBANCO-20261108"
SCENARIO = ROOT / "database" / "scenario-banco-demo.json"


def apply_demo(catalog, scenario, today):
    data = json.loads(scenario.read_text(encoding="utf-8"))
    overrides = data["stock_overrides"]
    with closing(catalog_connection(catalog, writable=True)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""
            INSERT INTO fonti (id,titolo,ente,consultata_il,data_o_versione,tipo)
            VALUES (?, 'Dati di prova · listino e scorte simulati', 'Sales Agents', ?, 'Scenario banco v1', 'demo')
            ON CONFLICT(id) DO NOTHING
        """, (SOURCE, today.isoformat()))
        source = db.execute("SELECT tipo FROM fonti WHERE id=?", (SOURCE,)).fetchone()
        if not source or source["tipo"] != "demo":
            raise ValueError("Il codice della fonte è già utilizzato per dati non dimostrativi.")

        prices = {}
        stocks = {}
        products = db.execute("""
            SELECT codice,prezzo_cent,prezzo_banco_fonte_id,quantita,quantita_fonte_id
            FROM prodotti WHERE dataset_tipo='reale' ORDER BY codice
        """).fetchall()
        for row in products:
            code = row["codice"]
            seed = crc32(code.encode("utf-8"))
            demo_price = 450 + (seed % 111) * 10
            demo_stock = overrides.get(code, 4 + seed % 13)
            for value_field, source_field, date_field, claim, value, recorded in (
                ("prezzo_cent", "prezzo_banco_fonte_id", "prezzo_banco_data", "prezzo_banco", demo_price, prices),
                ("quantita", "quantita_fonte_id", "quantita_data", "scorte", demo_stock, stocks),
            ):
                if row[source_field] != SOURCE and (row[value_field] is not None or row[source_field] is not None):
                    continue
                db.execute(f"""
                    UPDATE prodotti SET {value_field}=?, {source_field}=?, {date_field}=? WHERE codice=?
                """, (value, SOURCE, today.isoformat(), code))
                db.execute("""
                    INSERT INTO prodotto_fonti VALUES (?, ?, ?, 'demo')
                    ON CONFLICT(prodotto_codice,fonte_id,affermazione) DO NOTHING
                """, (code, SOURCE, claim))
                recorded[code] = value
        offer_count = 0
        for offer in data["offers"]:
            code, sku = offer["code"], offer["sku"]
            if sku not in prices or sku not in stocks:
                continue
            existing = db.execute("SELECT stato,criterio FROM offerte WHERE codice=?", (code,)).fetchone()
            criterion = "Scenario banco dimostrativo v1"
            if existing and (existing["stato"] != "demo" or existing["criterio"] != criterion):
                continue
            start = (today + timedelta(days=offer["starts"])).isoformat()
            end = (today + timedelta(days=offer["ends"])).isoformat()
            price = max(0, prices[sku] - offer["discount_cents"])
            db.execute("""
                INSERT INTO offerte (codice,prodotto_codice,titolo,criterio,prezzo_cent,inizio,fine,
                    stato,beneficio,disponibilita,criterio_tipo,budget_cent)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'demo', 'Riduzione di prezzo simulata', ?, 'prodotto', NULL)
                ON CONFLICT(codice) DO UPDATE SET prodotto_codice=excluded.prodotto_codice,
                    titolo=excluded.titolo,prezzo_cent=excluded.prezzo_cent,inizio=excluded.inizio,
                    fine=excluded.fine,disponibilita=excluded.disponibilita
            """, (code, sku, offer["title"], criterion, price, start, end, offer["quantity"]))
            offer_count += 1
        return {"prezzi_demo": len(prices), "scorte_demo": len(stocks), "offerte_demo": offer_count}


def demo_wiki(catalog, today):
    lines = [
        "# Listino e scorte di prova", "",
        f"Generato dal catalogo SQLite il {today.isoformat()}. I valori sono sintetici per confezione.",
        "Il trattino indica un dato assente o estraneo allo scenario.", "",
        "| Codice | Prodotto | Prezzo demo | Scorte demo |", "|---|---|---:|---:|",
    ]
    with closing(catalog_connection(catalog)) as db:
        rows = db.execute("""
            SELECT codice,nome,prezzo_cent,quantita,prezzo_banco_fonte_id,quantita_fonte_id
            FROM prodotti WHERE prezzo_banco_fonte_id=? OR quantita_fonte_id=?
            ORDER BY nome COLLATE NOCASE,codice
        """, (SOURCE, SOURCE)).fetchall()
    for row in rows:
        name = row["nome"].replace("|", r"\|").replace("\n", " ")
        price = f'{row["prezzo_cent"] / 100:.2f} €'.replace(".", ",") if row["prezzo_banco_fonte_id"] == SOURCE else "—"
        stock = str(row["quantita"]) if row["quantita_fonte_id"] == SOURCE else "—"
        lines.append(f'| `{row["codice"]}` | {name} | {price} | {stock} |')
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--scenario", type=Path, default=SCENARIO)
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--wiki", type=Path)
    args = parser.parse_args()
    print(json.dumps(apply_demo(args.catalog, args.scenario, args.date)))
    if args.wiki:
        args.wiki.write_text(demo_wiki(args.catalog, args.date), encoding="utf-8")
