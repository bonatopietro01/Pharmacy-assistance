"""Profilo del destinatario: per chi è il prodotto (sé, altra persona, animale), genere, età, stati.

Ogni campo ha la sua origine:
- `dichiarato`: detto in modo esplicito («per mia figlia di 5 anni», «sono incinta»);
- `dedotto`: solo indizi (accordo grammaticale «sono stanca»): si mostra «da confermare»
  e NON esclude mai un prodotto;
- `manuale`: scelto dal farmacista sul banco.

Si legge la trascrizione frase per frase; vince l'ultima dichiarazione esplicita
(«anzi per mia figlia», «no, è per me»). Il profilo resta in memoria: non si salva.
"""

import re

from backend.conversation import _italian_age

BANDS = ("neonato", "bambino", "adolescente", "adulto", "anziano")
STATES = ("gravidanza", "allattamento")
SOURCES_THAT_FILTER = {"dichiarato", "manuale"}
NUMBER = r"([0-9]{1,3}(?:[,.]5)?|[^\W\d_]+(?:\s+[^\W\d_]+)?)"

# relation word → (relation key, gender, band)
RELATIONS = {
    "figlio": ("figlio", "uomo", None), "figlia": ("figlia", "donna", None),
    "figliolo": ("figlio", "uomo", None), "bambino": ("bambino", "uomo", "bambino"),
    "bambina": ("bambina", "donna", "bambino"), "bimbo": ("bambino", "uomo", "bambino"),
    "bimba": ("bambina", "donna", "bambino"), "piccolo": ("bambino", "uomo", "bambino"),
    "piccola": ("bambina", "donna", "bambino"), "neonato": ("neonato", "uomo", "neonato"),
    "neonata": ("neonata", "donna", "neonato"), "lattante": ("neonato", None, "neonato"),
    "ragazzo": ("ragazzo", "uomo", None), "ragazza": ("ragazza", "donna", None),
    "ragazzino": ("ragazzo", "uomo", "adolescente"), "ragazzina": ("ragazza", "donna", "adolescente"),
    "marito": ("marito", "uomo", "adulto"), "moglie": ("moglie", "donna", "adulto"),
    "compagno": ("compagno", "uomo", "adulto"), "compagna": ("compagna", "donna", "adulto"),
    "fidanzato": ("fidanzato", "uomo", None), "fidanzata": ("fidanzata", "donna", None),
    "padre": ("padre", "uomo", "adulto"), "papà": ("padre", "uomo", "adulto"), "babbo": ("padre", "uomo", "adulto"),
    "madre": ("madre", "donna", "adulto"), "mamma": ("madre", "donna", "adulto"),
    "nonno": ("nonno", "uomo", "anziano"), "nonna": ("nonna", "donna", "anziano"),
    "suocero": ("suocero", "uomo", "adulto"), "suocera": ("suocera", "donna", "adulto"),
    "fratello": ("fratello", "uomo", None), "sorella": ("sorella", "donna", None),
    "zio": ("zio", "uomo", None), "zia": ("zia", "donna", None),
    "nipotino": ("nipote", "uomo", "bambino"), "nipotina": ("nipote", "donna", "bambino"),
    "amico": ("amico", "uomo", None), "amica": ("amica", "donna", None),
    "collega": ("collega", None, "adulto"), "partner": ("partner", None, "adulto"),
    "uomo": ("uomo", "uomo", "adulto"), "donna": ("donna", "donna", "adulto"),
    "signore": ("signore", "uomo", "adulto"), "signora": ("signora", "donna", "adulto"),
    "anziano": ("anziano", "uomo", "anziano"), "anziana": ("anziana", "donna", "anziano"),
}
_REL_WORDS = "|".join(sorted((re.escape(word) for word in RELATIONS), key=len, reverse=True))
_FOR_OTHER = re.compile(
    r"\b(?:per|a|al|alla|allo|del|della|di)\s+(?:(?:il|la|lo|un|una|mio|mia|tuo|tua|suo|sua|nostro|nostra)\s+){0,2}"
    rf"(?P<rel>{_REL_WORDS})\b", re.IGNORECASE)
_SUBJECT_OTHER = re.compile(
    rf"\b(?:(?:il|la|lo)\s+)?(?:mio|mia|nostro|nostra)\s+(?P<rel>{_REL_WORDS})\b", re.IGNORECASE)
_LEAD_OTHER = re.compile(r"^\W*(?:il|la|lo)\s+(?P<rel>bambin[oa]|bimb[oa]|piccol[oa]|neonat[oa]|ragazzin[oa]|ragazz[oa])\b",
                         re.IGNORECASE)
_BARE_BAND = re.compile(r"\b(?:è|e)\s+(?:un|una)\s+(?P<rel>neonat[oa]|bambin[oa]|bimb[oa]|ragazzin[oa]|anzian[oa])\b",
                        re.IGNORECASE)
_SELF = re.compile(r"\b(?:(?:è|e)\s+)?per\s+me(?:\s+stess[oa])?\b|\blo\s+prendo\s+io\b|\bè\s+per\s+me\b", re.IGNORECASE)
_ANIMAL = re.compile(r"\b(?:per\s+)?(?:il|al|del|la|alla|mio|mia|nostro|nostra)\s+(?:mio\s+|mia\s+)?"
                     r"(?P<sp>cane|cagnolino|cagnolina|cagnetto|cucciolo|gatto|gatta|gattino|gattina|micio|micia)\b",
                     re.IGNORECASE)
_AGE_YEARS = re.compile(rf"\b(?:di|ha|ne\s+ha|compie|ho|avrà|che\s+ha)\s+{NUMBER}\s+anni(?:\s+e\s+mezzo)?\b",
                        re.IGNORECASE)
_AGE_MONTHS = re.compile(rf"\b(?:di|ha|ne\s+ha|che\s+ha)\s+{NUMBER}\s+mes[ei]\b", re.IGNORECASE)
_ONE_YEAR = re.compile(r"\b(?:di|ha)\s+un\s+anno\b", re.IGNORECASE)
_FEW_MONTHS = re.compile(r"\bpochi\s+mesi\b|\bappena\s+nat[oa]\b", re.IGNORECASE)
_PREGNANT = re.compile(r"\b(?P<neg>non\s+(?:sono|è|e|sei|più)\s+(?:più\s+)?)?(?:incinta|in\s+gravidanza|in\s+dolce\s+attesa)\b|"
                       r"\b(?P<neg2>non\s+)?aspett(?:o|a|iamo)\s+un\s+(?:bambino|bimbo|bambina|figlio)\b",
                       re.IGNORECASE)
_NURSING = re.compile(r"\b(?P<neg>non\s+(?:più\s+)?)?(?:allatt(?:o|a|iamo|ando)|in\s+allattamento|sto\s+allattando|"
                      r"sta\s+allattando)\b", re.IGNORECASE)
_SELF_ADJ = re.compile(r"\b(?:sono|mi\s+sento)\s+(?:molto\s+|un\s+po['’]\s+)?(?P<w>[a-zà-ù]+?)(?P<end>[oa])\b", re.IGNORECASE)
_SELF_ADJ_STEMS = ("stanc", "raffreddat", "stat", "andat", "agitat", "stressat", "preoccupat", "stufat", "bloccat",
                   "scottat", "tagliat", "stitic", "nervos", "gonfi", "affaticat", "ammalat", "caduto", "cadut",
                   "sveglia", "svegliat", "sudat", "debol", "depress")
_SPLIT = re.compile(r"(?<=[.!?;])\s+|\s+(?=anzi\b)|\s*,\s*(?=no\b)|\s+(?=no,)", re.IGNORECASE)


def band_for(years=None, months=None):
    total = months if months is not None else (years * 12 if years is not None else None)
    if total is None:
        return None
    if total < 12:
        return "neonato"
    if total < 144:
        return "bambino"
    if total < 216:
        return "adolescente"
    if total < 780:
        return "adulto"
    return "anziano"


def empty_profile():
    return {"kind": "sconosciuto", "relation": None, "gender": None, "age_years": None, "age_months": None,
            "age_band": None, "states": [], "species": None, "source": {}, "evidence": []}


def _age_from(text):
    # «incinta di tre mesi» is the pregnancy, not the age.
    text = re.sub(r"\b(?:incinta|gravidanza|attesa)\s+(?:di|al)\s+\S+\s+mes[ei]\b", "", text, flags=re.IGNORECASE)
    match = _AGE_MONTHS.search(text)
    if match:
        months = _italian_age(match[1].replace(",5", "").replace(".5", ""))
        if months is not None and months <= 36:
            return None, months
    if _ONE_YEAR.search(text):
        return 1, 12
    match = _AGE_YEARS.search(text)
    if match:
        value = match[1]
        years = _italian_age(value.split(",")[0].split(".")[0])
        if years is not None and years <= 120:
            half = "mezzo" in match.group(0) or value.endswith(("5",)) and ("," in value or "." in value)
            return years, years * 12 + (6 if half else 0)
    return None, None


def _set(profile, field, value, source):
    profile[field] = value
    profile["source"][field] = source


def _reset_person(profile, source, kind):
    for field in ("relation", "gender", "age_years", "age_months", "age_band", "species"):
        profile[field] = None
        profile["source"].pop(field, None)
    profile["states"] = []
    profile["source"].pop("states", None)
    _set(profile, "kind", kind, source)


def extract(text):
    """Profile from the full transcript. Later explicit statements override earlier ones."""
    profile = empty_profile()
    for sentence in [part for part in _SPLIT.split(text or "") if part and part.strip()]:
        lowered = sentence.casefold()
        if "?" in sentence:
            # A question is not a declaration («è per un bambino?»), but a customer may
            # declare first and ask after: «sono incinta, posso prenderlo?».
            head = sentence.rsplit(",", 1)[0] if "," in sentence else ""
            if not head.strip():
                continue
            sentence, lowered = head, head.casefold()
        animal = _ANIMAL.search(sentence)
        other = (_FOR_OTHER.search(sentence) or _SUBJECT_OTHER.search(sentence) or _LEAD_OTHER.search(sentence)
                 or _BARE_BAND.search(sentence))
        if animal and (not other or animal.start() <= other.start()):
            _reset_person(profile, "dichiarato", "animale")
            species = "cane" if re.match(r"ca[gn]|cucc", animal["sp"], re.IGNORECASE) else "gatto"
            _set(profile, "species", species, "dichiarato")
            profile["evidence"].append(animal.group(0).strip())
            continue
        if other and not re.search(r"\bnon\s+(?:è\s+)?per\s+" , lowered[:other.end()]):
            word = other["rel"].casefold()
            key = word if word in RELATIONS else word[:-1] + ("o" if word.endswith("o") else "a")
            relation, gender, band = RELATIONS.get(key, RELATIONS.get(word, (word, None, None)))
            _reset_person(profile, "dichiarato", "altra_persona")
            _set(profile, "relation", relation, "dichiarato")
            if gender:
                _set(profile, "gender", gender, "dichiarato")
            if band:
                _set(profile, "age_band", band, "dichiarato")
            profile["evidence"].append(other.group(0).strip())
        elif _SELF.search(sentence):
            if profile["kind"] != "sé":
                _reset_person(profile, "dichiarato", "sé")
            profile["evidence"].append(_SELF.search(sentence).group(0).strip())
        if profile["kind"] == "animale":
            continue
        years, months = _age_from(sentence)
        if months is not None and (profile["kind"] != "sconosciuto" or re.search(r"\bha\b|\bdi\b|\bho\b", lowered)):
            _set(profile, "age_years", years if years is not None else months // 12, "dichiarato")
            _set(profile, "age_months", months, "dichiarato")
            _set(profile, "age_band", band_for(months=months), "dichiarato")
            if profile["kind"] == "sconosciuto":
                _set(profile, "kind", "sé" if re.search(r"\bho\s", lowered) else "altra_persona", "dichiarato")
        elif _FEW_MONTHS.search(sentence):
            _set(profile, "age_band", "neonato", "dichiarato")
        for pattern, state in ((_PREGNANT, "gravidanza"), (_NURSING, "allattamento")):
            match = pattern.search(sentence)
            if not match:
                continue
            negated = bool(match.groupdict().get("neg") or match.groupdict().get("neg2"))
            states = [item for item in profile["states"] if item != state]
            if not negated:
                states.append(state)
                if profile["kind"] == "sconosciuto":
                    _set(profile, "kind", "sé" if re.search(r"\b(?:sono|aspetto|allatto|sto)\b", lowered)
                         else "altra_persona", "dichiarato")
                if profile["source"].get("gender") != "manuale":
                    _set(profile, "gender", "donna", "dichiarato")
                if not profile["age_band"]:
                    _set(profile, "age_band", "adulto", "dedotto")
            profile["states"] = states
            profile["source"]["states"] = "dichiarato"
            profile["evidence"].append(match.group(0).strip())
        if profile["kind"] in ("sé", "sconosciuto") and not profile["gender"]:
            for match in _SELF_ADJ.finditer(sentence):
                stem = match["w"].casefold()
                if any(stem.startswith(item) or (stem + match["end"]).startswith(item) for item in _SELF_ADJ_STEMS):
                    _set(profile, "gender", "donna" if match["end"].casefold() == "a" else "uomo", "dedotto")
                    break
    if profile["age_years"] is not None and not profile["source"].get("age_band") == "dichiarato":
        _set(profile, "age_band", band_for(profile["age_years"], profile["age_months"]), "dichiarato")
    return profile


def merge_manual(profile, manual):
    """Apply the pharmacist's quick choice on top of the transcript profile."""
    result = {**profile, "source": dict(profile.get("source") or {}), "states": list(profile.get("states") or [])}
    for field, value in (manual or {}).items():
        if field == "states":
            result["states"] = [item for item in value if item in STATES]
        else:
            result[field] = value
        result["source"][field] = "manuale"
    if (manual or {}).keys() & {"age_years", "age_months"} and "age_band" not in manual:
        result["age_band"] = band_for(months=result["age_months"])
        result["source"]["age_band"] = "manuale"
    return result


def validate_manual(payload):
    """Validate the quick choice from the desk chip."""
    if not isinstance(payload, dict):
        raise ValueError("Destinatario non valido.")
    allowed = {}
    kind = payload.get("kind")
    if kind is not None:
        if kind not in ("sé", "altra_persona", "animale", "sconosciuto"):
            raise ValueError("Tipo di destinatario non valido.")
        allowed["kind"] = kind
    gender = payload.get("gender")
    if gender is not None:
        if gender not in ("donna", "uomo", "altro", "non_detto"):
            raise ValueError("Genere non valido.")
        allowed["gender"] = gender
    for key, top in (("age_years", 120), ("age_months", 1440)):
        value = payload.get(key)
        if value is not None:
            if type(value) is not int or not 0 <= value <= top:
                raise ValueError("Età non valida.")
            allowed[key] = value
    if "age_years" in allowed and "age_months" not in allowed:
        allowed["age_months"] = allowed["age_years"] * 12
    band = payload.get("age_band")
    if band is not None:
        if band not in BANDS:
            raise ValueError("Fascia d'età non valida.")
        allowed["age_band"] = band
    states = payload.get("states")
    if states is not None:
        if not isinstance(states, list) or any(item not in STATES for item in states):
            raise ValueError("Stato non valido.")
        allowed["states"] = states
    species = payload.get("species")
    if species is not None:
        if species not in ("cane", "gatto"):
            raise ValueError("Specie non valida.")
        allowed["species"] = species
    return allowed


def filtering(profile):
    """Only declared or manual fields can exclude a product."""
    profile = profile or {}
    source = profile.get("source") or {}
    def ok(field):
        return source.get(field) in SOURCES_THAT_FILTER
    return {
        "age_months": profile.get("age_months") if ok("age_months") else None,
        "age_band": profile.get("age_band") if ok("age_band") else None,
        "gender": profile.get("gender") if ok("gender") and profile.get("gender") in ("donna", "uomo") else None,
        "states": list(profile.get("states") or []) if ok("states") else [],
        "species": profile.get("species") if ok("species") else None,
    }


def label(profile):
    """Short text for the desk chip, e.g. «bambina · 5 anni · dichiarato»."""
    profile = profile or {}
    if profile.get("kind") in (None, "sconosciuto") and not profile.get("states") and not profile.get("gender"):
        return None
    source = profile.get("source") or {}
    parts = []
    if profile.get("kind") == "animale":
        parts.append(profile.get("species") or "animale")
    elif profile.get("kind") == "sé":
        parts.append("sé")
    if profile.get("relation"):
        parts.append(profile["relation"])
    if profile.get("gender") and profile.get("relation") in (None, "uomo", "donna"):
        parts.append(profile["gender"] + ("?" if source.get("gender") == "dedotto" else ""))
    if profile.get("age_months") is not None and profile["age_months"] < 24:
        parts.append(f"{profile['age_months']} mesi")
    elif profile.get("age_years") is not None:
        parts.append(f"{profile['age_years']} anni")
    elif profile.get("age_band") and profile.get("age_band") not in parts and source.get("age_band") != "dedotto":
        parts.append(profile["age_band"])
    parts += list(profile.get("states") or [])
    origin = "manuale" if "manuale" in source.values() else (
        "da confermare" if source and all(value == "dedotto" for value in source.values()) else "dichiarato")
    return " · ".join(dict.fromkeys(parts + [origin]))
