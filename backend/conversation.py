"""Deterministic search signals for one volatile Italian transcript revision."""

import re

from backend.knowledge import FORM_NAMES
from collections import defaultdict
from difflib import SequenceMatcher
from unicodedata import normalize


RULE_VERSION = "2"
GLOSSARY = "wiki/GLOSSARIO.md"

_CLAUSE = re.compile(r"(?:[^.!?;\n]|(?<=\d)\.(?=\d))+[.!?;]?")
_CORRECTION = re.compile(r"\b(?:anzi|intendevo|volevo dire|mi correggo|mi sono sbagliat[oa])\b", re.IGNORECASE)
_NEGATION = re.compile(r"\b(?:non|nessun[oa]?|senza|esclud[ao])\b", re.IGNORECASE)
_REFUSAL = re.compile(r"\b(?:non\s+(?:(?:lo|la|li|le|ne)\s+)?(?:voglio|vorrei|prendo|mi interessa)(?:\s+pi[uù])?|rifiuto)\b", re.IGNORECASE)
_TARGET_NEGATION = re.compile(r"\b(?:non(?:\s+(?:cerco|compro))?|esclud[ao])\b", re.IGNORECASE)
_PRONOMINAL_NEGATION = re.compile(r"\bnon\s+(?:lo|la|li|le|ne)\s+(?:cerco|compro|prendo|voglio)\b", re.IGNORECASE)
_PAST = re.compile(
    r"\b(?:avev(?:o|i|a|amo|ate|ano)|avuto|usavo|prendevo|prendeva|cercavo|volevo(?!\s+dire\b)|compravo|usato|usata|preso(?!\s+una\s+botta\b)|presa|"
    r"comprato|comprata|utilizzato|utilizzata|cercato|acquistato|in passato|prima usavo|l[’']altra volta|"
    r"(?:giorno|settimana|mese|anno)\s+scors[oa]|(?:giorni|settimane|mesi|anni)\s+fa|(?<!\bda\s)ieri)\b",
    re.IGNORECASE,
)
_REQUEST = re.compile(
    r"\b(?:cerco|sto cercando|vorrei|voglio|mi serve|mi dia|mi dà|mi da|mi darebbe|"
    r"posso\s+(?:avere|comprare)|avete(?:\s+offerte)?|quanto\s+costa|quanto\s+viene|"
    r"(?:è|e)\s+disponibile|(?:c[’']è|c[’']e|ce)\s+(?:un[’']?\s*offerta|il|la|un|una)|"
    r"ci sono\s+offerte)\b",
    re.IGNORECASE,
)
_REQUEST_GAP = re.compile(
    r"\s*(?:(?:comprare|acquistare|prendere|vedere|avere|per|sul|sulla|del|della|di)\s+)?"
    r"(?:(?:il|lo|la|i|gli|le|un|uno|una|questo|questa)\s+|(?:l|un)[’'])?\s*",
    re.IGNORECASE,
)
_POST_REQUEST = re.compile(r"(?:quanto\s+(?:costa|viene)|(?:è|e)\s+disponibile|ce\s+l[’']avete)", re.IGNORECASE)
_VERIFY = re.compile(r"\b(?:mi controlla|apri la scheda di|apro la scheda di|(?:c[’']è|ce) il generico di)\b", re.IGNORECASE)
_PROPOSAL = re.compile(r"\b(?:le propongo|propongo|le consiglio|consiglio)\b", re.IGNORECASE)
_ACCEPTANCE = re.compile(r"\b(?:va bene|prendo)\b(?!\s+gi[aà]\b)", re.IGNORECASE)
_TURN_ACTION = "(?:" + "|".join(pattern.pattern for pattern in
                                 (_REQUEST, _VERIFY, _PROPOSAL, _ACCEPTANCE)) + ")"
_TURN = re.compile(
    r"\b(?:ma|però|pero|anzi|intendevo|volevo dire|mi correggo|mi sono sbagliat[oa])\b|"
    r",\s*(?=non\b(?!\s+pi[uù]\s+di)|rifiuto\b)|"
    r"(?P<symptom_negation_boundary>\s+(?:e\s+)?(?=non\s+(?:ho|ha|abbiamo|hanno)\s))|"
    r"(?P<context_boundary>\b(?:oggi|ora|adesso)\s+(?=(?:ho|ha|abbiamo|hanno|sono|è)\b)|"
    r"(?:,\s*|\be\s+)(?=(?:ho|ha|abbiamo|hanno)\s))|"
    rf"(?P<action_boundary>,\s*(?={_TURN_ACTION})|\be\s+(?={_TURN_ACTION}))",
    re.IGNORECASE,
)
_QUESTION = re.compile(r"\b(?:per chi|da quanto|cosa ha gi[aà] provato|cosa mi consiglia|mi controlla|c[’']è il generico)\b", re.IGNORECASE)
_CLOSING_SIGNALS = (
    ("serve_altro", re.compile(
        r"\b(?:(?:(?:le|ti|vi|gli)\s+)?(?:serve|servono|occorre|occorrono)\s+(?:anche\s+)?(?:qualcos['’]?\s*)?altro|"
        r"oltre\s+a\s+(?:questo|questa|ciò)\s*,?\s*(?:cos(?:[’']|\s+)?altro|cosa(?:\s+altro)?|che\s+altro)\s+"
        r"(?:(?:ti|le|vi)\s+)?serve|"
        r"ha(?:nno)?\s+bisogno\s+di\s+(?:qualcos['’]?\s*)?altro)\b", re.IGNORECASE)),
    ("desidera_altro", re.compile(
        r"\b(?:(?:desidera|desiderate|gradirebbe|gradite)\s+(?:altro|aggiungere qualcosa)|"
        r"c[’']è\s+altro\s+che\s+(?:desidera|desiderate)|"
        r"c[’']è\s+qualcosa\s+da\s+abbinare)\b", re.IGNORECASE)),
    ("vuole_altro", re.compile(
        r"\b(?:(?:vuole|vuoi|volete)\s+(?:altro|aggiungere qualcosa)|"
        r"posso\s+(?:aiutarla|aiutarti|aiutarvi|servirle)\s+con\s+altro)\b", re.IGNORECASE)),
)
_OFFER_DECLINE = re.compile(
    r"\b(?:non\s+(?:(?:mi|ci)\s+)?(?:serve|servono|occorre|voglio|vogliamo|desidero)\s+(?:nient['’]?)?altro|"
    r"(?:nient['’]?altro|basta\s+cos[iì]|va\s+bene\s+cos[iì](?:\s*,?\s*grazie)?))\b", re.IGNORECASE,
)
_CHECKOUT = re.compile(
    r"\b(?:passiamo\s+(?:alla|in)\s+cassa|andiamo\s+alla\s+cassa|"
    r"(?:posso|vorrei)\s+pagare|(?:pago|paga)\s+(?:con\s+carta|in\s+contanti)|facciamo\s+lo\s+scontrino)\b",
    re.IGNORECASE,
)
_RESEARCH_REQUEST = re.compile(
    r"\b(?:avete|avrebbe|cerco|vorrei|mi\s+serve|cosa\s+avete)\s+qualcosa\s+per\b", re.IGNORECASE,
)
_CLARIFICATION_QUESTION = re.compile(
    r"\b(?:per\s+chi(?:\s+[èe])?|da\s+quanto\s+(?:tempo|ce\s+l['’]ha|dura)|"
    r"quali\s+sintomi|mi\s+descriv[ae]\s+(?:il\s+)?(?:fastidio|dolore))\b",
    re.IGNORECASE,
)
_UNSPECIFIED_NEED = re.compile(
    r"\b(?:mal(?:e)?\s+(?:di|allo)\s+stomaco|mal\s+di\s+pancia|fa\s+male\s+lo\s+stomaco|dolore\s+(?:allo|di)\s+stomaco|"
    r"(?:mal(?:e)?|dolore)\s+(?:(?:all['’]|a\s+un\s+)occhio|agli\s+occhi)|"
    r"(?:fa|fanno)\s+male\s+(?:l['’]occhio|gli\s+occhi)|allergia)\b",
    re.IGNORECASE,
)
_EXTRA_REQUEST = re.compile(
    r"\b(?:(?:cerco|vorrei|avete|mi\s+serve|mi\s+consiglia)\s+(?:un\s+|degli\s+)?integrator[ei])\b",
    re.IGNORECASE,
)
_IMMUNE_SUPPORT = re.compile(
    r"\b(?:supporto\s+(?:(?:del|al)\s+sistema\s+immunitario|(?:delle|alle|per\s+le)\s+difese(?:\s+immunitarie)?|immunitario)|"
    r"(?:sostenere|supportare)\s+le\s+difese(?:\s+immunitarie)?|normale\s+funzione\s+immunitaria)\b",
    re.IGNORECASE,
)
_EXPLICIT_NEED = re.compile(r"\b(?:cerco|vorrei|avete|avrebbe|mi\s+serve|mi\s+consiglia)\b", re.IGNORECASE)
_DESK_PREFERENCE = re.compile(r"\b(?:preferisco|preferirei|preferiamo|meglio)\b", re.IGNORECASE)
_DESK_CHOICE = re.compile(
    r"\b(?:va\s+bene|prend(?:o|iamo)|scelg(?:o|liamo)|vorrei|mi\s+dia|intendevo|volevo\s+dire)\b",
    re.IGNORECASE,
)
_DESK_CLASS = re.compile(r"\b(?P<generico>generic(?:[oai]|he))\b|\b(?P<marca>di\s+marca)\b", re.IGNORECASE)
_DESK_FORM = re.compile("|".join(rf"(?P<{key}>\b(?:{pattern})\b)"
                                 for key, (_, pattern) in FORM_NAMES.items()), re.IGNORECASE)


def _desk_modifier(clause, pattern):
    found = {item.lastgroup for item in pattern.finditer(clause)}
    return next(iter(found)) if len(found) == 1 else None


def _bare_desk_choice(clause, spans):
    for start, end in spans:
        left = clause[:start].strip().casefold()
        right = clause[end:].strip(" ,.!?").casefold()
        if left in {"", "il", "la", "lo", "le", "i", "gli", "un", "uno", "una", "quello", "quella", "l'", "l’"} \
                and right in {"", "per favore", "grazie"}:
            return True
    return False
_RECIPIENT = re.compile(
    r"\bper\s+(?:me(?:\s+stess[oa])?|(?:un\s+(?P<man>uomo)|una\s+(?P<woman>donna))|(?:mio|mia|il mio|la mia)\s+"
    r"(?P<relation>figlio|figlia|padre|madre|nonno|nonna|marito|moglie|partner|amico|amica|fratello|sorella))\b",
    re.IGNORECASE,
)
_AGE_OTHER = re.compile(r"(?:\s+di\s+|\s*,\s*(?:ne\s+)?ha\s+)([0-9]{1,3}|[^\W\d_]+(?:\s+[^\W\d_]+)?)\s+anni\b", re.IGNORECASE)
_AGE_SELF = re.compile(r"(?:\s+di\s+|\s*,?\s+ho\s+)([0-9]{1,3}|[^\W\d_]+(?:\s+[^\W\d_]+)?)\s+anni\b", re.IGNORECASE)
_RECIPIENT_LINK = re.compile(r"\b(?:è|e|serve|lo prendo|lo voglio|lo cerco|la prendo|la voglio|la cerco)\s*$", re.IGNORECASE)
_BUDGET = re.compile(r"\b(?:budget(?:\s+di)?|massimo|fino\s+a|non\s+pi[uù]\s+di)\s+(\d{1,6})(?:[,.](\d{1,2}))?\s*(?:euro\b|€)", re.IGNORECASE)
_BUDGET_GAP = re.compile(r"\s*,?\s*(?:(?:con|a)\s+)?", re.IGNORECASE)
_REMOVAL = re.compile(
    r"\bcome\s+(?:(?:lo\s+)?(?:rimuovo|tolgo)|(?:rimuovere|togliere)\s+(?:il\s+)?(?:mascara|trucco)|"
    r"(?:faccio\s+a\s+)?(?:rimuoverlo|toglierlo))\b",
    re.IGNORECASE,
)
_UNITS = ("zero", "uno", "due", "tre", "quattro", "cinque", "sei", "sette", "otto", "nove", "dieci",
          "undici", "dodici", "tredici", "quattordici", "quindici", "sedici", "diciassette", "diciotto", "diciannove")
_TENS = ("venti", "trenta", "quaranta", "cinquanta", "sessanta", "settanta", "ottanta", "novanta")
_TOPICS = (
    ("menopausa-e-pillola", r"menopausa|pillola(?: contraccettiva)?", "Chiarire la domanda e il prodotto, se pertinente."),
    ("abbinamenti-da-verificare", r"abbinar(?:e|ci)\s+un\s+integratore|prend(?:o|e)\s+gi[aà]\s+(?:un\s+medicinale|delle\s+medicine|farmaci)|effetto indesiderato|terapia in corso", "Chiarire quali prodotti o terapie sono coinvolti."),
)
_SYMPTOMS = (
    ("raffreddore", r"raffreddor(?:e|i|ato|ata|ati|ate)|sintomi da raffreddamento", "Chiarire quale informazione serve.", "raffreddore"),
    ("congestione-nasale", r"naso chiuso|naso tappato|congestione nasale|ostruzione nasale", "Chiarire quale informazione serve.", "congestione-nasale"),
    ("tosse", r"tosse(?:\s+(?:secca|grassa|produttiva|con catarro))?|tossire|tossisco", "Chiarire quale informazione serve.", "tosse"),
    ("acidita-stomaco", r"acidit[aà](?:\s+(?:di\s+stomaco|gastrica))?|bruciore\s+(?:di|allo)\s+stomaco|brucia\s+lo\s+stomaco", "Chiarire il tipo di bruciore.", "acidita-stomaco"),
    ("reflusso", r"reflusso(?:\s+gastroesofageo)?|rigurgito\s+acido", "Chiarire il contesto del reflusso.", "reflusso"),
    ("mal-di-testa", r"mal(?:e)?\s+(?:di|alla)\s+testa|fa\s+male\s+la\s+testa|cefalea", "Chiarire il contesto del mal di testa.", "mal-di-testa"),
    ("contusioni", r"contusion[ei]|lividi|livido|ematoma|ematomi|bott[ae]\s+(?:al|alla|sul|sulla|sulle|sui)|ho\s+preso\s+una\s+botta", "Chiarire la sede e il contesto della contusione.", "contusioni"),
    ("irritazione-oculare", r"(?:secchezza|irritazione)\s+ocular[ei]|occhi\s+(?:secchi|irritati)|bruciore\s+(?:agli\s+occhi|oculare)|bruciano\s+gli\s+occhi|occhio\s+secco", "Chiarire il tipo di fastidio oculare.", "irritazione-oculare"),
    ("allergia-nasale", r"rinit[ei]\s+allergic[ae]|allergia\s+(?:nasale|al\s+naso)|starnuti\s+(?:allergici|da\s+allergia)", "Chiarire i sintomi nasali dichiarati.", "allergia-nasale"),
    ("allergia-oculare", r"congiuntivit[ei]\s+allergic[ae]|allergia\s+(?:oculare|agli\s+occhi)", "Chiarire i sintomi oculari dichiarati.", "allergia-oculare"),
    ("allergia-cutanea", r"orticaria", "Chiarire il contesto dell’orticaria dichiarata.", "allergia-cutanea"),
)
_SERVICES = (
    ("turni", r"farmaci[ae] (?:di turno|apert[ae])|aperta stasera"),
    ("orari", r"orari(?:o)?|a che ora (?:aprite|chiudete)|quando (?:aprite|chiudete)"),
    ("sito", r"sito(?: web| della farmacia)?|pagina web"),
)


def _source(kind, identifier, label):
    return {"kind": kind, "id": identifier, "label": label, "version": RULE_VERSION}


def _signal(kind, span, reason, partial, *, code=None, wiki=None):
    rule = f"conversation.{kind}"
    start, end = span
    source = _source("rule", GLOSSARY, "Glossario di ricerca")
    if code:
        source = _source("catalog", code, "Catalogo locale")
    elif wiki:
        source = _source("wiki", wiki, f"wiki/schede/{wiki}.md")
    return {
        "id": f"{rule}:{start}:{end}:{code or wiki or ''}",
        "rule_id": rule,
        "kind": kind,
        "span": {"start": start, "end": end},
        "state": "provisional" if partial else "active",
        "reason": reason,
        "source": source,
        "product_codes": [code] if code else [],
    }


def _clauses(text):
    for sentence in _CLAUSE.finditer(text):
        start, end = sentence.span()
        for turn in _TURN.finditer(text, start, end):
            if turn.group("symptom_negation_boundary") and not re.search(
                r"\b(?:ho|ha|abbiamo|hanno)\b", text[start:turn.start()], re.IGNORECASE
            ):
                continue
            if turn.group("action_boundary") or turn.group("context_boundary"):
                prefix = text[start:turn.start()]
                budgets = list(_BUDGET.finditer(prefix))
                has_negation = any(not any(budget.start() <= match.start() < budget.end() for budget in budgets)
                                   for match in _NEGATION.finditer(prefix))
                if not (has_negation or _REFUSAL.search(prefix) or _PAST.search(prefix)
                        or _CORRECTION.search(prefix)):
                    continue
            if turn.start() > start:
                yield start, text[start:turn.start()]
            start = turn.start()
        yield start, text[start:end]


def _product_patterns(product_terms):
    seen = set()
    for record in product_terms or []:
        code = record.get("code") or record.get("codice")
        if not code:
            continue
        details = record.get("termini_dettaglio")
        if isinstance(details, list):
            terms = [(item.get("term"), item.get("basis", "catalog_term"), item.get("source"))
                     for item in details if isinstance(item, dict)]
        else:
            fallback_source = {"kind": "catalog", "id": code,
                               "label": record.get("nome") or "Catalogo locale"}
            terms = [(term, "catalog_term", fallback_source)
                     for term in (code, record.get("term"), record.get("termine"), record.get("nome"),
                                  *(record.get("termini") or []))]
        for term, basis, source in terms:
            if not isinstance(term, str):
                continue
            parts = list(re.finditer(r"[^\W_]+", term.casefold()))
            tokens = [part.group(0) for part in parts]
            if len("".join(tokens)) < 3 or (code, tuple(tokens)) in seen:
                continue
            seen.add((code, tuple(tokens)))
            phrase = ""
            for i, token in enumerate(tokens):
                if i:
                    separator = term[parts[i - 1].end():parts[i].start()].strip()
                    if separator == "/":
                        phrase += r"(?:\s*/\s*|\s+per\s+|\s+)"
                    elif separator in {".", ","} and tokens[i-1].isdigit() and token.isdigit():
                        phrase += r"(?:[,.]|\s+virgola\s+)"
                    else:
                        phrase += r"[\s/\-‐‑–]+"
                phrase += _product_token(token, i + 1 < len(tokens) and tokens[i + 1] in _SPOKEN_UNITS)
            yield code, re.compile(rf"\b{phrase}\b", re.IGNORECASE), {
                "term": term.strip(), "basis": basis,
                "source": source or {"kind": "catalog", "id": code,
                                      "label": record.get("nome") or "Catalogo locale"},
            }


_SPOKEN_UNITS = {"mg": r"milligramm[oi]", "ml": r"millilitr[oi]",
                 "g": r"gramm[oi]", "mcg": r"microgramm[oi]"}


def _product_token(token, before_unit):
    if token == "nasale":
        return r"nasal[ei]"
    if token in _SPOKEN_UNITS:
        return rf"(?:{token}|{_SPOKEN_UNITS[token]})"
    if not (token.isascii() and token.isdigit() and len(token) <= 3
            and (len(token) == 1 or not token.startswith("0"))):
        return re.escape(token)
    number = int(token)
    hundreds, rest = divmod(number, 100)
    prefix = ("" if hundreds == 1 else _UNITS[hundreds]) + "cento" if hundreds else ""
    if rest < 20:
        word = prefix + (_UNITS[rest] if rest or not hundreds else "")
    else:
        tens, units = divmod(rest, 10)
        stem = _TENS[tens - 2]
        word = prefix + (stem[:-1] if units in (1, 8) else stem) + (_UNITS[units] if units else "")
    short_one = "|un" if before_unit and number == 1 else ""
    return rf"(?:{token}|{word}{short_one})"


def _product_hits(clause, patterns):
    matches = {}
    for code, pattern, details in patterns:
        for match in pattern.finditer(clause):
            key = (code, *match.span())
            matches.setdefault(key, []).append(details)
    accepted = []
    for code, start, end in sorted(matches, key=lambda hit: (hit[1], -hit[2], hit[0])):
        if any(other_start <= start and end <= other_end and (other_start, other_end) != (start, end)
               for _, other_start, other_end, _ in accepted):
            continue
        source_priority = {"product_name": 0, "product_code": 1, "catalog_alias": 2,
                           "active_ingredient": 3, "supplement_ingredient": 4,
                           "demo_wiki_alias": 5, "catalog_term": 6}
        detail = min(matches[(code, start, end)],
                     key=lambda item: (source_priority.get(item.get("basis"), 99), item["term"].casefold()))
        accepted.append((code, start, end, detail))
    return accepted


_SPOKEN_WORD = re.compile(r"[^\W\d_]+")
_NON_BRAND_WORDS = {"compresse", "capsule", "granulato", "integratore", "medicinale", "prodotto", "magnesio"}


def _spoken_key(value):
    # Rejoin syllables and normalize common transcript spellings of Italian sounds.
    value = "".join(char for char in normalize("NFD", value.casefold()) if char.isalpha())
    value = re.sub(r"(.)\1+", r"\1", value)
    return re.sub(r"c(?=[ie])", "z", value)


def _spoken_index(patterns):
    names = defaultdict(dict)
    families = defaultdict(dict)
    for code, _, detail in patterns:
        term = detail["term"]
        basis = detail["basis"]
        words = _SPOKEN_WORD.findall(term)
        if not words or basis not in {"product_name", "catalog_alias"}:
            continue
        if basis == "product_name" and words[0].casefold() not in _NON_BRAND_WORDS:
            families[words[0].casefold()][code] = (words[0], detail["source"])
        # A name with a numeric strength remains the exact matcher's job.
        if not any(char.isdigit() for char in term):
            names[term.casefold()][code] = (term, detail["source"])
    for name, records in families.items():
        # A shared leading catalog word identifies a group, never a specific SKU.
        if len(records) > 1:
            names[name].update(records)
    return [(key, name, records) for name, records in names.items()
            if len(key := _spoken_key(name)) >= 7]


def _spoken_hits(clause, index, exact_hits):
    words = list(_SPOKEN_WORD.finditer(clause))
    matches = []
    for index_start, first in enumerate(words):
        for last in words[index_start:index_start + 4]:
            start, end = first.start(), last.end()
            fragment = clause[start:end]
            if re.search(r"[^\w\s‐‑–-]", fragment) or any(char.isdigit() for char in fragment):
                break
            if any(start < hit_end and hit_start < end for _, hit_start, hit_end, _ in exact_hits):
                continue
            key = _spoken_key(fragment)
            if len(key) < 7:
                continue
            options = []
            for target, name, records in index:
                if key == target:
                    options.append((1.0, name, records))
                elif key[:3] == target[:3] and min(len(key), len(target)) >= 8 and abs(len(key) - len(target)) <= 1:
                    score = SequenceMatcher(None, key, target, autojunk=False).ratio()
                    if score >= 0.88:
                        options.append((score, name, records))
            options.sort(key=lambda item: item[0], reverse=True)
            if not options or (len(options) > 1 and options[0][0] - options[1][0] < 0.09):
                continue
            score, name, records = options[0]
            matches.append((score, start, end, name, records))
    accepted = []
    for _, start, end, name, records in sorted(matches, key=lambda item: (-item[0], item[1], -item[2])):
        if any(start < other_end and other_start < end for other_start, other_end, _, _ in accepted):
            continue
        accepted.append((start, end, name, records))
    return sorted(accepted, key=lambda item: item[0])


def _refine_spoken_hits(clause, hits, patterns):
    """Resolve a noisy family only when its following catalog details match."""
    refined = []
    for start, end, name, records in hits:
        if len(records) > 1:
            label = next(iter(records.values()))[0]
            replacement_end = start + len(label)
            probe = clause[:start] + label + clause[end:]
            candidates = [
                (code, stop, detail) for code, begin, stop, detail in _product_hits(probe, patterns)
                if begin == start and stop > replacement_end and code in records
                and detail["basis"] in {"product_name", "catalog_alias"}
            ]
            codes = {code for code, _, _ in candidates}
            if len(codes) == 1:
                code, stop, detail = max(candidates, key=lambda item: item[1])
                refined.append((start, stop + end - replacement_end, name,
                                {code: (detail["term"], detail["source"])}))
                continue
        refined.append((start, end, name, records))
    return refined


def _linked_signal(clause, pattern, start, end, post_pattern=None):
    """Bind a trigger and an alias only through the supported short grammar."""
    for trigger in pattern.finditer(clause, 0, start):
        if _REQUEST_GAP.fullmatch(clause, trigger.end(), start):
            return trigger.start(), end
    if post_pattern:
        for trigger in post_pattern.finditer(clause, end):
            if not clause[end:trigger.start()].strip():
                return start, trigger.end()
    return None


def _italian_age(value):
    if value.isascii() and value.isdigit():
        age = int(value)
        return age if age <= 125 else None
    word = "".join(value.casefold().split()).replace("é", "e")
    hundreds = 100 if word.startswith("cento") else 0
    if hundreds:
        word = word[5:] or "zero"
    if word == "un":
        word = "uno"
    if word in _UNITS:
        return hundreds + _UNITS.index(word)
    for tens, prefix in enumerate(_TENS, start=2):
        for units in range(10):
            stem = prefix[:-1] if units in {1, 8} else prefix
            full = stem + (_UNITS[units] if units else "")
            age = hundreds + tens * 10 + units
            if age <= 125 and (word == full or (units == 1 and word == full[:-1])):
                return age
    return None


def _phase(value, reason, *missing):
    return {"value": value, "source": "auto", "reason": reason, "missing": list(missing)}


def analyze(text: str, product_terms: list[dict] | None = None, partial: bool = False,
            *, finalized_end: int | None = None) -> dict:
    """Return codepoint spans and provisional candidates for exactly this text.

    Catalog records or flat code/term pairs provide the only product names.
    The caller owns transcript revisions, stability and pharmacist actions.
    """
    patterns = list(_product_patterns(product_terms))
    spoken_index = _spoken_index(patterns)
    if finalized_end is None:
        finalized_end = 0 if partial else len(text)
    unknown_recipient = {"kind": "sconosciuto", "relation": None, "declared_fields": {}, "source": "unknown"}
    recipient = unknown_recipient
    evidence = []
    events = []
    candidates = {}
    interests = {}
    topics = {}
    spoken_matches = {}
    service = None
    removal = None
    question = None
    recipient_signal = None
    sales_stage = "collecting"
    closing_signal = None
    phase = _phase("Raccolta", "Sto raccogliendo il contesto.", "Quale prodotto, informazione o servizio serve?")

    for offset, clause in _clauses(text):
        def signal(kind, span, reason, *, code=None, wiki=None, match=None):
            item = _signal(kind, (offset + span[0], offset + span[1]), reason, partial, code=code, wiki=wiki)
            if match:
                item["matched_term"] = match["term"]
                item["matched_term_basis"] = match["basis"]
                item["source"] = match["source"]
            return item

        def event(item):
            evidence.append(item)
            events.append({"kind": item["kind"], "evidence_id": item["id"]})

        correction = _CORRECTION.search(clause)
        refusal = _REFUSAL.search(clause)
        budgets = list(_BUDGET.finditer(clause))
        negations = [match for match in _NEGATION.finditer(clause)
                     if not any(budget.start() <= match.start() < budget.end() for budget in budgets)]
        negation = negations[0] if negations else None
        past = _PAST.search(clause)
        hits = _product_hits(clause, patterns)
        stage = None
        stage_span = None
        clause_closing_signal = None
        span_counts = {}
        for _, start, end, _ in hits:
            span_counts[start, end] = span_counts.get((start, end), 0) + 1

        if correction:
            event(signal("correction", correction.span(), "Correzione esplicita da verificare."))
            candidates.clear()
            interests.clear()
            topics.clear()
            spoken_matches.clear()
            service = None
            removal = None
            question = "Qual è la richiesta corretta?"
            stage = "questions"
            stage_span = correction.span()
            closing_signal = None
        for kind, match, reason in (
            ("negation", negation, "Negazione rilevata nella frase."),
            ("refusal", refusal, "Rifiuto esplicito da verificare."),
            ("past", past, "Riferimento a un momento o uso passato."),
        ):
            if match:
                event(signal(kind, match.span(), reason))
                question = "Qual è la richiesta attuale?"
        if not hits and (refusal or _PRONOMINAL_NEGATION.search(clause)):
            candidates.clear()
            interests.clear()
            spoken_matches.clear()
        if refusal or negation:
            stage = "questions"
            stage_span = (refusal or negation).span()
            closing_signal = None

        # A partial may change both the product name and the meaning of its clause.
        # Analyze phonetic matches only after the entire clause is consolidated.
        spoken_hits = []
        if spoken_index and offset + len(clause) <= finalized_end:
            spoken_hits = _refine_spoken_hits(clause, _spoken_hits(clause, spoken_index, hits), patterns)
            for start, end, name, records in spoken_hits:
                kind = "spoken_exclusion" if refusal or negation or past else "spoken_match"
                item = signal(kind, (start, end), "Nome ricostruito dai termini del catalogo locale.")
                label, source = next(iter(records.values()))
                item.update({"recognized_name": label, "product_codes": sorted(records),
                             "matched_term": clause[start:end], "source": source,
                             "state": "active", "recognition_kind": ("catalog_family" if len(records) > 1 else "phonetic")})
                if kind == "spoken_exclusion":
                    spoken_matches.pop(name, None)
                    event(item)
                else:
                    spoken_matches[name] = item

        for code, start, end, matched_term in hits:
            span = (start, end)
            if refusal or negation or past or span_counts[span] == 1:
                for name, item in list(spoken_matches.items()):
                    if code in item["product_codes"]:
                        spoken_matches.pop(name)
            if refusal or negation or past:
                candidates.pop(code, None)
                interests.pop(code, None)
                named_refusal = _linked_signal(clause, _REFUSAL, start, end, _REFUSAL)
                named_negation = _linked_signal(clause, _TARGET_NEGATION, start, end, _PRONOMINAL_NEGATION)
                if not past and span_counts[span] == 1 and (named_refusal or named_negation):
                    kind = "refusal" if named_refusal else "negation"
                    event(signal(kind, named_refusal or named_negation, "Il testo esclude esplicitamente questo prodotto.", code=code))
                mention = signal("product_mention", span,
                                 "Prodotto citato in una frase con negazione, rifiuto o riferimento passato.",
                                 code=code, match=matched_term)
                mention["mention_context"] = "excluded"
                event(mention)
                continue
            if span_counts[span] > 1:
                question = "Quale confezione o prodotto intendi?"
                continue
            request = _linked_signal(clause, _REQUEST, start, end, _POST_REQUEST)
            proposal = _linked_signal(clause, _PROPOSAL, start, end)
            acceptance = _linked_signal(clause, _ACCEPTANCE, start, end)
            verification = _linked_signal(clause, _VERIFY, start, end)
            corrected = correction and correction.end() <= start and _REQUEST_GAP.fullmatch(clause[correction.end():start].lstrip(" ,"))
            if not (request or proposal or acceptance or verification or corrected):
                reason = ("Alias demo esplicito collegato al prodotto." if matched_term["basis"] == "demo_wiki_alias"
                          else "Prodotto identificato tramite un termine con provenienza locale.")
                mention = signal("product_mention", span, reason, code=code, match=matched_term)
                # A product adjacent to a correction marker is not a neutral
                # current mention. A corrected target follows the separate
                # product_candidate path above and remains eligible there.
                mention["mention_context"] = "excluded" if correction else "neutral"
                event(mention)
                question = "Che cosa vuoi verificare sul prodotto citato?"
                stage = "questions"
                stage_span = span
                continue
            reason = ("Alias demo esplicito collegato al prodotto da verificare." if matched_term["basis"] == "demo_wiki_alias"
                      else "Corrispondenza esatta con un termine del catalogo da verificare.")
            candidates[code] = signal("product_candidate", span, reason, code=code, match=matched_term)
            service = None
            for kind, event_span in (("proposal", proposal), ("acceptance", acceptance)):
                if event_span:
                    event(signal(kind, event_span, "Segnale verbale da confermare al banco.", code=code))
                    stage = "proposal" if kind == "proposal" else "sale"
                    stage_span = event_span
                    closing_signal = None
            if request and not proposal and not acceptance:
                stage = "questions"
                stage_span = request
                budget = next((match for match in budgets if match.start() >= request[1]
                               and _BUDGET_GAP.fullmatch(clause, request[1], match.start())), None)
                intent_span = (request[0], budget.end() if budget else request[1])
                item = signal("commercial_intent", intent_span, "Richiesta esplicita riferita al prodotto.", code=code)
                if budget:
                    item["budget_cent"] = int(budget[1]) * 100 + int((budget[2] or "").ljust(2, "0"))
                interests[code] = item

        # A short acceptance can refer to a product mentioned in an earlier
        # turn. Keep the stage cue, but do not infer which speaker said it or
        # attach it to a product unless this clause names one.
        if not hits and not (negation or refusal or past or correction):
            acceptance = _ACCEPTANCE.search(clause)
            if acceptance:
                event(signal("acceptance", acceptance.span(), "Segnale verbale di accettazione; oggetto e parlante non attribuiti."))
                stage = "sale"
                stage_span = acceptance.span()
                closing_signal = None

        # A closing question is a distinct conversation cue, never a claim that a
        # product was sold. The caller must match this evidence against its stable
        # transcript revision before allowing any approved complement to appear.
        decline = _OFFER_DECLINE.search(clause)
        if decline:
            event(signal("offer_decline", decline.span(), "Rifiuto della proposta aggiuntiva."))
            closing_signal = None
            stage, stage_span = "questions", decline.span()
        elif not (negation or refusal or past):
            form = _desk_modifier(clause, _DESK_FORM)
            classification = _desk_modifier(clause, _DESK_CLASS)
            preference = _DESK_PREFERENCE.search(clause)
            modifier_spans = [m.span() for pattern in (_DESK_FORM, _DESK_CLASS)
                              for m in pattern.finditer(clause)]
            product_spans = [(start, end) for _, start, end, _ in hits]
            product_spans.extend((start, end) for start, end, _, _ in spoken_hits)
            explicit_choice = _DESK_CHOICE.search(clause)
            modifier_reference = _bare_desk_choice(clause, modifier_spans)
            directive_head = preference or explicit_choice
            if directive_head:
                end = directive_head.end()
                modifier_reference |= _bare_desk_choice(
                    clause[end:], [(a - end, b - end) for a, b in modifier_spans if a >= end]
                )
            if preference and (form or classification):
                kind = "desk_preference"
            elif (modifier_reference and (form or classification)) or (
                    product_spans and (explicit_choice or _bare_desk_choice(clause, product_spans))):
                kind = "desk_choice"
            else:
                kind = None
            if kind:
                selection = signal(kind, (0, len(clause.rstrip())), "Scelta o preferenza per la consultazione al banco.")
                selection.update(choice_form=form, choice_classification=classification,
                                 choice_explicit=bool(explicit_choice or preference or modifier_reference),
                                 choice_reference=bool(correction or _bare_desk_choice(clause, modifier_spans)),
                                 choice_modifier_only=modifier_reference,
                                 choice_has_name=bool(product_spans))
                event(selection)

        closing_match = next(((kind, pattern.search(clause)) for kind, pattern in _CLOSING_SIGNALS
                              if pattern.search(clause)), None)
        if closing_match and not (negation or refusal or past or correction or decline):
            clause_closing_signal, match = closing_match
            closing = signal("closing_signal", match.span(), "Segnale verbale di chiusura; parlante non attribuito.")
            closing["closing_signal"] = clause_closing_signal
            closing["closing_reference"] = bool(re.search(r"\boltre\s+a\s+(?:questo|questa|ciò)\b",
                                                          clause, re.IGNORECASE))
            event(closing)
            stage = "closing"
            stage_span = match.span()
            closing_signal = clause_closing_signal
        elif stage is None and (_QUESTION.search(clause) or "?" in clause or any(
                re.search(rf"\b(?:{terms})\b", clause, re.IGNORECASE)
                for _, terms, _ in _TOPICS
        ) or any(re.search(rf"\b(?:{terms})\b", clause, re.IGNORECASE)
                 for _, terms, _, _ in _SYMPTOMS)
                or any(re.search(rf"\b(?:{terms})\b", clause, re.IGNORECASE) for _, terms in _SERVICES)):
            stage = "questions"
            match = _QUESTION.search(clause) or next((re.search(rf"\b(?:{terms})\b", clause, re.IGNORECASE)
                                                       for _, terms, _ in _TOPICS
                                                       if re.search(rf"\b(?:{terms})\b", clause, re.IGNORECASE)), None)
            if not match:
                match = next((re.search(rf"\b(?:{terms})\b", clause, re.IGNORECASE)
                              for _, terms, _, _ in _SYMPTOMS
                              if re.search(rf"\b(?:{terms})\b", clause, re.IGNORECASE)), None)
            stage_span = match.span() if match else (0, len(clause.rstrip()))
            closing_signal = None

        if stage:
            stage_item = signal("sales_stage_signal", stage_span or (0, len(clause.rstrip())),
                                "Fase della vendita dedotta da un segnale testuale stabile solo dopo la verifica del chiamante.")
            stage_item["sales_stage"] = stage
            if clause_closing_signal:
                stage_item["closing_signal"] = clause_closing_signal
            event(stage_item)
            sales_stage = stage

        declared = _RECIPIENT.search(clause)
        if declared and not (past or clause.rstrip().endswith("?")):
            relation = declared["relation"]
            gender = declared["man"] or declared["woman"]
            gender = gender.lower() if gender else None
            kind = "altra_persona" if relation or gender else "sé"
            age_match = (_AGE_OTHER if kind == "altra_persona" else _AGE_SELF).match(clause, declared.end())
            age = _italian_age(age_match[1]) if age_match else None
            relation = relation.lower() if relation else None
            same_recipient = (recipient["kind"] == kind and recipient["relation"] == relation
                              and recipient["declared_fields"].get("gender") == gender)
            if negation and same_recipient:
                recipient = unknown_recipient
                recipient_signal = None
            elif not negation and (relation or gender or age is not None or _RECIPIENT_LINK.search(clause[:declared.start()])
                                   or not clause[declared.end():].strip(" .!;,\t")):
                fields = {key: value for key, value in (("age", age), ("gender", gender)) if value is not None}
                recipient = {"kind": kind, "relation": relation, "declared_fields": fields, "source": "dichiarato"}
                declared_span = (declared.start(), age_match.end() if age is not None else declared.end())
                recipient_signal = signal("recipient", declared_span, "Destinatario dichiarato nella conversazione.", wiki="destinatario-dichiarato")
                question = "Quale informazione serve per il destinatario?"

        for wiki, terms, prompt in _TOPICS:
            match = re.search(rf"\b(?:{terms})\b", clause, re.IGNORECASE)
            if match and (negation or past or refusal):
                topics.pop(wiki, None)
            elif match:
                topics[wiki] = signal("topic", match.span(), "Termine di ricerca in una scheda dimostrativa.", wiki=wiki)
                question = prompt
        if not (negation or past or refusal) and any(
            re.search(rf"\b(?:ho|ha|abbiamo|hanno)\s+solo\s+(?:il\s+|la\s+|un\s+|una\s+)?(?:{terms})\b",
                      clause, re.IGNORECASE) for _, terms, _, _ in _SYMPTOMS
        ):
            for concept_id, _, _, _ in _SYMPTOMS:
                topics.pop(concept_id, None)
        for concept_id, terms, prompt, wiki in _SYMPTOMS:
            match = re.search(rf"\b(?:{terms})\b", clause, re.IGNORECASE)
            if match and (negation or past or refusal):
                topics.pop(concept_id, None)
                item = signal("symptom_exclusion", match.span(), "Sintomo negato o riferito al passato.", wiki=wiki)
                item["concept_id"] = concept_id
                event(item)
            elif match:
                item = signal(
                    "topic", match.span(), "Sintomo menzionato; verifica delle indicazioni documentate.",
                    wiki=wiki,
                    match={
                        "term": match.group(0),
                        "basis": "symptom_glossary",
                        "source": _source("wiki", wiki, f"wiki/schede/{wiki}.md"),
                    },
                )
                item["concept_id"] = concept_id
                topics[concept_id] = item
                question = prompt
        for kind, terms in _SERVICES:
            match = re.search(rf"\b(?:{terms})\b", clause, re.IGNORECASE)
            if match and (negation or past or refusal):
                if service and service[0] == kind:
                    service = None
            elif match:
                service = (kind, signal(f"service_{kind}", match.span(), "Richiesta di consultazione di un servizio.",
                                        wiki="farmacie-di-turno" if kind == "turni" else None))
                break
        removal_match = _REMOVAL.search(clause)
        if removal_match:
            removal = None if negation or past or refusal else signal(
                "cosmetic_removal", removal_match.span(), "Domanda esplicita sulla rimozione del trucco.", wiki="struccante-demo",
            )
        if _QUESTION.search(clause) and not (negation or past):
            question = "Quale informazione manca per proseguire la verifica?"

        # This state is separate from the legacy sales-stage signals used by
        # the product pipeline. It describes where the conversation is now.
        cue, phase_key, phase_reason = None, None, None
        immune_support = _IMMUNE_SUPPORT.search(clause)
        explicit_immune_need = immune_support and _EXPLICIT_NEED.search(clause[:immune_support.start()])
        if immune_support and (negation or refusal or past or explicit_immune_need):
            excluded = bool(negation or refusal or past)
            item = signal("supplement_need_exclusion" if excluded else "supplement_need", immune_support.span(),
                          "Bisogno di supporto immunitario negato o passato." if excluded
                          else "Richiesta esplicita di supporto alla normale funzione immunitaria.")
            item["concept_id"] = "supporto-immunitario"
            event(item)
        if decline:
            cue, phase_key = decline, "closing"
            phase_reason = "Chiusura senza altre proposte."
        elif not (past or negation or refusal):
            checkout = _CHECKOUT.search(clause)
            extras = _EXTRA_REQUEST.search(clause)
            broad_need = _UNSPECIFIED_NEED.search(clause)
            if broad_need and any(re.search(rf"\b(?:{terms})\b", clause, re.IGNORECASE)
                                  for _, terms, _, _ in _SYMPTOMS):
                broad_need = None
            research = _RESEARCH_REQUEST.search(clause)
            clarify = _CLARIFICATION_QUESTION.search(clause)
            if checkout:
                cue, phase_key, phase_reason = checkout, "closing", "Passaggio al pagamento o alla cassa."
            elif closing_match or extras or explicit_immune_need:
                cue, phase_key = closing_match[1] if closing_match else extras or immune_support, "extras"
                phase_reason = "Domanda esplicita su altri bisogni o integratori."
            elif broad_need:
                cue, phase_key, phase_reason = broad_need, "clarify", "Serve chiarire il sintomo prima di cercare prodotti."
                question = phase_reason
            elif research:
                cue, phase_key, phase_reason = research, "research", "Richiesta esplicita di cercare un prodotto."
            elif clarify:
                cue, phase_key, phase_reason = clarify, "clarify", "Domanda per precisare il bisogno o il destinatario."
        if cue:
            item = signal("sale_phase", (cue.start(), len(clause.rstrip())), phase_reason)
            item.update(phase_key=phase_key, matched_term=cue.group(0))
            event(item)

    if recipient_signal:
        evidence.append(recipient_signal)
    if removal:
        evidence.append(removal)
    evidence.extend(topics.values())
    evidence.extend(spoken_matches.values())
    evidence.extend(candidates.values())
    evidence.extend(interests.values())
    if service:
        kind, item = service
        evidence.append(item)
        missing = ["comune", "data"] if kind == "turni" else []
        phase = _phase("Servizio", item["reason"], *missing)
    elif candidates:
        phase = _phase("Verifica prodotto", "Prodotto candidato da verificare al banco.", "Conferma del farmacista")
    elif question:
        phase = _phase("Domande", "Occorre chiarire la richiesta prima di proseguire.", question)

    commercial = {"product_codes": list(interests)}
    budgets = {item.get("budget_cent") for item in interests.values()}
    if len(budgets) == 1 and None not in budgets:
        commercial["budget_cent"] = budgets.pop()
    evidence.sort(key=lambda item: (item["span"]["start"], item["span"]["end"], item["id"]))
    return {
        "phase": phase,
        "sales_stage": sales_stage,
        "closing_signal": closing_signal,
        "recipient": recipient,
        "evidence": evidence,
        "spoken_matches": list(spoken_matches.values()),
        "events": events,
        "candidate_codes": list(candidates),
        "commercial_intent": commercial,
        "service": {"kind": service[0] if service else None},
    }
