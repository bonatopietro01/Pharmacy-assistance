"""Import notturni: anagrafica AIFA, farmaci carenti, prezzi e giacenze del gestionale.

Regole comuni:
- si lavora prima su una copia (`--catalog copia.sqlite3`), poi sull'operativo;
- un campo già revisionato dal farmacista non viene mai sovrascritto;
- ogni esecuzione scrive un riepilogo in `registro_import` (migrazione 007),
  letto dalla pagina di diagnostica.

    python -m backend.import_dati aifa --cartella dati/aifa [--scarica]
    python -m backend.import_dati gestionale export.csv
    python -m backend.import_dati eta-minima [--applica]
    python -m backend.import_dati stato

AIFA pubblica i dati in licenza CC-BY 4.0: la fonte va citata (lo fa la scheda
prodotto tramite la fonte registrata in `fonti`).
Le intestazioni dei CSV AIFA non sono documentate in modo stabile: le colonne
vengono riconosciute per nome tra diverse varianti; se una colonna necessaria
manca, l'import si ferma e indica le intestazioni trovate, da mappare in
`database/configurazione.json` → `import.aifa.colonne`.
"""

import argparse
import csv
import io
import json
import re
import sqlite3
import sys
import urllib.request
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "database" / "farmacia.sqlite3"
CONFIG = ROOT / "database" / "configurazione.json"

AIFA_FILES = {
    "confezioni": "https://drive.aifa.gov.it/farmaci/confezioni_fornitura.csv",
    "principi_attivi": "https://drive.aifa.gov.it/farmaci/PA_confezioni.csv",
    "atc": "https://drive.aifa.gov.it/farmaci/atc.csv",
    "carenti": "https://www.aifa.gov.it/documents/20142/847339/elenco_medicinali_carenti.csv",
}
AIFA_SOURCE = {
    "id": "SRC-AIFA-ANAGRAFICA",
    "url": "https://www.aifa.gov.it/it/liste-dei-farmaci",
    "titolo": "AIFA - Liste dei farmaci: anagrafica farmaci e farmaci carenti (CC-BY 4.0)",
    "ente": "Agenzia Italiana del Farmaco",
}
GESTIONALE_SOURCE_ID = "SRC-GESTIONALE-EXPORT"

# Header variants seen across AIFA open data files; matched case-insensitively.
COLUMN_VARIANTS = {
    "aic": ("codice_aic", "aic", "cod_aic", "codice aic", "aic9", "codice_aic9"),
    "fornitura": ("fornitura", "regime_fornitura", "descrizione_fornitura", "classe_fornitura", "regime"),
    "atc": ("codice_atc", "atc", "cod_atc"),
    "stato": ("stato_amministrativo", "stato", "stato_amm"),
    "denominazione": ("denominazione", "farmaco", "nome_farmaco", "descrizione_farmaco", "medicinale"),
}
REGIME_PATTERNS = (  # order matters: longer codes first
    (r"\bvet[_ ]?rr|ricetta veterinaria", "vet_RR"),
    (r"\bRNRL\b|\bRRL\b|\bOSP\b|\bUSPL\b", "RRL"),
    (r"\bRNR\b|non ripetibile", "RNR"),
    (r"\bRR\b|ripetibile", "RR"),
    (r"\bOTC\b|automedicazione", "OTC"),
    (r"\bSOP\b|senza obbligo", "SOP"),
)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _config(path=CONFIG):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read_csv(path_or_text):
    """Read a CSV with an unknown delimiter (`;`, `|`, `,`, tab) and encoding."""
    if isinstance(path_or_text, Path):
        raw = path_or_text.read_bytes()
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
    else:
        text = path_or_text
    sample = text[:20000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";|,\t")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]
    return reader.fieldnames or [], rows


def find_columns(headers, overrides=None):
    lowered = {h.strip().casefold(): h for h in headers}
    result = {}
    for key, variants in COLUMN_VARIANTS.items():
        wanted = [(overrides or {}).get(key)] if (overrides or {}).get(key) else []
        for name in [*wanted, *variants]:
            if name and name.casefold() in lowered:
                result[key] = lowered[name.casefold()]
                break
    return result


def normalize_aic(value):
    """9-digit package AIC, or the 6-digit medicine code when only that is known."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 6:
        return digits
    return digits.zfill(9) if 7 <= len(digits) <= 9 else None


def map_regime(value):
    for pattern, regime in REGIME_PATTERNS:
        if re.search(pattern, value or "", re.IGNORECASE):
            return regime
    return None


def _log(db, fonte, esito, read, applied, rejected, nota):
    db.execute("""INSERT INTO registro_import (fonte, eseguito_il, esito, righe_lette, righe_applicate,
                                               righe_rifiutate, nota) VALUES (?,?,?,?,?,?,?)""",
               (fonte, _now(), esito, read, applied, rejected, nota[:500]))


def _ensure_source(db, source_id, url, title, owner, kind):
    db.execute("""INSERT INTO fonti (id, url, titolo, ente, consultata_il, tipo) VALUES (?,?,?,?,?,?)
                  ON CONFLICT(id) DO UPDATE SET consultata_il = excluded.consultata_il""",
               (source_id, url, title, owner, _now()[:10], kind))


def download_aifa(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    done = {}
    for name, url in AIFA_FILES.items():
        target = folder / f"{name}.csv"
        with urllib.request.urlopen(url, timeout=60) as response, open(target, "wb") as out:
            out.write(response.read())
        done[name] = str(target)
    return done


def import_aifa(folder, catalog=CATALOG, config=None):
    """Apply AIFA registry data to products matched by AIC. Returns a change report."""
    folder = Path(folder)
    overrides = ((config or _config()).get("import", {}).get("aifa", {}).get("colonne") or {})
    report = {"letti": 0, "applicati": 0, "rifiutati": 0, "modifiche": [], "senza_aic": [], "aic_non_trovati": [], "avvisi": []}
    by_aic = {}
    packages = folder / "confezioni.csv"
    if packages.is_file():
        headers, rows = read_csv(packages)
        columns = find_columns(headers, overrides)
        if "aic" not in columns:
            raise ValueError(f"Colonna AIC non trovata in {packages.name}. Intestazioni: {headers}")
        report["letti"] += len(rows)
        for row in rows:
            aic = normalize_aic(row.get(columns["aic"]))
            if aic:
                by_aic[aic] = {"fornitura": row.get(columns.get("fornitura", ""), ""),
                               "atc": row.get(columns.get("atc", ""), ""),
                               "stato": row.get(columns.get("stato", ""), ""),
                               "denominazione": row.get(columns.get("denominazione", ""), "")}
            else:
                report["rifiutati"] += 1
        missing = [key for key in ("fornitura", "atc") if key not in columns]
        if missing:
            report["avvisi"].append(f"Colonne non trovate in confezioni.csv: {missing}. Intestazioni: {headers}")
    shortages = set()
    shortage_file = folder / "carenti.csv"
    if shortage_file.is_file():
        headers, rows = read_csv(shortage_file)
        columns = find_columns(headers, overrides)
        if "aic" in columns:
            shortages = {aic for row in rows if (aic := normalize_aic(row.get(columns["aic"])))}
        else:
            report["avvisi"].append(f"Colonna AIC non trovata in carenti.csv. Intestazioni: {headers}")

    with closing(sqlite3.connect(catalog)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        if db.execute("PRAGMA user_version").fetchone()[0] < 7:
            raise sqlite3.DatabaseError("Applicare migrate-latest (schema v7) prima dell'import AIFA.")
        _ensure_source(db, AIFA_SOURCE["id"], AIFA_SOURCE["url"], AIFA_SOURCE["titolo"], AIFA_SOURCE["ente"], "aifa")
        today = _now()[:10]
        products = db.execute("""SELECT codice, nome, categoria, id_regolatorio, regime_fornitura, regime_fonte_id,
                                        atc, carente FROM prodotti WHERE dataset_tipo = 'reale'""").fetchall()
        for product in products:
            aic = normalize_aic(product["id_regolatorio"]) if product["id_regolatorio"] else None
            if not aic:
                if product["categoria"] in ("medicinale", "Farmaco da banco", "medicinale_veterinario"):
                    report["senza_aic"].append({"codice": product["codice"], "nome": product["nome"]})
                continue
            if len(aic) == 6:
                # Only the medicine code is known: use it only if every package agrees on the regime.
                family = [data for key, data in by_aic.items() if key.startswith(aic)]
                regimes = {map_regime(data["fornitura"]) for data in family}
                if family and len(regimes) == 1:
                    by_aic[aic] = {**family[0], "denominazione": family[0]["denominazione"]}
            if aic not in by_aic:
                if by_aic:
                    report["aic_non_trovati"].append({"codice": product["codice"], "aic": aic})
                continue
            data = by_aic[aic]
            changes = {}
            regime = map_regime(data["fornitura"])
            # Never overwrite a regime the pharmacist set from another source.
            if regime and product["regime_fornitura"] == "non_verificato":
                changes["regime_fornitura"] = regime
                changes["regime_fonte_id"] = AIFA_SOURCE["id"]
            elif regime and product["regime_fonte_id"] == AIFA_SOURCE["id"] and product["regime_fornitura"] != regime:
                changes["regime_fornitura"] = regime
            if data["atc"] and data["atc"] != (product["atc"] or ""):
                changes["atc"] = data["atc"]
            is_short = 1 if aic in shortages else 0
            if shortage_file.is_file() and is_short != product["carente"]:
                changes["carente"] = is_short
                changes["carenza_aggiornata_il"] = today
            if changes:
                sets = ", ".join(f"{key} = ?" for key in changes)
                db.execute(f"UPDATE prodotti SET {sets} WHERE codice = ?", (*changes.values(), product["codice"]))
                report["modifiche"].append({"codice": product["codice"], **changes})
                report["applicati"] += 1
        esito = "ok" if not report["avvisi"] else "parziale"
        _log(db, "aifa", esito, report["letti"], report["applicati"], report["rifiutati"],
             f"{len(report['modifiche'])} prodotti aggiornati; {len(report['senza_aic'])} medicinali senza AIC; "
             f"{len(report['aic_non_trovati'])} AIC non trovati")
    return report


def import_gestionale(path, catalog=CATALOG, config=None):
    """Import prices and stock from a CSV exported by the pharmacy management software.

    Column names come from configurazione.json → import.gestionale.colonne:
    {"codice": "...", "prezzo": "...", "giacenza": "..."}; `codice` matches the
    catalog code or the AIC (`chiave`: "codice" | "aic"). Incomplete rows are
    rejected and counted, never guessed.
    """
    settings = (config or _config()).get("import", {}).get("gestionale", {})
    mapping = {"codice": "codice", "prezzo": "prezzo", "giacenza": "giacenza", **(settings.get("colonne") or {})}
    key_kind = settings.get("chiave", "codice")
    headers, rows = read_csv(Path(path))
    missing = [mapping[k] for k in ("codice", "prezzo", "giacenza") if mapping[k] not in headers]
    if missing:
        raise ValueError(f"Colonne mancanti nel CSV: {missing}. Intestazioni trovate: {headers}")
    report = {"letti": len(rows), "applicati": 0, "rifiutati": 0, "sconosciuti": 0, "dettaglio_rifiuti": []}
    with closing(sqlite3.connect(catalog)) as db, db:
        db.execute("PRAGMA foreign_keys = ON")
        _ensure_source(db, GESTIONALE_SOURCE_ID, None, "Export CSV del gestionale della farmacia", "Farmacia", "farmacia")
        today = _now()[:10]
        for number, row in enumerate(rows, start=2):
            code = row.get(mapping["codice"], "").strip()
            price_raw = row.get(mapping["prezzo"], "").replace("€", "").replace(" ", "")
            stock_raw = row.get(mapping["giacenza"], "").strip()
            try:
                if not code:
                    raise ValueError("codice vuoto")
                if "," in price_raw and "." in price_raw:
                    price_raw = price_raw.replace(".", "")
                try:
                    price = round(float(price_raw.replace(",", ".")) * 100)
                    stock = int(stock_raw)
                except ValueError:
                    raise ValueError("prezzo o giacenza mancanti o non numerici") from None
                if price < 0 or stock < 0:
                    raise ValueError("valori negativi")
            except ValueError as error:
                report["rifiutati"] += 1
                report["dettaglio_rifiuti"].append(f"riga {number}: {error}")
                continue
            where = "codice = ?" if key_kind == "codice" else "id_regolatorio = ?"
            value = code if key_kind == "codice" else normalize_aic(code)
            updated = db.execute(f"""UPDATE prodotti SET prezzo_cent = ?, prezzo_banco_fonte_id = ?, prezzo_banco_data = ?,
                                         quantita = ?, quantita_fonte_id = ?, quantita_data = ?
                                     WHERE {where}""",
                                 (price, GESTIONALE_SOURCE_ID, today, stock, GESTIONALE_SOURCE_ID, today, value)).rowcount
            if updated:
                report["applicati"] += updated
            else:
                report["sconosciuti"] += 1
        esito = "ok" if not report["rifiutati"] else "parziale"
        _log(db, "gestionale", esito, report["letti"], report["applicati"], report["rifiutati"],
             f"{report['sconosciuti']} codici non presenti in catalogo")
    report["dettaglio_rifiuti"] = report["dettaglio_rifiuti"][:20]
    return report


_AGE = re.compile(r"(?:almeno|dai|a partire dai|non sotto i|minim\w*[^0-9]{0,40}|limite[^0-9]{0,25}|\()\s*(\d{1,2})\s*anni",
                  re.IGNORECASE)


def ages_from_relations(catalog=CATALOG, apply=False):
    """Minimum ages already written, with their source, in the documented relations.

    Only explicit phrases ("almeno 12 anni", "dai 6 anni", "(16 anni)") are used;
    a product whose texts disagree is reported and left alone.
    """
    with closing(sqlite3.connect(catalog)) as db, db:
        found = {}
        for code, text, source in db.execute(
                "SELECT prodotto_codice, prerequisiti, fonte_id FROM relazioni_concetto_prodotto WHERE fonte_id IS NOT NULL"):
            for age in _AGE.findall(text or ""):
                found.setdefault(code, set()).add((int(age), source))
        proposals, conflicts = [], []
        for code, values in sorted(found.items()):
            ages = {age for age, _ in values}
            if len(ages) != 1:
                conflicts.append({"codice": code, "eta": sorted(ages)})
                continue
            age, source = sorted(values)[0]
            current = db.execute("SELECT eta_minima_anni FROM prodotti WHERE codice=?", (code,)).fetchone()
            if current and current[0] is None:
                proposals.append({"codice": code, "eta_minima_anni": age, "fonte": source})
                if apply:
                    db.execute("UPDATE prodotti SET eta_minima_anni=?, eta_fonte_id=? WHERE codice=?", (age, source, code))
    return {"proposte": proposals, "in_conflitto": conflicts, "applicate": apply}


def import_status(catalog=CATALOG):
    """Latest run per source, for the diagnostics page."""
    try:
        db = sqlite3.connect(Path(catalog).resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    with closing(db):
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='registro_import'").fetchone():
            return []
        rows = db.execute("""SELECT fonte, eseguito_il, esito, righe_lette, righe_applicate, righe_rifiutate, nota
                             FROM registro_import r
                             WHERE id = (SELECT max(id) FROM registro_import WHERE fonte = r.fonte)
                             ORDER BY fonte""").fetchall()
    keys = ("fonte", "eseguito_il", "esito", "righe_lette", "righe_applicate", "righe_rifiutate", "nota")
    return [dict(zip(keys, row)) for row in rows]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("comando", choices=("aifa", "gestionale", "eta-minima", "stato"))
    parser.add_argument("file", nargs="?", type=Path)
    parser.add_argument("--cartella", type=Path, default=ROOT / "dati" / "aifa")
    parser.add_argument("--scarica", action="store_true", help="scarica prima i CSV AIFA nella cartella")
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--applica", action="store_true", help="eta-minima: scrive le proposte nel catalogo")
    args = parser.parse_args(argv)
    try:
        if args.comando == "aifa":
            if args.scarica:
                download_aifa(args.cartella)
            result = import_aifa(args.cartella, args.catalog)
            result["senza_aic"] = result["senza_aic"][:50]
        elif args.comando == "gestionale":
            if not args.file:
                parser.error("Indicare il CSV esportato dal gestionale.")
            result = import_gestionale(args.file, args.catalog)
        elif args.comando == "eta-minima":
            result = ages_from_relations(args.catalog, apply=args.applica)
        else:
            result = import_status(args.catalog)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, sqlite3.Error) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
