"""Read the current catalog and searchable Markdown knowledge without storing queries."""

import json
import re
import sqlite3
import sys
import tomllib
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from backend.catalog_setup import SYMPTOM_SOURCE_DOMAINS, VERIFIED_LEAFLET_URLS
ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "database" / "farmacia.sqlite3"
WIKI = ROOT / "wiki" / "schede"
PACKAGES = ROOT / "database" / "confezioni.json"
CLASSIFICATIONS = "classificazioni.json"
FORM_NAMES = {
    "spray": ("Spray", r"spray"),
    "compresse": ("Compresse", r"compress[ae]|pastigli[ae]"),
    "sciroppo": ("Sciroppo", r"sciropp[oi]"),
    "capsule": ("Capsule", r"capsul[ae]"),
    "bustine": ("Bustine", r"bustin[ae]"),
    "granulato": ("Granulato", r"granulat[oi]"),
    "collirio": ("Collirio", r"collir(?:io|i)"),
    "gocce": ("Gocce", r"gocc[ae]"),
    "gel": ("Gel", r"gel"),
    "crema": ("Crema", r"crem[ae]"),
}
SYMPTOM_CONCEPT_IDS = frozenset({
    "raffreddore", "congestione-nasale", "tosse", "acidita-stomaco", "reflusso",
    "mal-di-testa", "contusioni", "irritazione-oculare", "allergia-nasale",
    "allergia-oculare", "allergia-cutanea", "micosi-cutanee", "dermatite", "ematomi",
    "artrosi-cane", "artrosi-gatto", "parassiti-cane", "parassiti-gatto",
})
CONTEXT_CONCEPT_IDS = frozenset({"supporto-immunitario"})
_OFFICIAL_PRODUCT_DOMAINS = SYMPTOM_SOURCE_DOMAINS | {
    "aifa.gov.it", "aspirina.it", "rinazina.it", "aboca.com", "actigrip.it",
    "gazzettaufficiale.it",
}


def normalize(value):
    return " ".join(re.findall(r"[^\W_]+", value.casefold()))


def product_form_key(value):
    # Use the primary dosage form first, falling back to a package descriptor.
    head, _, tail = value.partition(";")
    for part in (head, tail):
        matches = [key for key, (_, pattern) in FORM_NAMES.items()
                   if re.search(rf"\b(?:{pattern})\b", part, re.IGNORECASE)]
        if set(matches) == {"granulato", "bustine"}:
            return "granulato"
        if matches:
            return matches[0] if len(matches) == 1 else None
    return None


def _product_classification(db, catalog, code):
    try:
        records = json.loads(catalog.with_name(CLASSIFICATIONS).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None, None
    entry = records.get(code) if isinstance(records, dict) else None
    if not isinstance(entry, dict):
        return None, None
    key, source_id = entry.get("classification"), entry.get("source_id")
    if key not in ("generico", "marca") or not isinstance(source_id, str):
        return None, None
    source = _source_detail(db, source_id)
    if not source or source.get("kind") not in {"aifa", "ministero", "produttore"}:
        return None, None
    try:
        url = urlsplit(source.get("url") or "")
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            return None, None
    except ValueError:
        return None, None
    identity = any(item["id"] == source_id and item["affermazione"] == "identita"
                   and item["stato_verifica"] == "verificata" for item in _product_assertions(db, code))
    return (key, source) if identity else (None, None)


def catalog_connection(catalog=CATALOG, writable=False):
    mode = "rw" if writable else "ro"
    db = sqlite3.connect(catalog.resolve().as_uri() + f"?mode={mode}", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def _table_exists(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _table_columns(db, name):
    if not _table_exists(db, name):
        return set()
    return {row["name"] for row in db.execute(f"PRAGMA table_info({name})")}


def _source_detail(db, source_id):
    if not source_id or not _table_exists(db, "fonti"):
        return None
    row = db.execute("""
        SELECT id, url, titolo, ente, consultata_il, data_o_versione, tipo
        FROM fonti WHERE id = ?
    """, (source_id,)).fetchone()
    if not row:
        return None
    source = dict(row)
    # Keep the database's Italian columns for backend callers while exposing
    # stable display names to the session/frontend boundary.
    source.update({
        "title": source["titolo"], "label": source["titolo"], "kind": source.get("tipo"),
        "owner": source.get("ente"), "checked_at": source.get("consultata_il"),
        "version": source.get("data_o_versione"),
    })
    return source


def _is_official_product_source(source):
    """Accept only linked HTTPS sources on explicitly supported official domains."""
    if not source or not source.get("url") or not source.get("owner"):
        return False
    if source["url"] in VERIFIED_LEAFLET_URLS:
        return True
    try:
        parsed = urlsplit(source["url"])
        host = (parsed.hostname or "").casefold().rstrip(".")
    except (TypeError, ValueError):
        return False
    return (parsed.scheme.casefold() == "https" and
            any(host == domain or host.endswith("." + domain) for domain in _OFFICIAL_PRODUCT_DOMAINS))


def _indication_source_claim_is_verified(db, product_code, source_id):
    """Require a verified source claim for symptom-to-label indications.

    `_claim_is_verified()` also accepts `demo` for general product-display
    behavior. This narrower check must not let demo source claims authorize
    symptom-product matches.
    """
    if not source_id or not _table_exists(db, "prodotto_fonti"):
        return False
    return db.execute("""
        SELECT 1 FROM prodotto_fonti
        WHERE prodotto_codice = ? AND fonte_id = ?
          AND affermazione IN ('indicazione', 'associazione_clinica')
          AND stato_verifica = 'verificata'
    """, (product_code, source_id)).fetchone() is not None


def _claim_is_verified(db, code, source_id, claim):
    if not source_id or not _table_exists(db, "prodotto_fonti"):
        return False
    return db.execute("""
        SELECT 1 FROM prodotto_fonti
        WHERE prodotto_codice = ? AND fonte_id = ? AND affermazione = ?
          AND stato_verifica IN ('verificata','demo')
    """, (code, source_id, claim)).fetchone() is not None


def _product_assertions(db, code):
    if not _table_exists(db, "prodotto_fonti") or not _table_exists(db, "fonti"):
        return []
    return [dict(row) for row in db.execute("""
        SELECT f.id, f.url, f.titolo, f.ente, f.consultata_il, f.data_o_versione, f.tipo,
               pf.affermazione, pf.stato_verifica
        FROM prodotto_fonti pf JOIN fonti f ON f.id = pf.fonte_id
        WHERE pf.prodotto_codice = ? AND pf.stato_verifica IN ('verificata','demo')
        ORDER BY pf.affermazione, f.id
    """, (code,))]


def _active_ingredient_rows(db, code, product=None):
    if _table_exists(db, "prodotto_principi_attivi") and _table_exists(db, "principi_attivi"):
        rows = db.execute("""
            SELECT a.nome, pa.quantita_per_unita AS amount, pa.unita AS unit, pa.fonte_id
            FROM prodotto_principi_attivi pa
            JOIN principi_attivi a ON a.id = pa.principio_attivo_id
            WHERE pa.prodotto_codice = ?
            ORDER BY a.nome_normalizzato, a.nome
        """, (code,))
        result = []
        for row in rows:
            if ((product or {}).get("dataset_tipo") == "reale" and
                    not _claim_is_verified(db, code, row["fonte_id"], "composizione")):
                continue
            result.append({"name": row["nome"], "amount": row["amount"], "unit": row["unit"],
                           "source": _source_detail(db, row["fonte_id"])})
        return result
    legacy = (product or {}).get("principio_attivo")
    return ([{"name": legacy, "amount": (product or {}).get("dosaggio"), "unit": None, "source": None}]
            if legacy else [])


def _supplement_ingredient_rows(db, code, product=None):
    if not _table_exists(db, "prodotto_componenti_integratore") or not _table_exists(db, "componenti_integratore"):
        return []
    result = []
    for row in db.execute("""
            SELECT c.nome, c.tipo, pc.quantita_per_unita AS amount, pc.unita AS unit, pc.fonte_id
            FROM prodotto_componenti_integratore pc
            JOIN componenti_integratore c ON c.id = pc.componente_id
            WHERE pc.prodotto_codice = ?
            ORDER BY c.nome_normalizzato, c.nome
        """, (code,)):
        if ((product or {}).get("dataset_tipo") == "reale" and
                not _claim_is_verified(db, code, row["fonte_id"], "composizione")):
            continue
        result.append({"name": row["nome"], "amount": row["amount"], "unit": row["unit"],
                       "type": row["tipo"], "source": _source_detail(db, row["fonte_id"])})
    return result


def _product_alias_rows(db, code, product=None):
    if not _table_exists(db, "alias_prodotto"):
        return []
    result = []
    for row in db.execute("""
            SELECT alias, tipo, fonte_id FROM alias_prodotto
            WHERE prodotto_codice = ? ORDER BY alias COLLATE NOCASE, tipo
        """, (code,)):
        source = _source_detail(db, row["fonte_id"])
        if (product or {}).get("dataset_tipo") == "reale" and not source:
            continue
        result.append({"name": row["alias"], "type": row["tipo"], "source": source})
    return result


def _equivalent_rows(db, code):
    if not _table_exists(db, "relazioni_prodotti"):
        return []
    source_product = db.execute("SELECT * FROM prodotti WHERE codice = ?", (code,)).fetchone()
    source_type = dict(source_product).get("dataset_tipo", "demo") if source_product else "demo"
    rows = db.execute("""
        SELECT r.*, p.nome AS related_name
        FROM relazioni_prodotti r JOIN prodotti p ON p.codice = r.destinazione
        WHERE r.origine = ? AND r.tipo IN ('equivalente_demo','equivalente_documentato')
        ORDER BY p.nome COLLATE NOCASE, p.codice
    """, (code,))
    equivalents = []
    for row in rows:
        relation = dict(row)
        status = relation.get("stato_revisione")
        if status is None and relation["tipo"] == "equivalente_demo":
            status = "demo"  # Schema v3 compatibility during migration.
        related_product = db.execute("SELECT * FROM prodotti WHERE codice = ?", (relation["destinazione"],)).fetchone()
        if not related_product or not _real_product_is_searchable(db, dict(related_product)):
            continue
        if relation["tipo"] == "equivalente_demo" and status == "demo":
            if source_type == "reale" or dict(related_product).get("dataset_tipo", "demo") == "reale":
                continue
        elif relation["tipo"] == "equivalente_documentato" and status == "approvata":
            if (not relation.get("fonte_id") or not relation.get("revisore") or
                    not relation.get("revisionato_il") or not _source_detail(db, relation.get("fonte_id"))):
                continue
        else:
            continue
        equivalents.append({
            "product_code": relation["destinazione"],
            "name": relation["related_name"],
            "source": _source_detail(db, relation.get("fonte_id")) or {
                "label": relation.get("fonte") or "Relazione dimostrativa"
            },
            "review_status": status,
            "conditions": relation.get("condizioni"),
            "source_version": relation.get("versione_fonte"),
            "reviewer": relation.get("revisore"),
        })
    return equivalents


def _real_product_is_searchable(db, product):
    """Real catalogue entries need direct identity and market evidence before retrieval."""
    if product.get("dataset_tipo") != "reale":
        return True
    if product.get("stato_mercato") != "verificato" or not _table_exists(db, "prodotto_fonti"):
        return False
    claims = {
        row["affermazione"]
        for row in db.execute("""
            SELECT affermazione FROM prodotto_fonti
            WHERE prodotto_codice = ? AND stato_verifica = 'verificata'
        """, (product["codice"],))
    }
    return {"identita", "commercializzazione"}.issubset(claims)


def product_display(code, catalog=CATALOG):
    """Return sourced product facts and nullable pharmacy data for one exact code.

    Candidate or rejected relations never enter the display. Demo relations are
    kept visibly marked as demo; real equivalences require an explicit approval.
    """
    with closing(catalog_connection(catalog)) as db:
        row = db.execute("SELECT * FROM prodotti WHERE codice = ?", (code,)).fetchone()
        if not row:
            return None
        product = dict(row)
        if not _real_product_is_searchable(db, product):
            return None
        sources = _product_assertions(db, code)
        real = product.get("dataset_tipo") == "reale"
        bank_source_id = product.get("prezzo_banco_fonte_id")
        stock_source_id = product.get("quantita_fonte_id")
        reference_source_id = product.get("prezzo_riferimento_fonte_id")
        bank_price_source = (_source_detail(db, bank_source_id) if not real or
                             _claim_is_verified(db, code, bank_source_id, "prezzo_banco") else None)
        stock_source = (_source_detail(db, stock_source_id) if not real or
                        _claim_is_verified(db, code, stock_source_id, "scorte") else None)
        reference_price_source = (_source_detail(db, reference_source_id) if not real or
                                  _claim_is_verified(db, code, reference_source_id, "prezzo_riferimento") else None)
        if not real and product.get("dataset_tipo") is None:
            legacy_source = {"label": product.get("fonte") or "Catalogo dimostrativo", "kind": "demo"}
            bank_price_source = bank_price_source or legacy_source
            stock_source = stock_source or legacy_source
            reference_price_source = reference_price_source or legacy_source
        image_source = _source_detail(db, product.get("immagine_fonte_id"))
        image_verified = (not real or (image_source and _claim_is_verified(
            db, code, product.get("immagine_fonte_id"), "immagine")))
        aliases = _product_alias_rows(db, code, product)
        form_key = product_form_key(product["formato"])
        classification, classification_source = _product_classification(db, catalog, code) if real else (None, None)
        display = {
            "code": code,
            "name": product["nome"],
            "category": product["categoria"],
            "species_scope": product.get("specie_destinazione") or
                ("umana" if product.get("categoria") == "medicinale" else None),
            "form": product["formato"],
            "form_key": form_key,
            "form_label": FORM_NAMES[form_key][0] if form_key else None,
            "classification": classification,
            "classification_label": {"generico": "Generico", "marca": "Di marca"}.get(classification),
            "classification_source": classification_source,
            "strength": product.get("dosaggio") if not real or any(
                source["affermazione"] == "composizione" and source["stato_verifica"] == "verificata"
                for source in sources
            ) else None,
            "active_ingredients": _active_ingredient_rows(db, code, product),
            "supplement_ingredients": _supplement_ingredient_rows(db, code, product),
            "aliases": aliases,
            "equivalents": _equivalent_rows(db, code),
            "sources": sources,
            "provenance": sources,
            "review_status": product.get("stato_revisione", "dimostrativa"),
            "dataset_type": product.get("dataset_tipo", "demo"),
            "regulatory_status": product.get("stato_regolatorio", "non_verificato"),
            "market_status": product.get("stato_mercato", "dimostrativo"),
            "image": product.get("immagine") if image_verified else None,
            "image_source": image_source if image_verified else None,
        }
        commercial = {
            "bank_price_cents": product.get("prezzo_cent") if bank_price_source else None,
            "bank_price_source": bank_price_source,
            "reference_price_cents": product.get("prezzo_riferimento_cent") if reference_price_source else None,
            "reference_price_source": reference_price_source,
            "stock": product.get("quantita") if stock_source else None,
            "stock_source": stock_source,
            "checked_at": (product.get("quantita_data") if product.get("dataset_tipo") == "reale" and stock_source
                           else datetime.now(timezone.utc).isoformat(timespec="seconds")),
        }
        return {"display": display, "commercial": commercial}


def documented_variants(code, catalog=CATALOG, packages=None):
    """Load explicit same-formulation packages, never infer them from a brand."""
    path = packages if packages is not None else catalog.with_name(PACKAGES.name)
    try:
        groups = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []
    if not isinstance(groups, list):
        return []

    for group in groups:
        if not isinstance(group, dict):
            continue
        labels = group.get("packages")
        if not isinstance(labels, dict) or code not in labels or len(labels) < 2:
            continue
        with closing(catalog_connection(catalog)) as db:
            source_id = group.get("source_id")
            if not isinstance(source_id, str):
                continue
            source = _source_detail(db, source_id)
            if not _is_official_product_source(source):
                continue
            variants, signatures = [], set()
            for package_code, label in labels.items():
                if not isinstance(label, str) or not label.strip():
                    break
                record = db.execute("SELECT * FROM prodotti WHERE codice = ?", (package_code,)).fetchone()
                if not record or record["dataset_tipo"] != "reale":
                    break
                identity = db.execute("""
                    SELECT 1 FROM prodotto_fonti WHERE prodotto_codice = ? AND fonte_id = ?
                    AND affermazione = 'identita' AND stato_verifica = 'verificata'
                """, (package_code, source_id)).fetchone()
                detail = product_display(package_code, catalog=catalog) if identity else None
                if not detail:
                    break
                display = detail["display"]
                ingredients = tuple(sorted(
                    (normalize(item["name"]), item.get("amount") or "", item.get("unit") or "")
                    for key in ("active_ingredients", "supplement_ingredients") for item in display[key]
                ))
                if display["category"] in {"medicinale", "medicinale_veterinario"} and (
                    not ingredients or any(not amount or not unit for _, amount, unit in ingredients)
                ):
                    break
                signatures.add((display["category"], normalize(display["form"]), record["via"],
                                display["strength"], ingredients))
                variants.append({**detail, "code": package_code, "label": label.strip(), "source": source})
            if len(variants) == len(labels) and len(signatures) == 1:
                return variants
    return []


def symptom_product_matches(concept_ids, catalog=CATALOG, species_scope="umana"):
    """Return only source-backed, unreviewed label-indication matches.

    This is intentionally separate from product mentions and the normal
    product-relation filters: an explicit stable topic may expose a sourced
    candidate, but no candidate is treated as approved advice.
    """
    if species_scope not in {"umana", "cane", "gatto", "cane_gatto"}:
        return []
    matches = _concept_product_matches(concept_ids, SYMPTOM_CONCEPT_IDS, "indicazione_etichetta", catalog)
    filtered = []
    for match in matches:
        display = match.get("product_display", {})
        product_scope = display.get("species_scope")
        if product_scope is None and display.get("category") != "medicinale_veterinario":
            product_scope = "umana"
        if product_scope == species_scope or (
                product_scope == "cane_gatto" and species_scope in {"cane", "gatto"}):
            filtered.append(match)
    return filtered


def context_product_matches(concept_ids, catalog=CATALOG):
    """Look up explicit physiological needs separately from symptom coverage."""
    return _concept_product_matches(concept_ids, CONTEXT_CONCEPT_IDS, "contesto_ricerca", catalog)


def _concept_product_matches(concept_ids, allowed, relation_type, catalog):
    if isinstance(concept_ids, str):
        concept_ids = [concept_ids]
    requested = list(dict.fromkeys(
        concept_id for concept_id in (concept_ids or [])
        if isinstance(concept_id, str) and concept_id in allowed
    ))
    if not requested:
        return []

    with closing(catalog_connection(catalog)) as db:
        required_tables = {"concetti", "relazioni_concetto_prodotto", "fonti", "prodotti", "prodotto_fonti"}
        if not all(_table_exists(db, table) for table in required_tables):
            return []
        placeholders = ",".join("?" for _ in requested)
        rows = db.execute(f"""
            SELECT c.id AS concept_id, c.nome AS concept_name,
                   r.prodotto_codice AS product_code, r.tipo AS relation_type,
                   r.contesto AS context, r.benefici AS claim,
                   r.rischi AS risks, r.prerequisiti AS prerequisites,
                   r.esclusioni AS exclusions, r.fonte_id AS source_id,
                   r.versione_fonte AS source_version, r.stato_revisione AS review_status, c.tipo AS concept_type,
                   p.*
            FROM concetti c
            JOIN relazioni_concetto_prodotto r ON r.concetto_id = c.id
            JOIN prodotti p ON p.codice = r.prodotto_codice
            WHERE c.id IN ({placeholders})
              AND r.tipo = ?
              AND r.stato_revisione = 'candidata'
              AND r.fonte_id IS NOT NULL
            ORDER BY c.id, p.nome COLLATE NOCASE, p.codice
        """, (*requested, relation_type)).fetchall()

        matches = []
        for row in rows:
            source = _source_detail(db, row["source_id"])
            if not _is_official_product_source(source):
                continue
            # Schema v4 records this source assertion as `associazione_clinica`;
            # the relation's narrower `indicazione_etichetta` type remains the
            # authoritative filter. Require the associated product-source claim
            # itself to be verified, never merely a demo claim.
            if relation_type == "indicazione_etichetta":
                if not _indication_source_claim_is_verified(db, row["product_code"], row["source_id"]):
                    continue
            elif (row["concept_type"] != "bisogno" or row["categoria"] != "integratore_alimentare"
                  or not db.execute("""
                      SELECT 1 FROM prodotto_fonti WHERE prodotto_codice=? AND fonte_id=?
                        AND affermazione='identita' AND stato_verifica='verificata'
                  """, (row["product_code"], row["source_id"])).fetchone()):
                continue
            product_record = dict(row)
            if not _real_product_is_searchable(db, product_record):
                continue
            if not row["context"] or not row["claim"]:
                continue
            product_details = product_display(row["product_code"], catalog=catalog)
            if not product_details:
                continue
            matches.append({
                "concept_id": row["concept_id"],
                "concept_name": row["concept_name"],
                "product_code": row["product_code"],
                "product_display": product_details["display"],
                "commercial": product_details["commercial"],
                "relation_type": row["relation_type"],
                "review_status": row["review_status"],
                "claim": row["claim"],
                "context": row["context"],
                "risks": row["risks"],
                "prerequisites": row["prerequisites"],
                "exclusions": row["exclusions"],
                "source": source,
                "source_version": row["source_version"],
            })
    return matches


def reference_material(catalog=CATALOG, wiki=WIKI):
    with closing(catalog_connection(catalog)) as db:
        products = {}
        for row in db.execute("SELECT * FROM prodotti"):
            product = dict(row)
            if not _real_product_is_searchable(db, product):
                continue
            code = product["codice"]
            product["active_ingredients"] = _active_ingredient_rows(db, code, product)
            product["supplement_ingredients"] = _supplement_ingredient_rows(db, code, product)
            product["aliases"] = _product_alias_rows(db, code, product)
            products[code] = product

    pages = {}
    product_pages = set()
    for path in sorted(wiki.glob("*.md")):
        opening, metadata, body = path.read_text(encoding="utf-8").split("+++\n", 2)
        if opening:
            raise ValueError(f"Intestazione wiki non valida: {path.name}")
        page = tomllib.loads(metadata)
        if page["stato"] == "bozza":
            continue
        if page["stato"] not in {"demo", "pubblicata", "documentata"}:
            raise ValueError(f"Stato wiki non valido: {path.name}")
        if page["stato"] == "pubblicata" and not all(page.get(k) for k in ("fonte", "revisore", "versione")):
            raise ValueError(f"Fonte, revisore e versione richiesti: {path.name}")
        code = page.get("prodotto")
        if page["stato"] == "documentata" and not (code and page.get("fonte")):
            raise ValueError(f"Prodotto e fonte richiesti per la scheda documentata: {path.name}")
        if code and code not in products:
            continue
        if code:
            product_pages.add(code)
        pages[path.stem] = {**page, "testo": body.strip(), "scheda": path.stem, "catalogo": products.get(code)}

    for code, product in products.items():
        if code not in product_pages:
            pages[f"catalogo:{code}"] = {
                "titolo": product["nome"], "tipo": "prodotto", "stato": "catalogo",
                "fonte": product.get("fonte", "Catalogo locale"), "catalogo": product,
                "scheda": f"catalogo:{code}", "testo": "",
            }
    return products, pages


def product_aliases(products, pages):
    terms_by_code = {code: [] for code in products}
    seen_by_code = {code: set() for code in products}

    def add(code, term, basis, source):
        if not isinstance(term, str) or not term.strip():
            return
        key = normalize(term)
        if not key or key in seen_by_code[code]:
            return
        seen_by_code[code].add(key)
        terms_by_code[code].append({"term": term.strip(), "basis": basis, "source": source})

    generic = {"banco", "demo", "farmaco", "medicinale", "integratore", "prodotto", "generico",
               "compresse", "compressa", "capsule", "capsula", "granulato", "spray", "sciroppo",
               "bustine", "bustina", "gel", "crema", "collutorio", "gocce"}
    for code, product in products.items():
        catalog_source = {"kind": "catalog", "id": code, "label": product.get("nome", "Catalogo locale")}
        add(code, product.get("nome"), "product_name", catalog_source)
        add(code, code, "product_code", catalog_source)
        for alias in product.get("aliases", []):
            add(code, alias.get("name"), "catalog_alias", alias.get("source") or catalog_source)
        for ingredient in product.get("active_ingredients", []):
            source = ingredient.get("source")
            if product.get("dataset_tipo") != "reale" or source:
                add(code, ingredient.get("name"), "active_ingredient", source or catalog_source)
        # Supplement components remain a separate searchable basis from
        # medicinal active ingredients, with their own source metadata.
        for ingredient in product.get("supplement_ingredients", []):
            source = ingredient.get("source")
            if product.get("dataset_tipo") != "reale" or source:
                add(code, ingredient.get("name"), "supplement_ingredient", source or catalog_source)

    for page in pages.values():
        product = page.get("catalogo") or {}
        code = page.get("prodotto")
        # Only an explicitly product-bound demo sheet may contribute curated
        # terms to product recognition. Real products and generic/editorial
        # topic sheets never inherit product aliases from wiki prose.
        if (code in terms_by_code and page.get("stato") == "demo"
                and product.get("dataset_tipo", "demo") != "reale"):
            product_words = set(normalize(product.get("nome", "")).split()) - generic
            source = {"kind": "wiki", "id": page["scheda"],
                      "label": f"wiki/schede/{page['scheda']}.md",
                      "version": str(page.get("versione", "demo"))}
            for term in page.get("termini", []):
                words = normalize(term).split()
                # A linked demo page may contribute a specific phrase such as
                # "mascara waterproof", but dosage forms and unrelated
                # category terms are not product identities.
                if (set(words) - generic).intersection(product_words):
                    add(code, term, "demo_wiki_alias", source)
    result = []
    for code, details in terms_by_code.items():
        result.append({"codice": code, "nome": products[code]["nome"],
                       "categoria": products[code]["categoria"],
                       "specie_destinazione": products[code].get("specie_destinazione") or
                           ("umana" if products[code]["categoria"] == "medicinale" else None),
                       "termini": [item["term"] for item in details],
                       "termini_dettaglio": details})
    return result


def stock_for(codes, catalog=CATALOG, confirmed=None, cosmetic_complement=False, complement_eligible=False,
              *, include_unknown_complements=False):
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(catalog_connection(catalog)) as db:
        rows = []
        for code in dict.fromkeys(codes):
            product = db.execute("SELECT * FROM prodotti WHERE codice = ?", (code,)).fetchone()
            if not product:
                continue
            product = dict(product)
            if not _real_product_is_searchable(db, product):
                continue
            current_quantity = product.get("quantita")
            current_stock_source = _source_detail(db, product.get("quantita_fonte_id"))
            if product.get("dataset_tipo") is None and current_quantity is not None:
                current_stock_source = {"label": product.get("fonte") or "Catalogo dimostrativo", "kind": "demo"}
            if (product.get("dataset_tipo") == "reale" and not _claim_is_verified(
                    db, code, product.get("quantita_fonte_id"), "scorte")):
                current_quantity = None
                current_stock_source = None
            equivalents, complements = [], []
            product_columns = _table_columns(db, "prodotti")
            quantity_source_column = "p.quantita_fonte_id" if "quantita_fonte_id" in product_columns else "NULL"
            quantity_date_column = "p.quantita_data" if "quantita_data" in product_columns else "NULL"
            dataset_column = "p.dataset_tipo" if "dataset_tipo" in product_columns else "NULL"
            price_source_column = "p.prezzo_banco_fonte_id" if "prezzo_banco_fonte_id" in product_columns else "NULL"
            relations = db.execute("""
                SELECT r.*, p.codice AS product_code, p.nome,
                       p.quantita AS quantity, {quantity_source_column} AS quantity_source_id,
                       {quantity_date_column} AS quantity_checked_at, p.categoria AS related_category,
                       {dataset_column} AS related_dataset_type, p.prezzo_cent AS price_cents,
                       {price_source_column} AS price_source_id
                FROM relazioni_prodotti r JOIN prodotti p ON p.codice = r.destinazione
                WHERE r.origine = ?
                ORDER BY p.codice
            """.format(quantity_source_column=quantity_source_column,
                       quantity_date_column=quantity_date_column, dataset_column=dataset_column,
                       price_source_column=price_source_column), (code,))
            for relation in relations:
                relation = dict(relation)
                related = db.execute("SELECT * FROM prodotti WHERE codice = ?", (relation["product_code"],)).fetchone()
                if not related or not _real_product_is_searchable(db, dict(related)):
                    continue
                related_product = dict(related)
                quantity = relation.get("quantity")
                quantity_source = _source_detail(db, relation.get("quantity_source_id"))
                if related_product.get("dataset_tipo") is None and quantity is not None:
                    quantity_source = {"label": related_product.get("fonte") or "Catalogo dimostrativo", "kind": "demo"}
                if (related_product.get("dataset_tipo") == "reale" and not _claim_is_verified(
                        db, relation["product_code"], relation.get("quantity_source_id"), "scorte")):
                    quantity = None
                    quantity_source = None
                price_source = _source_detail(db, relation.get("price_source_id"))
                if related_product.get("dataset_tipo") is None and relation.get("price_cents") is not None:
                    price_source = {"label": related_product.get("fonte") or "Catalogo dimostrativo", "kind": "demo"}
                if (related_product.get("dataset_tipo") == "reale" and not _claim_is_verified(
                        db, relation["product_code"], relation.get("price_source_id"), "prezzo_banco")):
                    price_source = None
                status = relation.get("stato_revisione")
                if status is None and relation["tipo"] in {"equivalente_demo", "complemento_cosmetico"}:
                    status = "demo"  # Existing v3 rows are fixture-only until v4 migration.
                demo_pair = product.get("dataset_tipo") != "reale" and relation.get("related_dataset_type") != "reale"
                approved = (status == "approvata" and relation.get("fonte_id") and relation.get("revisore")
                            and relation.get("revisionato_il") and _source_detail(db, relation.get("fonte_id")))
                demo_relation = status == "demo" and demo_pair
                relation_view = {
                    "product_code": relation["product_code"], "name": relation["nome"],
                    "quantity": quantity,
                    "quantity_source": quantity_source,
                    "quantity_checked_at": relation.get("quantity_checked_at"),
                    "type": relation["tipo"], "source": _source_detail(db, relation.get("fonte_id")) or
                    {"label": relation.get("fonte") or "Relazione dimostrativa"},
                    "tipo": relation["tipo"],
                    "source_version": relation.get("versione_fonte"),
                    "review_status": status,
                    "reviewer": relation.get("revisore"),
                    "reviewed_at": relation.get("revisionato_il"),
                    "benefits": relation.get("benefici"), "risks": relation.get("rischi"),
                    "prerequisites": relation.get("prerequisiti"),
                    "conditions": relation.get("condizioni"), "exclusions": relation.get("esclusioni"),
                    "price_cents": relation.get("price_cents") if price_source else None,
                    "bank_price_cents": relation.get("price_cents") if price_source else None,
                    "bank_price_source": price_source,
                }
                if (current_quantity == 0 and relation["tipo"] in
                        {"equivalente_demo", "equivalente_documentato"} and quantity is not None
                        and quantity > 0 and (approved or demo_relation)):
                    equivalents.append(relation_view)
                is_demo_cosmetic = (relation["tipo"] == "complemento_cosmetico" and demo_relation
                                    and product.get("categoria") == relation.get("related_category") == "Cosmetico")
                is_approved_complement = (relation["tipo"] in {"complemento_revisionato", "complemento_clinico"}
                                          and approved)
                if (quantity is not None and quantity > 0 and
                        ((code == confirmed and cosmetic_complement and is_demo_cosmetic) or
                         (complement_eligible and is_approved_complement))):
                    complements.append(relation_view)
                elif quantity is None and include_unknown_complements and complement_eligible and is_approved_complement:
                    complements.append(relation_view)
            complements = complements[:3]
            rows.append({"product_code": code, "quantity": current_quantity,
                         "source": current_stock_source,
                         "quantity_source": current_stock_source,
                         "checked_at": product.get("quantita_data") or
                         (checked_at if product.get("dataset_tipo") != "reale" else None),
                         "equivalents": equivalents, "complements": complements})
        return rows


def search(query, catalog=CATALOG, wiki=WIKI):
    """Return reference material for an ephemeral text fragment."""
    if len(query) > 4096:
        raise ValueError("Usa un frammento di conversazione fino a 4096 caratteri.")
    phrase = normalize(query)
    if not phrase:
        return []

    products, pages = reference_material(catalog, wiki)

    with closing(sqlite3.connect(":memory:")) as index:
        index.execute("CREATE VIRTUAL TABLE ricerca USING fts5(id UNINDEXED, titolo, termini, testo)")
        aliases = {}
        for key, page in pages.items():
            product = page.get("catalogo") or {}
            catalog_terms = [product[key] for key in ("codice", "nome", "categoria", "formato") if product.get(key)]
            catalog_terms.extend(alias["name"] for alias in product.get("aliases", []))
            catalog_terms.extend(item["name"] for item in product.get("active_ingredients", []))
            catalog_terms.extend(item["name"] for item in product.get("supplement_ingredients", []))
            terms = [page["titolo"], *page.get("termini", []), *catalog_terms]
            aliases[key] = [normalize(term) for term in terms if term]
            index.execute("INSERT INTO ricerca VALUES (?, ?, ?, ?)", (
                key, page["titolo"], " ".join(aliases[key]), page["testo"],
            ))
        query_fts = " OR ".join(f'"{word}"' for word in dict.fromkeys(phrase.split()))
        rows = index.execute("SELECT id, bm25(ricerca, 0, 4, 3, 1) FROM ricerca WHERE ricerca MATCH ?", (query_fts,))
        matches = []
        for key, rank in rows:
            found = [term for term in aliases[key] if term and f" {term} " in f" {phrase} "]
            priority = max((len(term.split()) for term in found), default=0)
            matches.append((-priority, rank, key, found))
    results = []
    for _, _, key, found in sorted(matches)[:10]:
        page = pages[key]
        # Wiki links are fixture navigation only. Real product associations
        # must come from an explicitly approved, source-backed DB relation.
        related = [products[code] for code in page.get("collegamenti", [])
                   if code in products and products[code].get("dataset_tipo", "demo") != "reale"]
        results.append({**page, "termini_rilevati": found, "prodotti_collegati": related})
    return results


if __name__ == "__main__":
    try:
        print(json.dumps(search(sys.stdin.read(4097)), ensure_ascii=False, indent=2))
    except (ValueError, OSError, sqlite3.Error) as error:
        sys.exit(str(error))
