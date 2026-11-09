"""Apply the v3-to-v4 catalog migration and import a sourced product dataset."""

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "database" / "farmacia.sqlite3"
DEFAULT_MIGRATION = ROOT / "database" / "004_catalogo_v4.sql"
DEFAULT_SEED = ROOT / "database" / "catalogo-reale.json"
DEFAULT_SYMPTOM_SEED = ROOT / "database" / "collegamenti-sintomo.json"
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")
SOURCE_KINDS = {"aifa", "ministero", "produttore", "commerciale", "farmacia", "demo", "altro"}
REGULATORY_STATUS = {"autorizzato", "notificato", "non_verificato", "non_applicabile", "sospeso", "revocato"}
SYMPTOM_CONCEPT_TYPES = {"sintomo", "condizione", "tema", "bisogno"}
SYMPTOM_RELATION_TYPES = {"indicazione_etichetta", "contesto_ricerca"}
SYMPTOM_SOURCE_DOMAINS = {
    "aspirina.it", "rinazina.it", "aboca.com", "maalox.com", "geffer.it",
    "flector.it", "schwabe.it", "thea.it", "ucbpharma.it", "tachipirina.it",
    "nurofen.it", "multicentrum.it", "supradyn.it",
}
VERIFIED_LEAFLET_URLS = {
    "https://assets.ctfassets.net/hcd109vfxzqs/46uAxThECMNgO2RWcF2nEr/66298543d72019cbe3fcd61f4eac4fd3/12-2022_fi_actigrip_500.pdf",
}
ALIAS_TYPES = {"nome_commerciale", "sinonimo", "nome_uso_comune", "codice_pubblico"}
SUPPLEMENT_TYPES = {"vitamina", "minerale", "estratto", "probiotico", "altro"}
SOURCE_CLAIMS = {"identita", "composizione", "stato_regolatorio", "commercializzazione", "immagine",
                 "prezzo_riferimento", "prezzo_banco", "scorte", "equivalenza", "associazione_clinica"}
# Context notes may be recorded by a source, but they are not normalized product
# assertions and must never be inserted into prodotto_fonti as verified claims.
SOURCE_CONTEXT_LABELS = {"claim_ce_pagina_produttore", "classificazione_dichiarata_produttore",
                         "contesto_normativo_notifica", "identificativo_AIC",
                         "dato_storico_non_corrente", "claim_supporto_fisiologico"}
HISTORICAL_SUPPORT_MAP = {
    "identificativo_AIC": ("identificativo_regolatorio", "candidata"),
    "composizione": ("composizione", "candidata"),
    "dato_storico_non_corrente": ("dato_storico", "verificata"),
}


def _connect(path):
    db = sqlite3.connect(Path(path).resolve())
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def inspect_catalog(path=DEFAULT_CATALOG):
    if not Path(path).is_file():
        raise FileNotFoundError(f"Catalogo assente: {path}")
    with closing(_connect(path)) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = [tuple(row) for row in db.execute("PRAGMA foreign_key_check")]
        counts = {}
        if version >= 3:
            for table in ("prodotti", "offerte", "relazioni_prodotti",
                          "concetti", "relazioni_concetto_prodotto"):
                try:
                    counts[table] = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                except sqlite3.Error:
                    counts[table] = None
        return {"user_version": version, "integrity_check": integrity, "foreign_key_check": foreign_keys,
                "counts": counts}


def migrate_catalog(path=DEFAULT_CATALOG, migration=DEFAULT_MIGRATION):
    """Apply schema v4 once; leave the caller's backup policy to the operator."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Catalogo assente: {path}")
    sql = Path(migration).read_text(encoding="utf-8")
    with closing(sqlite3.connect(path.resolve())) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version == 4:
            report = inspect_catalog(path)
            if report["integrity_check"] != "ok" or report["foreign_key_check"]:
                raise sqlite3.DatabaseError("Il catalogo v4 non supera i controlli di integrità.")
            return {"applied": False, **report}
        if version != 3:
            raise sqlite3.DatabaseError(f"Migrazione attesa da schema v3, trovato v{version}.")
        try:
            db.executescript(sql)
        except Exception:
            if db.in_transaction:
                db.rollback()
            db.execute("PRAGMA foreign_keys = ON")
            raise
    report = inspect_catalog(path)
    if report["user_version"] != 4 or report["integrity_check"] != "ok" or report["foreign_key_check"]:
        raise sqlite3.DatabaseError("La migrazione v4 non supera i controlli di integrità.")
    return {"applied": True, **report}


def _required_text(value, label, limit=500):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"Campo richiesto non valido: {label}.")
    return value.strip()


def _source_value(source, *keys):
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def _validate_source(source, label, default_kind):
    if not isinstance(source, dict):
        raise ValueError(f"Fonte mancante o non valida: {label}.")
    url = _required_text(_source_value(source, "url"), f"{label}.url", 2000)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or any(ch.isspace() for ch in url):
        raise ValueError(f"URL fonte non valido: {label}.")
    title = _required_text(_source_value(source, "title", "titolo"), f"{label}.title", 300)
    owner = _required_text(_source_value(source, "owner", "ente", "manufacturer"), f"{label}.owner", 300)
    consulted = _required_text(_source_value(source, "consulted_at", "consulted_on", "consultata_il", "date"),
                               f"{label}.consulted_at", 80)
    kind = _source_value(source, "kind", "tipo") or default_kind
    if kind not in SOURCE_KINDS:
        kind = default_kind
    version = _source_value(source, "version", "published_at", "data_o_versione")
    if version is not None and (not isinstance(version, str) or len(version) > 200):
        raise ValueError(f"Versione della fonte non valida: {label}.")
    supports = source.get("supports", [])
    if not isinstance(supports, list) or any(claim not in SOURCE_CLAIMS | SOURCE_CONTEXT_LABELS for claim in supports):
        raise ValueError(f"Elenco delle affermazioni supportate non valido: {label}.")
    return {"url": url, "title": title, "owner": owner, "consulted": consulted,
            "version": version, "kind": kind, "supports": sorted(set(supports))}


def _source_id(db, source):
    digest = hashlib.sha256(source["url"].encode("utf-8")).hexdigest()[:24].upper()
    source_id = "SRC-" + digest
    existing = db.execute("SELECT id FROM fonti WHERE url = ?", (source["url"],)).fetchone()
    if existing:
        source_id = existing["id"]
        db.execute("""UPDATE fonti SET titolo=?, ente=?, consultata_il=?, data_o_versione=?, tipo=?
                      WHERE id=?""", (source["title"], source["owner"], source["consulted"], source["version"],
                                       source["kind"], source_id))
    else:
        db.execute("""INSERT INTO fonti (id,url,titolo,ente,consultata_il,data_o_versione,tipo)
                      VALUES (?,?,?,?,?,?,?)""",
                   (source_id, source["url"], source["title"], source["owner"], source["consulted"],
                    source["version"], source["kind"]))
    return source_id


def _normalize_ingredient(name):
    return " ".join(_required_text(name, "principio attivo", 200).casefold().split())


def _ingredient_details(product):
    details = product.get("ingredient_details")
    if details is None:
        details = product.get("active_ingredients", [])
    if not isinstance(details, list):
        raise ValueError(f"Principi attivi non validi per {product.get('code')}.")
    result = []
    seen = set()
    for item in details:
        if isinstance(item, str):
            row = {"name": item, "amount": None, "unit": None}
        elif isinstance(item, dict):
            row = {"name": item.get("name"), "amount": item.get("amount"), "unit": item.get("unit")}
        else:
            raise ValueError(f"Principio attivo non valido per {product.get('code')}.")
        normalized = _normalize_ingredient(row["name"])
        if normalized in seen:
            continue
        for key in ("amount", "unit"):
            if row[key] is not None and (not isinstance(row[key], (str, int, float)) or isinstance(row[key], bool)):
                raise ValueError(f"Quantità del principio attivo non valida per {product.get('code')}.")
            if row[key] is not None:
                row[key] = str(row[key]).strip()
                if not row[key] or len(row[key]) > 80:
                    raise ValueError(f"Quantità del principio attivo non valida per {product.get('code')}.")
        row["name"] = _required_text(row["name"], "principio attivo", 200)
        row["normalized"] = normalized
        result.append(row)
        seen.add(normalized)
    return result


def _supplement_details(product):
    details = product.get("supplement_ingredients", [])
    if not isinstance(details, list):
        raise ValueError(f"Ingredienti dell’integratore non validi per {product.get('code')}.")
    result, seen = [], set()
    for item in details:
        if not isinstance(item, dict):
            raise ValueError(f"Ingrediente dell’integratore non valido per {product.get('code')}.")
        name = _required_text(item.get("name"), f"{product.get('code')}.supplement_ingredient", 200)
        normalized = _normalize_ingredient(name)
        if normalized in seen:
            continue
        amount, unit = item.get("amount"), item.get("unit")
        for key, value in (("amount", amount), ("unit", unit)):
            if value is not None and (not isinstance(value, (str, int, float)) or isinstance(value, bool)):
                raise ValueError(f"{key} dell’ingrediente non valido per {product.get('code')}.")
            if value is not None:
                value = str(value).strip()
                if not value or len(value) > 80:
                    raise ValueError(f"{key} dell’ingrediente non valido per {product.get('code')}.")
            if key == "amount":
                amount = value
            else:
                unit = value
        kind = item.get("type") or "altro"
        if kind not in SUPPLEMENT_TYPES:
            kind = "altro"
        result.append({"name": name, "normalized": normalized, "amount": amount, "unit": unit, "type": kind})
        seen.add(normalized)
    return result


def _validate_product(raw):
    if not isinstance(raw, dict):
        raise ValueError("Ogni prodotto deve essere un oggetto JSON.")
    code = _required_text(raw.get("code"), "code", 80)
    if not IDENTIFIER.fullmatch(code):
        raise ValueError(f"Codice prodotto non valido: {code}.")
    name = _required_text(raw.get("name"), f"{code}.name", 300)
    category = _required_text(raw.get("category"), f"{code}.category", 100)
    manufacturer = _required_text(raw.get("manufacturer"), f"{code}.manufacturer", 300)
    form = _required_text(_source_value(raw, "form", "variant"), f"{code}.form", 300)
    strength = raw.get("strength")
    route = raw.get("route")
    for field, value in (("strength", strength), ("route", route)):
        if value is not None and (not isinstance(value, str) or len(value) > 300):
            raise ValueError(f"Campo {field} non valido per {code}.")
    if raw.get("price_cents", raw.get("prezzo_cent")) is not None:
        raise ValueError(f"Il prezzo del prodotto reale {code} non ha una fonte di farmacia autorizzata.")
    if raw.get("stock", raw.get("quantita")) is not None:
        raise ValueError(f"Le scorte del prodotto reale {code} non hanno una fonte di farmacia autorizzata.")
    market = _validate_source(raw.get("market_source"), f"{code}.market_source", "produttore")
    regulatory_raw = raw.get("regulatory_source")
    regulatory = _validate_source(regulatory_raw, f"{code}.regulatory_source", "aifa") if regulatory_raw else None
    historical_regulatory = None
    if isinstance(regulatory_raw, dict) and isinstance(regulatory_raw.get("supporting_source"), dict):
        historical_raw = dict(regulatory_raw["supporting_source"])
        historical_raw.setdefault("consulted_at", _source_value(regulatory_raw, "consulted_at", "consulted_on"))
        historical_raw.setdefault("version", _source_value(historical_raw, "source_date", "note"))
        historical_regulatory = _validate_source(
            historical_raw, f"{code}.regulatory_source.supporting_source", "aifa")
    composition_raw = raw.get("composition_source")
    composition = _validate_source(composition_raw, f"{code}.composition_source", "produttore") if composition_raw else None
    status = raw.get("regulatory_status", "non_verificato")
    if status not in REGULATORY_STATUS:
        raise ValueError(f"Stato regolatorio non valido per {code}: {status}.")
    if status not in {"non_verificato", "non_applicabile"} \
            and (not regulatory or "stato_regolatorio" not in regulatory["supports"]):
        raise ValueError(f"Stato regolatorio senza fonte specifica che lo supporti per {code}.")
    identifier = raw.get("regulatory_identifier")
    identifier_type = raw.get("regulatory_identifier_type")
    if identifier is not None:
        identifier = _required_text(identifier, f"{code}.regulatory_identifier", 100)
    if identifier_type is not None:
        identifier_type = _required_text(identifier_type, f"{code}.regulatory_identifier_type", 50)
    if identifier and not identifier_type:
        raise ValueError(f"Indicare il tipo di identificativo regolatorio per {code}.")
    market_status = "verificato" if market else "non_verificato"
    if not isinstance(raw.get("aliases", []), list):
        raise ValueError(f"Alias non validi per {code}.")
    aliases = []
    for alias in raw.get("aliases", []):
        if not isinstance(alias, dict):
            raise ValueError(f"Alias non valido per {code}.")
        alias_name = _required_text(alias.get("name"), f"{code}.alias", 250)
        alias_type = alias.get("type") or "sinonimo"
        if alias_type not in ALIAS_TYPES:
            alias_type = "sinonimo"
        aliases.append({"name": alias_name, "type": alias_type})
    image = raw.get("image")
    if image:
        raise ValueError(f"Il seed non importa immagini senza verifica di origine/licenza ({code}).")
    ingredients = _ingredient_details(raw)
    supplement_ingredients = _supplement_details(raw)
    if (ingredients or supplement_ingredients) \
            and (not composition or "composizione" not in composition["supports"]):
        raise ValueError(f"Composizione senza composition_source che documenti il contenuto di {code}.")
    if "identita" not in market["supports"] or "commercializzazione" not in market["supports"]:
        raise ValueError(f"Fonte di mercato senza prove esplicite d’identità e commercializzazione per {code}.")
    return {"code": code, "name": name, "category": category, "manufacturer": manufacturer, "form": form,
            "strength": strength, "route": route, "market": market, "regulatory": regulatory,
            "historical_regulatory": historical_regulatory, "composition": composition,
            "regulatory_status": status, "market_status": market_status,
            "identifier": identifier, "identifier_type": identifier_type,
            "ingredients": ingredients, "supplement_ingredients": supplement_ingredients, "aliases": aliases}


def seed_products(path=DEFAULT_CATALOG, seed=DEFAULT_SEED, only_new=False):
    """Idempotently import source-backed products without inventing commercial data."""
    payload = json.loads(Path(seed).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
        raise ValueError("Il seed deve contenere un array products.")
    products = [_validate_product(item) for item in payload["products"]]
    codes = [item["code"] for item in products]
    if len(codes) != len(set(codes)):
        raise ValueError("Il seed contiene codici prodotto duplicati.")
    skipped_existing = 0
    with closing(_connect(path)) as db, db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version != 4:
            raise sqlite3.DatabaseError(f"Il seed richiede lo schema v4, trovato v{version}.")
        for item in products:
            existing = db.execute("SELECT dataset_tipo FROM prodotti WHERE codice=?", (item["code"],)).fetchone()
            if existing and existing["dataset_tipo"] != "reale":
                raise ValueError(f"Il codice {item['code']} è già usato da un record demo.")
            if existing and only_new:
                skipped_existing += 1

        if only_new:
            products = [item for item in products if not db.execute(
                "SELECT 1 FROM prodotti WHERE codice=?", (item["code"],)).fetchone()]

        counts = Counter(item["category"] for item in products)

        for item in products:
            code = item["code"]
            regulatory_id = _source_id(db, item["regulatory"]) if item["regulatory"] else None
            historical_regulatory_id = (_source_id(db, item["historical_regulatory"])
                                        if item["historical_regulatory"] else None)
            composition_id = _source_id(db, item["composition"]) if item["composition"] else None
            market_id = _source_id(db, item["market"])
            db.execute("""INSERT INTO prodotti (
                           codice,nome,categoria,formato,prezzo_cent,quantita,principio_attivo,dosaggio,via,immagine,fonte,
                           dataset_tipo,stato_regolatorio,stato_mercato,stato_revisione,tipo_id_regolatorio,id_regolatorio
                       ) VALUES (?,?,?,?,NULL,NULL,NULL,?,?,NULL,?,'reale',?,?, 'da_revisionare',?,?)
                       ON CONFLICT(codice) DO UPDATE SET
                           nome=excluded.nome,categoria=excluded.categoria,formato=excluded.formato,
                           prezzo_cent=NULL,quantita=NULL,principio_attivo=NULL,dosaggio=excluded.dosaggio,
                           via=excluded.via,immagine=NULL,fonte=excluded.fonte,dataset_tipo='reale',
                           stato_regolatorio=excluded.stato_regolatorio,stato_mercato=excluded.stato_mercato,
                           stato_revisione='da_revisionare',tipo_id_regolatorio=excluded.tipo_id_regolatorio,
                           id_regolatorio=excluded.id_regolatorio""",
                       (code,item["name"],item["category"],item["form"],item["strength"],item["route"],
                        "Fonti pubbliche documentate",item["regulatory_status"],item["market_status"],
                        item["identifier_type"],item["identifier"]))
            db.execute("DELETE FROM prodotto_principi_attivi WHERE prodotto_codice=?", (code,))
            db.execute("DELETE FROM prodotto_componenti_integratore WHERE prodotto_codice=?", (code,))
            db.execute("DELETE FROM alias_prodotto WHERE prodotto_codice=?", (code,))
            db.execute("DELETE FROM prodotto_fonti WHERE prodotto_codice=?", (code,))

            for claim, source_id in (("identita", market_id), ("commercializzazione", market_id)):
                db.execute("INSERT INTO prodotto_fonti VALUES (?,?,?,'verificata')", (code,source_id,claim))
            if regulatory_id and "stato_regolatorio" in item["regulatory"]["supports"]:
                db.execute("INSERT INTO prodotto_fonti VALUES (?,?,?,'verificata')", (code,regulatory_id,"stato_regolatorio"))
            if composition_id and "composizione" in item["composition"]["supports"]:
                db.execute("INSERT INTO prodotto_fonti VALUES (?,?,?,'verificata')",
                           (code,composition_id,"composizione"))
            if historical_regulatory_id:
                for source_claim, (claim, verification) in HISTORICAL_SUPPORT_MAP.items():
                    if source_claim in item["historical_regulatory"]["supports"]:
                        db.execute("INSERT OR IGNORE INTO prodotto_fonti VALUES (?,?,?,?)",
                                   (code,historical_regulatory_id,claim,verification))

            for ingredient in item["ingredients"]:
                db.execute("""INSERT INTO principi_attivi (nome,nome_normalizzato) VALUES (?,?)
                              ON CONFLICT(nome_normalizzato) DO NOTHING""",
                           (ingredient["name"],ingredient["normalized"]))
                ingredient_id = db.execute("SELECT id FROM principi_attivi WHERE nome_normalizzato=?",
                                           (ingredient["normalized"],)).fetchone()[0]
                db.execute("""INSERT INTO prodotto_principi_attivi
                              (prodotto_codice,principio_attivo_id,quantita_per_unita,unita,fonte_id)
                              VALUES (?,?,?,?,?)""",
                           (code,ingredient_id,ingredient["amount"],ingredient["unit"],composition_id))
            for ingredient in item["supplement_ingredients"]:
                db.execute("""INSERT INTO componenti_integratore (nome,nome_normalizzato,tipo) VALUES (?,?,?)
                              ON CONFLICT(nome_normalizzato) DO UPDATE SET nome=excluded.nome,tipo=excluded.tipo""",
                           (ingredient["name"],ingredient["normalized"],ingredient["type"]))
                component_id = db.execute("SELECT id FROM componenti_integratore WHERE nome_normalizzato=?",
                                          (ingredient["normalized"],)).fetchone()[0]
                db.execute("""INSERT INTO prodotto_componenti_integratore
                              (prodotto_codice,componente_id,quantita_per_unita,unita,fonte_id)
                              VALUES (?,?,?,?,?)""",
                           (code,component_id,ingredient["amount"],ingredient["unit"],composition_id))
            for alias in item["aliases"]:
                db.execute("INSERT INTO alias_prodotto VALUES (?,?,?,?)",
                           (code,alias["name"],alias["type"],market_id))

    return {"inserted_or_updated": len(products), "by_category": dict(sorted(counts.items())),
            "dataset_type": "reale", "price_and_stock": None,
            "only_new": bool(only_new), "skipped_existing": skipped_existing}


def seed_symptom_associations(path=DEFAULT_CATALOG, seed=DEFAULT_SYMPTOM_SEED):
    """Load source-backed symptom links as candidates; never approve a clinical relation."""
    payload = json.loads(Path(seed).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("Versione seed dei collegamenti sintomo non valida.")
    concepts, source_rows, relations = payload.get("concepts"), payload.get("sources", []), payload.get("relations")
    if not isinstance(concepts, list) or not isinstance(source_rows, list) or not isinstance(relations, list):
        raise ValueError("Il seed dei collegamenti sintomo deve contenere concetti e relazioni.")

    clean_concepts = []
    for item in concepts:
        if not isinstance(item, dict):
            raise ValueError("Concetto sintomo non valido.")
        concept_id = _required_text(item.get("id"), "concept.id", 80)
        name = _required_text(item.get("name"), "concept.name", 200)
        kind = item.get("type")
        if not IDENTIFIER.fullmatch(concept_id) or kind not in SYMPTOM_CONCEPT_TYPES:
            raise ValueError(f"Identificativo o tipo concetto non valido: {concept_id}.")
        clean_concepts.append((concept_id, name, kind))
    if len({item[0] for item in clean_concepts}) != len(clean_concepts):
        raise ValueError("Il seed contiene concetti duplicati.")
    concept_ids = {item[0] for item in clean_concepts}

    clean_sources = {}
    for index, source in enumerate(source_rows):
        clean = _validate_source(source, f"sources[{index}]", "produttore")
        parsed = urlsplit(clean["url"])
        host = (parsed.hostname or "").casefold().rstrip(".")
        official = parsed.scheme == "https" and not parsed.username and not parsed.password and any(
            host == domain or host.endswith("." + domain) for domain in SYMPTOM_SOURCE_DOMAINS)
        if not official and clean["url"] not in VERIFIED_LEAFLET_URLS:
            raise ValueError("La fonte deve essere HTTPS e appartenere al dominio ufficiale dichiarato.")
        if clean["url"] in clean_sources:
            raise ValueError(f"Fonte duplicata nel seed: {clean['url']}.")
        clean_sources[clean["url"]] = clean

    clean_relations = []
    relation_keys = set()
    for item in relations:
        if not isinstance(item, dict):
            raise ValueError("Relazione sintomo-prodotto non valida.")
        concept_id = _required_text(item.get("concept_id"), "relation.concept_id", 80)
        code = _required_text(item.get("product_code"), "relation.product_code", 80)
        relation_type = item.get("type")
        if concept_id not in concept_ids or not IDENTIFIER.fullmatch(code):
            raise ValueError(f"Concetto o codice prodotto non valido: {concept_id}/{code}.")
        if relation_type not in SYMPTOM_RELATION_TYPES:
            raise ValueError("Sono ammesse solo indicazioni riportate in etichetta.")
        key = (concept_id, code, relation_type)
        if key in relation_keys:
            raise ValueError(f"Relazione duplicata nel seed: {concept_id}/{code}.")
        relation_keys.add(key)

        fields = {
            "context": _required_text(item.get("context"), "relation.context", 1200),
            "claim": _required_text(item.get("claim"), "relation.claim", 800),
            "prerequisites": _required_text(item.get("prerequisites"), "relation.prerequisites", 800),
            "exclusions": _required_text(item.get("exclusions"), "relation.exclusions", 800),
            "source_url": _required_text(item.get("source_url"), "relation.source_url", 2000),
            "source_version": _required_text(item.get("source_version"), "relation.source_version", 200),
        }
        parsed = urlsplit(fields["source_url"])
        host = (parsed.hostname or "").casefold().rstrip(".")
        official = parsed.scheme == "https" and not parsed.username and not parsed.password and any(
            host == domain or host.endswith("." + domain) for domain in SYMPTOM_SOURCE_DOMAINS)
        if not official and fields["source_url"] not in VERIFIED_LEAFLET_URLS:
            raise ValueError(f"La relazione {concept_id}/{code} non usa una fonte HTTPS ufficiale ammessa.")
        source_definition = clean_sources.get(fields["source_url"])
        required_support = ("associazione_clinica" if relation_type == "indicazione_etichetta"
                            else "claim_supporto_fisiologico")
        has_product_identity = (source_definition and
                                bool({"identita", "commercializzazione"}.intersection(source_definition["supports"])))
        if not source_definition or required_support not in source_definition["supports"] or not has_product_identity:
            raise ValueError(f"La fonte di {concept_id}/{code} non sostiene il tipo di relazione richiesto.")
        clean_relations.append((concept_id, code, relation_type, fields))

    with closing(_connect(path)) as db, db:
        if db.execute("PRAGMA user_version").fetchone()[0] != 4:
            raise sqlite3.DatabaseError("I collegamenti sintomo richiedono lo schema v4.")
        source_ids = {url: _source_id(db, source) for url, source in clean_sources.items()}
        for concept_id, name, kind in clean_concepts:
            db.execute("""INSERT INTO concetti (id,nome,tipo) VALUES (?,?,?)
                          ON CONFLICT(id) DO UPDATE SET nome=excluded.nome,tipo=excluded.tipo""",
                       (concept_id, name, kind))

        inserted_claims = 0
        context_relations = 0
        for concept_id, code, relation_type, fields in clean_relations:
            product = db.execute("SELECT dataset_tipo FROM prodotti WHERE codice=?", (code,)).fetchone()
            if not product or product["dataset_tipo"] != "reale":
                raise ValueError(f"Il prodotto {code} manca o non e' un record reale.")
            source = db.execute("SELECT id,url FROM fonti WHERE url=?", (fields["source_url"],)).fetchone()
            if not source and fields["source_url"] in source_ids:
                source = db.execute("SELECT id,url FROM fonti WHERE id=?",
                                    (source_ids[fields["source_url"]],)).fetchone()
            if not source or source["url"] != fields["source_url"]:
                raise ValueError(f"Fonte non presente nel catalogo per {code}: {fields['source_url']}.")
            source_definition = clean_sources.get(fields["source_url"])
            if source_definition:
                for claim_name in source_definition["supports"]:
                    if claim_name in SOURCE_CLAIMS:
                        db.execute("INSERT OR IGNORE INTO prodotto_fonti VALUES (?,?,?,'verificata')",
                                   (code, source["id"], claim_name))
            source_link = db.execute("""SELECT 1 FROM prodotto_fonti
                                       WHERE prodotto_codice=? AND fonte_id=?
                                         AND affermazione IN ('identita','commercializzazione')
                                         AND stato_verifica='verificata'""",
                                     (code, source["id"])).fetchone()
            if not source_link:
                raise ValueError(f"La fonte non e' collegata come identita/commercializzazione per {code}.")
            if relation_type == "indicazione_etichetta":
                claim = db.execute("""SELECT stato_verifica FROM prodotto_fonti
                                      WHERE prodotto_codice=? AND fonte_id=? AND affermazione='associazione_clinica'""",
                                   (code, source["id"])).fetchone()
                if claim is None:
                    db.execute("INSERT INTO prodotto_fonti VALUES (?,?,?,'verificata')",
                               (code, source["id"], "associazione_clinica"))
                    inserted_claims += 1
                elif claim["stato_verifica"] != "verificata":
                    raise ValueError(
                        f"La claim associazione_clinica per {code} deve essere verificata; "
                        f"stato esistente: {claim['stato_verifica']}. Nessuno stato viene convertito dal seed."
                    )
            else:
                product_category = db.execute("SELECT categoria FROM prodotti WHERE codice=?", (code,)).fetchone()
                if not product_category or product_category["categoria"] != "integratore_alimentare":
                    raise ValueError("Il contesto supporto-immunitario accetta solo integratori alimentari.")
                context_relations += 1

            db.execute("""INSERT INTO relazioni_concetto_prodotto (
                              concetto_id,prodotto_codice,tipo,contesto,benefici,rischi,
                              prerequisiti,esclusioni,fonte_id,versione_fonte,stato_revisione
                          ) VALUES (?,?,?,?,?,'',?,?,?,?,'candidata')
                          ON CONFLICT(concetto_id,prodotto_codice,tipo) DO UPDATE SET
                              contesto=excluded.contesto,benefici=excluded.benefici,
                              prerequisiti=excluded.prerequisiti,esclusioni=excluded.esclusioni,
                              fonte_id=excluded.fonte_id,versione_fonte=excluded.versione_fonte
                          WHERE relazioni_concetto_prodotto.stato_revisione='candidata'""",
                       (concept_id, code, relation_type, fields["context"], fields["claim"],
                        fields["prerequisites"], fields["exclusions"], source["id"], fields["source_version"]))

        report = inspect_catalog(path)
        if report["integrity_check"] != "ok" or report["foreign_key_check"]:
            raise sqlite3.DatabaseError("Il seed dei collegamenti sintomo non supera i controlli di integrita'.")
    return {"concepts": len(clean_concepts), "relations": len(clean_relations),
            "association_claims_added": inserted_claims, "context_relations": context_relations,
            "review_status": "candidata",
            "catalog": inspect_catalog(path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Gestisce migrazioni, prodotti e relazioni documentate.")
    parser.add_argument("action", choices=("migrate", "seed", "seed-symptoms", "check"))
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--only-new", action="store_true",
                        help="importa solo codici assenti e preserva ogni record già presente")
    parser.add_argument("--symptom-seed", type=Path, default=DEFAULT_SYMPTOM_SEED)
    parser.add_argument("--migration", type=Path, default=DEFAULT_MIGRATION)
    args = parser.parse_args(argv)
    try:
        if args.action == "migrate":
            result = migrate_catalog(args.catalog, args.migration)
        elif args.action == "seed":
            result = seed_products(args.catalog, args.seed, only_new=args.only_new)
        elif args.action == "seed-symptoms":
            result = seed_symptom_associations(args.catalog, args.symptom_seed)
        else:
            result = inspect_catalog(args.catalog)
            if result["integrity_check"] != "ok" or result["foreign_key_check"]:
                raise sqlite3.DatabaseError("Il catalogo non supera i controlli d’integrità.")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, sqlite3.Error, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
