"""Stato della vendita al banco: bisogno → domande → prodotto → complemento → offerta.

Lo stato è derivato, in memoria, dalla sessione già calcolata in desk.py
(evidenze, destinatario, risultati, prodotto confermato, carrello) più poche
scelte esplicite del farmacista (salta, gestito, decisione sul complemento).
Non duplica il riconoscimento: legge le evidenze di conversation.py.

Regole:
- un segnale d'allarme ferma le proposte finché il farmacista non preme «gestito»;
- il complemento si apre solo con un prodotto confermato dal farmacista;
- un solo complemento: il più prioritario, approvato e disponibile;
- le offerte riguardano solo prodotti già entrati nella conversazione.
"""

import json
import re
from functools import lru_cache
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from backend.conversation import _phrase_pattern, _symptom_excluded
from backend.protocolli import protocol_for
from backend import semantica

ROOT = Path(__file__).resolve().parents[1]
LEXICON = ROOT / "database" / "lessico-concetti.json"
STEPS = (
    ("bisogno", "Bisogno"),
    ("inquadramento", "Domande"),
    ("proposta", "Prodotto"),
    ("complemento", "Complemento"),
    ("offerta", "Offerta"),
)
FEEDBACK_EVENTS = {"mostrato", "proposto", "accettato", "rifiutato", "non_pertinente", "errore_riconoscimento"}
ESSENTIAL_FILTERS = {"eta", "terapie_patologie", "gravidanza"}
_ANSWERS = {
    "eta": None,  # answered by the declared recipient age
    "durata": re.compile(r"\bda\s+(?:ieri|stamattina|stanotte|stasera|oggi|(?:\d+|un|una|due|tre|quattro|cinque|sei|"
                         r"sette|qualche|pochi|alcuni)\s+(?:giorn\w*|settiman\w*|mes\w*|or\w*))\b|\bda\s+ieri\b", re.I),
    "terapie_patologie": re.compile(r"\b(?:non\s+prend\w+\s+(?:altri\s+)?(?:farmaci|medicin\w+|niente|nulla)|"
                                    r"nessun\s+(?:altro\s+)?farmaco|prend\w+\s+(?:gi[aà]\s+)?(?:il|la|lo|l'|un|una)\s+\w+|"
                                    r"pressione\s+alta|iperteso|ipertesa|diabet\w+|tiroide)\b", re.I),
    "gravidanza": re.compile(r"\b(?:incinta|gravidanza|allatt\w+|non\s+sono\s+incinta)\b", re.I),
}


def _lexicon(path=LEXICON):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _red_flag_patterns(path=LEXICON):
    flags = []
    for key, entry in (_lexicon(path).get("segnali_allarme") or {}).items():
        if key.startswith("_") or not isinstance(entry, dict):
            continue
        terms = [t for t in entry.get("termini", []) if isinstance(t, str) and t.strip()]
        if terms:
            pattern = re.compile(r"\b(?:" + "|".join(_phrase_pattern(t) for t in sorted(terms, key=len, reverse=True))
                                 + r")\b", re.IGNORECASE)
            flags.append((key, entry.get("testo") or key, pattern))
    return flags


_FLAGS = _red_flag_patterns()


def detect_red_flags(text, flags=None):
    """Red flags said in the conversation, honouring negation ("non ho dolore al petto")."""
    found = {}
    for clause in re.split(r"[.!?;\n]+", text or ""):
        for key, label, pattern in (flags if flags is not None else _FLAGS):
            match = pattern.search(clause)
            if match and not _symptom_excluded(clause, match.span()):
                found[key] = {"id": key, "text": label, "matched": match.group(0)}
    return list(found.values())


def _fallback_questions(concept_ids, path=LEXICON):
    concepts = _lexicon(path).get("concetti") or {}
    questions = []
    for concept_id in concept_ids:
        text = (concepts.get(concept_id) or {}).get("domanda")
        if text:
            questions.append({"text": text, "filter": None, "concept_id": concept_id, "source": "lessico (bozza)"})
    return questions


def _answered(question, text, recipient, profile=None):
    key = question.get("filter")
    source = (profile or {}).get("source") or {}
    if key == "eta":
        return ((recipient or {}).get("declared_fields", {}).get("age") is not None
                or source.get("age_band") in ("dichiarato", "manuale") or (profile or {}).get("kind") == "animale")
    if key == "gravidanza" and (source.get("states") in ("dichiarato", "manuale")
                                or (profile or {}).get("gender") == "uomo" and source.get("gender") != "dedotto"):
        return True
    pattern = _ANSWERS.get(key)
    return bool(pattern and pattern.search(text or ""))


def active_concepts(evidence):
    """Concept ids of active topic evidence, most recent last."""
    ordered = sorted((item for item in evidence or [] if item.get("kind") == "topic" and item.get("concept_id")
                      and item.get("state") in {"active", "provisional"}), key=lambda item: item["span"]["end"])
    return list(dict.fromkeys(item["concept_id"] for item in ordered))


def population_flags(concepts, profile):
    """Red flags that depend on who the product is for (declared or manual fields only)."""
    from backend import destinatario
    who = destinatario.filtering(profile)
    flags = []
    concepts = set(concepts)
    if "cistite" in concepts and (who["gender"] == "uomo" or "gravidanza" in who["states"]
                                  or who["age_band"] in ("neonato", "bambino")):
        flags.append({"id": "pop_cistite", "text": "Cistite nell'uomo, in gravidanza o nel bambino: serve il medico",
                      "matched": "destinatario"})
    if "febbre" in concepts and (who["age_band"] == "neonato" or (who["age_months"] is not None
                                                                 and who["age_months"] < 3)):
        flags.append({"id": "pop_febbre_lattante", "text": "Febbre in un lattante: valutare subito il pediatra",
                      "matched": "destinatario"})
    if concepts & {"micosi-vaginale"} and who["age_band"] in ("neonato", "bambino"):
        flags.append({"id": "pop_intimo_bambina", "text": "Disturbo intimo in una bambina: serve il pediatra",
                      "matched": "destinatario"})
    return flags


def pick_complement(catalog, concept_ids, confirmed_code, cart_codes, approved_supplements=()):
    """The single complement to show after confirmation, or None."""
    candidates = []
    try:
        db = sqlite3.connect(Path(catalog).resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        db = None
    if db is not None:
        with closing(db):
            db.row_factory = sqlite3.Row
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='complementi_banco'").fetchone():
                marks = ",".join("?" for _ in concept_ids) or "''"
                rows = db.execute(f"""
                    SELECT c.*, p.nome AS nome_prodotto, p.quantita AS giacenza, p.prezzo_cent
                    FROM complementi_banco c LEFT JOIN prodotti p ON p.codice = c.prodotto_complemento
                    WHERE c.stato_revisione = 'approvata'
                      AND (c.concetto_id IN ({marks}) OR c.prodotto_origine = ?)
                    ORDER BY c.priorita, c.id""", (*concept_ids, confirmed_code)).fetchall()
                for row in rows:
                    code = row["prodotto_complemento"]
                    if code and (code in cart_codes or code == confirmed_code):
                        continue
                    if code and row["giacenza"] is not None and row["giacenza"] <= 0:
                        continue
                    candidates.append({
                        "id": row["id"], "code": code, "name": row["nome_prodotto"] or row["categoria_scaffale"],
                        "shelf": row["categoria_scaffale"], "kind": row["tipo"], "reason": row["motivo"],
                        "exclusions": row["esclusioni"], "reviewer": row["revisore"],
                        "price_cents": row["prezzo_cent"], "stock": row["giacenza"], "origin": "complementi_banco",
                        "reviewed": True, "level_label": "Complemento approvato",
                    })
    for row in approved_supplements:
        code = row.get("code")
        if not code or code in cart_codes or code == confirmed_code:
            continue
        stock = (row.get("commercial") or {}).get("stock")
        if stock is not None and stock <= 0:
            continue
        link = next(iter(row.get("references") or []), {})
        candidates.append({
            "id": None, "code": code, "name": row["display"]["name"], "shelf": None, "kind": "integratore",
            "reason": link.get("reason") or link.get("claim") or row.get("relevance") or "Abbinamento revisionato",
            "exclusions": link.get("exclusions"), "reviewer": link.get("reviewer"),
            "price_cents": (row.get("commercial") or {}).get("bank_price_cents"), "stock": stock,
            "origin": "relazioni_prodotti", "reviewed": True, "level_label": "Abbinamento approvato",
        })
    return candidates[0] if candidates else None


@lru_cache(maxsize=64)
def _semantic_hint(text):
    hint = semantica.suggest_concept(text)
    if not hint:
        return None
    entry = (_lexicon().get("concetti") or {}).get(hint["concept_id"]) or {}
    return {**hint, "name": entry.get("nome") or hint["concept_id"].replace("-", " ")}


def sales_view(state, catalog, choices):
    """Build the visible sales state. `choices` holds the pharmacist's explicit decisions."""
    text = (state.get("transcript") or {}).get("testo", "")
    evidence = state.get("evidence") or []
    results = state.get("desk_results") or {}
    product = state.get("product") or {}
    recipient = state.get("recipient") or {}
    concepts = list(dict.fromkeys([*active_concepts(evidence), *choices.get("manual_concepts", [])]))
    confirmed = product.get("confirmed_code")
    cart_codes = {item.get("code") for item in (state.get("cart") or {}).get("items", [])}

    flags = [flag for flag in detect_red_flags(text) + population_flags(concepts, state.get("recipient_profile"))
             if flag["id"] not in choices.get("flags_handled", set())]
    protocols = protocol_for(concepts, catalog)
    questions, advice, follow_up, protocol_flags = [], [], None, []
    for concept_id in concepts:
        protocol = protocols.get(concept_id)
        if protocol:
            questions += [{**q, "concept_id": concept_id, "source": f"protocollo v{protocol['version']}"}
                          for q in protocol["questions"]]
            advice += protocol["advice"]
            protocol_flags += protocol["red_flags"]
            follow_up = follow_up or protocol["follow_up"]
    covered = {q["concept_id"] for q in questions}
    questions += _fallback_questions([c for c in concepts if c not in covered])
    for question in questions:
        question["answered"] = _answered(question, text, recipient, state.get("recipient_profile"))
    open_questions = [q for q in questions if not q["answered"]][:3]
    answered = [q for q in questions if q["answered"]][:3]

    complement = None
    decision = choices.get("complement_decision")
    if confirmed and not flags:
        complement = pick_complement(catalog, concepts, confirmed, cart_codes,
                                     [row for row in results.get("supplements", [])
                                      if any(link.get("review_status") == "approvata"
                                             for link in row.get("references", []))])
        linked_for_confirmed = linked_supplements(state, catalog, [confirmed])
        top = next((item for item in linked_for_confirmed if item["level"] <= 2), None)
        if complement is None and top is None and linked_for_confirmed:
            # No approved complement: still open the step with the best candidate, clearly labelled.
            top = linked_for_confirmed[0]
        # An approved pairing with the confirmed drug itself beats a generic complement for the need.
        if top and (complement is None or (top["level"] == 1 and complement.get("code") != top["code"])):
            if top:
                source = (top["linked_to"] or top["for_symptoms"])[0]
                complement = {
                    "id": top["complement_id"], "code": top["code"], "name": top["name"], "shelf": None,
                    "kind": top["kind"], "reason": source["motivo"], "exclusions": None,
                    "origin_kind": top["origin"], "for_symptoms": top["for_symptoms"],
                    "reviewer": None, "price_cents": top["price_cents"], "stock": top["stock"],
                    "origin": "linked_supplements", "level": top["level"], "level_label": top["level_label"],
                    "reviewed": top["level"] < 3,
                }

    skipped = choices.get("skipped", set())
    rows = results.get("rows") or []
    if flags:
        step, reason = "allarme", "Segnale d'allarme: valutare l'invio al medico prima di proporre."
    elif not concepts and not rows and not confirmed:
        step, reason = "bisogno", "In ascolto del bisogno del cliente."
    elif (concepts and not confirmed and "inquadramento" not in skipped
          and any(q.get("filter") in ESSENTIAL_FILTERS for q in open_questions)):
        step, reason = "inquadramento", "Mancano risposte che possono escludere delle opzioni."
    elif not confirmed:
        step, reason = "proposta", ("Opzioni pronte: confermare quella scelta." if rows
                                    else "Nessuna opzione documentata per questo bisogno.")
    elif complement and decision is None and "complemento" not in skipped:
        step, reason = "complemento", "Prodotto confermato: un complemento approvato è disponibile."
    else:
        step, reason = "offerta", "Prodotto confermato: chiusura e offerte."

    hint = None
    if step == "bisogno" and len(text.strip()) >= 12 and semantica.settings()["attiva"]:
        hint = _semantic_hint(text.strip()[-300:])

    order = [key for key, _ in STEPS]
    current = order.index(step) if step in order else 0
    return {
        "step": step, "reason": reason,
        "steps": [{"key": key, "label": label,
                   "state": ("blocked" if step == "allarme" else "done" if index < current
                             else "current" if index == current else "todo")}
                  for index, (key, label) in enumerate(STEPS)],
        "concepts": concepts,
        "questions": open_questions, "answered": answered,
        "red_flags": flags, "protocol_red_flags": protocol_flags[:4],
        "advice": advice[:3], "follow_up": follow_up,
        "complement": complement, "complement_decision": decision,
        "complement_empty": bool(confirmed and not flags and complement is None),
        "excluded": results.get("excluded", []),
        "proposals_blocked": bool(flags),
        "semantic_hint": hint,
    }


def record_feedback(catalog, event, *, concept_id=None, product_code=None, complement_id=None, version=None,
                    origin=None):
    """Write one anonymous event. Silently skipped when the table is missing."""
    if event not in FEEDBACK_EVENTS:
        raise ValueError("Evento di feedback non valido.")
    try:
        with closing(sqlite3.connect(catalog)) as db, db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='feedback_banco'").fetchone():
                return False
            if concept_id and not db.execute("SELECT 1 FROM concetti WHERE id=?", (concept_id,)).fetchone():
                concept_id = None
            if product_code and not db.execute("SELECT 1 FROM prodotti WHERE codice=?", (product_code,)).fetchone():
                product_code = None
            columns = {row[1] for row in db.execute("PRAGMA table_info(feedback_banco)")}
            if "origine" in columns:
                db.execute("""INSERT INTO feedback_banco (creato_il, concetto_id, prodotto_codice, complemento_id,
                                  evento, protocollo_versione, origine) VALUES (?,?,?,?,?,?,?)""",
                           (datetime.now(timezone.utc).isoformat(timespec="seconds"), concept_id, product_code,
                            complement_id, event, version, origin if origin in ("farmaco", "sintomo") else None))
            else:
                db.execute("""INSERT INTO feedback_banco (creato_il, concetto_id, prodotto_codice, complemento_id,
                                  evento, protocollo_versione) VALUES (?,?,?,?,?,?)""",
                           (datetime.now(timezone.utc).isoformat(timespec="seconds"), concept_id, product_code,
                            complement_id, event, version))
        return True
    except sqlite3.Error:
        return False


def weekly_analysis(catalog, days=7):
    """Aggregated counts only, for the /analisi page."""
    result = {"giorni": days, "per_bisogno": [], "imbuto": [], "complemento_per_settimana": [], "non_pertinenti": []}
    try:
        db = sqlite3.connect(Path(catalog).resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        return result
    with closing(db):
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='feedback_banco'").fetchone():
            return result
        since = f"-{int(days)} days"
        result["per_bisogno"] = [
            {"concetto": name or cid, "eventi": n} for cid, name, n in db.execute("""
                SELECT f.concetto_id, c.nome, count(*) FROM feedback_banco f LEFT JOIN concetti c ON c.id = f.concetto_id
                WHERE f.concetto_id IS NOT NULL AND f.evento = 'mostrato' AND f.complemento_id IS NULL
                  AND f.prodotto_codice IS NULL AND f.creato_il >= datetime('now', ?)
                GROUP BY 1 ORDER BY 3 DESC LIMIT 12""", (since,))]

        def count(where):
            return db.execute(f"SELECT count(*) FROM feedback_banco WHERE creato_il >= datetime('now', ?) AND {where}",
                              (since,)).fetchone()[0]
        result["imbuto"] = [
            {"passo": "Bisogno riconosciuto", "n": count("evento='mostrato' AND complemento_id IS NULL AND prodotto_codice IS NULL")},
            {"passo": "Prodotto proposto", "n": count("evento='proposto'")},
            {"passo": "Prodotto confermato", "n": count("evento='accettato' AND complemento_id IS NULL")},
            {"passo": "Complemento accettato", "n": count("evento='accettato' AND complemento_id IS NOT NULL")},
        ]
        result["complemento_per_settimana"] = [
            {"settimana": week, "mostrati": shown, "accettati": accepted} for week, shown, accepted in db.execute("""
                SELECT strftime('%Y-%W', creato_il), sum(evento='mostrato'), sum(evento='accettato')
                FROM feedback_banco WHERE complemento_id IS NOT NULL
                GROUP BY 1 ORDER BY 1 DESC LIMIT 12""")][::-1]
        result["non_pertinenti"] = [
            {"concetto": name or cid or "(nessuno)", "n": n} for cid, name, n in db.execute("""
                SELECT f.concetto_id, c.nome, count(*) FROM feedback_banco f LEFT JOIN concetti c ON c.id = f.concetto_id
                WHERE f.evento IN ('non_pertinente','errore_riconoscimento') AND f.creato_il >= datetime('now', ?)
                GROUP BY 1 ORDER BY 3 DESC LIMIT 10""", (since,))]
    return result


SUPPLEMENT_CATEGORIES = ("integratore_alimentare", "Integratore")
LINK_LEVELS = {
    1: "Abbinamento approvato",
    2: "Complemento approvato per il bisogno",
    3: "Stesso bisogno · non revisionato",
}


def _excluded_by_text(exclusions, text):
    """True when a declared exclusion term (e.g. «gravidanza») was said at the desk."""
    if not exclusions or not text:
        return False
    spoken = text.lower()
    for term in re.split(r"[,;/\n]|\be\b|\bo\b", exclusions.lower()):
        term = re.sub(r"^(?:in|con|se|per|durante|chi ha|chi è|soggetti con)\s+", "", term.strip(" .()"))
        if len(term) >= 5 and re.search(r"\b" + re.escape(term) + r"\b", spoken):
            return True
    return False


def linked_supplements(state, catalog, drug_codes=None):
    """Supplements linked to the drugs on screen, best documented level first.

    Level 1: approved pairing with that drug (relazioni_prodotti complement, or
    complementi_banco with prodotto_origine). Level 2: approved complementi_banco
    for one of the drug's needs. Level 3: a supplement linked with a source to the
    same need (candidate, shown as «non revisionato»). Nothing without a record.
    Items in the cart, out of stock or excluded by what was said are left out.
    """
    results = state.get("desk_results") or {}
    if drug_codes is None:
        drug_codes = []
        for row in results.get("rows") or []:
            if row.get("code"):
                drug_codes.append(row["code"])
        confirmed = (state.get("product") or {}).get("confirmed_code")
        if confirmed and confirmed not in drug_codes:
            drug_codes.append(confirmed)
    drug_codes = list(dict.fromkeys(code for code in drug_codes if isinstance(code, str) and code))
    cart_codes = {item.get("code") for item in (state.get("cart") or {}).get("items", [])}
    text = (state.get("transcript") or {}).get("testo", "")
    active = set(active_concepts(state.get("evidence") or []))
    # Needs said in the conversation (and chosen by hand): their supplements count too,
    # even when the chosen drug is not linked to them.
    said = list(dict.fromkeys([*active_concepts(state.get("evidence") or []),
                               *((state.get("vendita") or {}).get("concepts") or []),
                               *(state.get("extra_concepts") or [])]))
    if not drug_codes and not said:
        return []
    try:
        db = sqlite3.connect(Path(catalog).resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    found = {}
    db_tables = {}
    from backend import destinatario, knowledge
    who = destinatario.filtering(state.get("recipient_profile"))
    population_cache = {}

    def unsuitable(code):
        """Population rows: contraindicated, or a formula dedicated to someone else (e.g. pregnancy)."""
        if code not in population_cache:
            rows = []
            if db_tables.get("prodotto_popolazione"):
                rows = [{"population": r[0], "age_min_months": r[1], "age_max_months": r[2], "outcome": r[3],
                         "note": r[4]} for r in db.execute(
                    """SELECT popolazione, eta_min_mesi, eta_max_mesi, esito, nota FROM prodotto_popolazione
                       WHERE prodotto_codice = ? AND stato_revisione != 'respinta'""", (code,))]
            verdict = knowledge.admissibility({"populations": rows, "dispensing": "non_farmaco"}, None, who)
            dedicated = {row["population"] for row in rows if row["outcome"] == "formulazione_dedicata"}
            other_life_stage = dedicated & {"gravidanza", "allattamento"} and not dedicated & set(who["states"])
            other_gender = who["gender"] and dedicated & {"donna", "uomo"} and who["gender"] not in dedicated
            sconsigliato = any(label.startswith("sconsigliato") for label in verdict["labels"])
            population_cache[code] = (not verdict["allowed"] or bool(other_life_stage) or bool(other_gender)
                                      or sconsigliato)
        return population_cache[code]

    def add(code, drug, level, reason, exclusions, *, name=None, kind=None, price=None, stock=None, link_id=None,
            symptom=None):
        if not code or code in cart_codes or code in drug_codes:
            return
        if stock is not None and stock <= 0:
            return
        if _excluded_by_text(exclusions, text):
            return
        if unsuitable(code):
            return
        item = found.setdefault(code, {
            "code": code, "name": name or code, "kind": kind, "price_cents": price, "stock": stock,
            "level": level, "level_label": LINK_LEVELS[level], "reviewed": level < 3,
            "complement_id": link_id, "linked_to": [], "for_symptoms": [],
        })
        if level < item["level"]:
            item.update(level=level, level_label=LINK_LEVELS[level], reviewed=level < 3, complement_id=link_id)
        if symptom is not None:
            concept_id, concept_name = symptom
            current = next((entry for entry in item["for_symptoms"] if entry["concetto_id"] == concept_id), None)
            if current is None or level < current["livello"]:
                item["for_symptoms"] = [entry for entry in item["for_symptoms"] if entry["concetto_id"] != concept_id]
                item["for_symptoms"].append({"concetto_id": concept_id, "nome": concept_name, "livello": level,
                                             "motivo": reason or LINK_LEVELS[level]})
            return
        if not any(link["code_farmaco"] == drug and link["livello"] <= level for link in item["linked_to"]):
            item["linked_to"] = [link for link in item["linked_to"] if link["code_farmaco"] != drug]
            item["linked_to"].append({"code_farmaco": drug, "livello": level, "motivo": reason or LINK_LEVELS[level]})

    try:
        with closing(db):
            db.row_factory = sqlite3.Row
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            db_tables["prodotto_popolazione"] = "prodotto_popolazione" in tables
            product_columns = "p.nome, p.categoria, p.prezzo_cent, p.quantita"
            for drug in drug_codes:
                if "relazioni_prodotti" in tables:
                    for row in db.execute(f"""
                            SELECT r.destinazione AS code, r.motivo, r.esclusioni, {product_columns}
                            FROM relazioni_prodotti r JOIN prodotti p ON p.codice = r.destinazione
                            WHERE r.origine = ? AND r.stato_revisione = 'approvata'
                              AND r.tipo IN ('complemento_revisionato','complemento_clinico','complemento_cosmetico')
                            ORDER BY r.destinazione""", (drug,)):
                        add(row["code"], drug, 1, row["motivo"], row["esclusioni"], name=row["nome"],
                            kind=row["categoria"], price=row["prezzo_cent"], stock=row["quantita"])
                drug_concepts = []
                if "relazioni_concetto_prodotto" in tables:
                    drug_concepts = [row[0] for row in db.execute("""
                        SELECT DISTINCT concetto_id FROM relazioni_concetto_prodotto
                        WHERE prodotto_codice = ? AND stato_revisione IN ('approvata','candidata')
                        ORDER BY concetto_id""", (drug,))]
                    if active and set(drug_concepts) & active:
                        drug_concepts = [concept for concept in drug_concepts if concept in active]
                if "complementi_banco" in tables:
                    marks = ",".join("?" for _ in drug_concepts) or "''"
                    for row in db.execute(f"""
                            SELECT c.id, c.prodotto_complemento AS code, c.prodotto_origine, c.motivo, c.esclusioni,
                                   {product_columns}
                            FROM complementi_banco c JOIN prodotti p ON p.codice = c.prodotto_complemento
                            WHERE c.stato_revisione = 'approvata'
                              AND (c.prodotto_origine = ? OR (c.prodotto_origine IS NULL AND c.concetto_id IN ({marks})))
                            ORDER BY c.priorita, c.id""", (drug, *drug_concepts)):
                        level = 1 if row["prodotto_origine"] == drug else 2
                        add(row["code"], drug, level, row["motivo"], row["esclusioni"], name=row["nome"],
                            kind=row["categoria"], price=row["prezzo_cent"], stock=row["quantita"], link_id=row["id"])
                    # Candidate complements for the drug's needs: shown as level 3, «non revisionato».
                    for row in db.execute(f"""
                            SELECT c.id, c.prodotto_complemento AS code, c.motivo, c.esclusioni, {product_columns}
                            FROM complementi_banco c JOIN prodotti p ON p.codice = c.prodotto_complemento
                            WHERE c.stato_revisione = 'candidata'
                              AND (c.prodotto_origine = ? OR (c.prodotto_origine IS NULL AND c.concetto_id IN ({marks})))
                            ORDER BY c.priorita, c.id""", (drug, *drug_concepts)):
                        add(row["code"], drug, 3, "Complemento candidato: " + row["motivo"], row["esclusioni"],
                            name=row["nome"], kind=row["categoria"], price=row["prezzo_cent"], stock=row["quantita"],
                            link_id=row["id"])
                if drug_concepts and "relazioni_concetto_prodotto" in tables:
                    marks = ",".join("?" for _ in drug_concepts)
                    categories = ",".join("?" for _ in SUPPLEMENT_CATEGORIES)
                    for row in db.execute(f"""
                            SELECT r.prodotto_codice AS code, r.contesto, r.esclusioni, c.nome AS concetto,
                                   {product_columns}
                            FROM relazioni_concetto_prodotto r
                            JOIN prodotti p ON p.codice = r.prodotto_codice
                            JOIN concetti c ON c.id = r.concetto_id
                            WHERE r.concetto_id IN ({marks}) AND r.fonte_id IS NOT NULL
                              AND r.stato_revisione IN ('approvata','candidata')
                              AND p.categoria IN ({categories})
                            ORDER BY r.prodotto_codice""", (*drug_concepts, *SUPPLEMENT_CATEGORIES)):
                        add(row["code"], drug, 3, "Collegato con fonte a «" + row["concetto"] + "»",
                            row["esclusioni"], name=row["nome"], kind=row["categoria"],
                            price=row["prezzo_cent"], stock=row["quantita"])
            if said:
                names = dict(db.execute(f"SELECT id, nome FROM concetti WHERE id IN ({','.join('?' for _ in said)})",
                                        said).fetchall())
                categories = ",".join("?" for _ in SUPPLEMENT_CATEGORIES)
                for concept in said:
                    symptom = (concept, names.get(concept, concept))
                    if "complementi_banco" in tables:
                        for row in db.execute(f"""
                                SELECT c.id, c.prodotto_complemento AS code, c.motivo, c.esclusioni, c.stato_revisione,
                                       {product_columns}
                                FROM complementi_banco c JOIN prodotti p ON p.codice = c.prodotto_complemento
                                WHERE c.concetto_id = ? AND c.prodotto_origine IS NULL
                                  AND c.stato_revisione IN ('approvata','candidata')
                                ORDER BY c.stato_revisione = 'approvata' DESC, c.priorita, c.id""", (concept,)):
                            approved = row["stato_revisione"] == "approvata"
                            add(row["code"], None, 2 if approved else 3,
                                ("" if approved else "Complemento candidato: ") + row["motivo"], row["esclusioni"],
                                name=row["nome"], kind=row["categoria"], price=row["prezzo_cent"],
                                stock=row["quantita"], link_id=row["id"], symptom=symptom)
                    if "relazioni_concetto_prodotto" in tables:
                        for row in db.execute(f"""
                                SELECT r.prodotto_codice AS code, r.esclusioni, r.stato_revisione, {product_columns}
                                FROM relazioni_concetto_prodotto r JOIN prodotti p ON p.codice = r.prodotto_codice
                                WHERE r.concetto_id = ? AND r.fonte_id IS NOT NULL
                                  AND r.stato_revisione IN ('approvata','candidata') AND p.categoria IN ({categories})
                                ORDER BY r.prodotto_codice""", (concept, *SUPPLEMENT_CATEGORIES)):
                            approved = row["stato_revisione"] == "approvata"
                            add(row["code"], None, 2 if approved else 3,
                                f"Collegato con fonte a «{symptom[1]}»", row["esclusioni"], name=row["nome"],
                                kind=row["categoria"], price=row["prezzo_cent"], stock=row["quantita"],
                                symptom=symptom)
    except sqlite3.Error:
        return []
    order = {code: index for index, code in enumerate(drug_codes)}
    said_order = {concept: index for index, concept in enumerate(said)}
    items = [item for item in found.values() if item["linked_to"] or item["for_symptoms"]]
    for item in items:
        item["linked_to"].sort(key=lambda link: (link["livello"], order.get(link["code_farmaco"], 99)))
        item["for_symptoms"].sort(key=lambda entry: (entry["livello"], said_order.get(entry["concetto_id"], 99)))
        best_drug = min((link["livello"] for link in item["linked_to"]), default=9)
        best_symptom = min((entry["livello"] for entry in item["for_symptoms"]), default=9)
        # 0 approved with the drug · 1 approved for a need (drug's or said) · 2 candidate with the drug · 3 symptom only
        item["tier"] = 0 if best_drug == 1 else 1 if min(best_drug, best_symptom) == 2 else 2 if item["linked_to"] else 3
        item["origin"] = "farmaco" if item["linked_to"] else "sintomo"
    items.sort(key=lambda item: (item["tier"], -len(item["linked_to"]), -len(item["for_symptoms"]),
                                 min((order.get(link["code_farmaco"], 99) for link in item["linked_to"]), default=99),
                                 min((said_order.get(e["concetto_id"], 99) for e in item["for_symptoms"]), default=99),
                                 item["name"].lower()))
    return items[:12]


def with_product(state, catalog, code):
    """«Con questo prodotto»: the most likely supplement and up to two pertinent offers for the chosen drug."""
    from backend import knowledge
    from backend.offers import active_offers
    if not code:
        return None
    linked = linked_supplements(state, catalog, [code])
    supplement = linked[0] if linked else None
    reasons = {code: (0, "sul prodotto scelto")}
    try:
        for variant in knowledge.documented_variants(code, catalog=Path(catalog)):
            reasons.setdefault(variant["code"], (1, "formato conveniente dello stesso prodotto"))
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
        pass
    for item in linked[:3]:
        reasons.setdefault(item["code"], (2, "sull'integratore collegato"))
    for item in (state.get("cart") or {}).get("items", []):
        if item.get("code"):
            reasons.setdefault(item["code"], (3, "su un prodotto già nel carrello"))
    try:
        offers = active_offers(datetime.now(timezone.utc).date(), {"product_codes": set(reasons)}, Path(catalog))
    except (OSError, sqlite3.Error, ValueError):
        offers = []
    rows = sorted(({"code": offer["prodotto_codice"], "name": offer.get("prodotto_nome"),
                    "offer_code": offer["codice"], "title": offer.get("titolo"), "benefit": offer.get("beneficio"),
                    "price_cents": offer.get("prezzo_cent"), "end": offer.get("fine"),
                    "demo": offer.get("stato") == "demo", "reason": reasons[offer["prodotto_codice"]][1],
                    "_rank": reasons[offer["prodotto_codice"]][0]} for offer in offers), key=lambda row: row["_rank"])
    for row in rows:
        row.pop("_rank")
    return {"code": code, "supplement": supplement, "offers": rows[:2], "offers_empty": not rows}
