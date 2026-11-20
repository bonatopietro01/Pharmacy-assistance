"""Misura la copertura del retrieval su frasi realistiche da banco.

Non è un test unitario: è un set di riferimento ("golden set") da far crescere
con le frasi che il farmacista sente davvero. Ogni riga dichiara cosa ci si
aspetta: un concetto (sintomo/bisogno) o un prodotto (prefisso di codice).
Le righe con concetti non ancora presenti nel catalogo restano volutamente nel
set: misurano il lavoro da fare su wiki e database.

Uso:  python -B tests/eval_retrieval.py            (riepilogo)
      python -B tests/eval_retrieval.py --verbose  (riga per riga)
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.conversation import analyze  # noqa: E402
from backend.knowledge import product_aliases, reference_material, search  # noqa: E402

# (frase, tipo atteso, valore atteso)
#   tipo "concetto": l'analisi deve produrre un topic con quel concept_id
#   tipo "prodotto": l'analisi o la ricerca devono restituire un codice con quel prefisso
#   tipo "escluso":  il concetto NON deve risultare attivo (negazione / passato)
GOLDEN = [
    # --- sintomi già modellati nel catalogo
    ("Ho un raffreddore tremendo, cosa mi dà?", "concetto", "raffreddore"),
    ("buongiorno ho la tosse da tre giorni cosa mi consiglia", "concetto", "tosse"),
    ("Ho il naso chiuso e non respiro", "concetto", "congestione-nasale"),
    ("Ho un mal di testa che non passa", "concetto", "mal-di-testa"),
    ("mi fa male la testa da stamattina", "concetto", "mal-di-testa"),
    ("Ho mangiato troppo e ho bruciore di stomaco", "concetto", "acidita-stomaco"),
    ("Mi bruciano gli occhi", "concetto", "irritazione-oculare"),
    ("Mio figlio ha la tosse e non dorme", "concetto", "tosse"),
    ("Il mio cane ha le pulci", "concetto", "parassiti-cane"),
    ("ho preso una botta al ginocchio", "concetto", "contusioni"),
    ("ho un livido sul braccio", "concetto", "ematomi"),
    ("ho il piede d'atleta", "concetto", "micosi-cutanee"),
    ("ho la rinite allergica", "concetto", "allergia-nasale"),
    # --- linguaggio colloquiale per concetti esistenti (sinonimi mancanti)
    ("Mi cola il naso da due giorni", "concetto", "raffreddore"),
    ("Ho il naso che cola e starnutisco", "concetto", "raffreddore"),
    ("Ho l'emicrania", "concetto", "mal-di-testa"),
    ("ho il naso tappato", "concetto", "congestione-nasale"),
    ("ho la gastrite", "concetto", "acidita-stomaco"),
    ("ho gli occhi rossi", "concetto", "irritazione-oculare"),
    ("ho preso una storta alla caviglia", "concetto", "dolore-muscolare"),
    # --- bisogni frequenti con prodotti GIÀ in catalogo ma senza concetto
    ("Ho mal di gola, mi brucia quando deglutisco", "concetto", "mal-di-gola"),
    ("Ho la febbre a 38", "concetto", "febbre"),
    ("Mi fa male la schiena da stamattina", "concetto", "dolore-muscolare"),
    ("Ho i dolori mestruali", "concetto", "dolore-mestruale"),
    ("Ho mal di denti", "concetto", "mal-di-denti"),
    ("Ho la diarrea da ieri", "concetto", "diarrea"),
    ("Sono stitico da una settimana", "concetto", "stitichezza"),
    ("Ho una puntura di zanzara che prude", "concetto", "punture-insetti"),
    ("Ho l'herpes sul labbro", "concetto", "herpes-labiale"),
    ("Ho le emorroidi", "concetto", "emorroidi"),
    ("Mi sento stanco, senza energie", "concetto", "stanchezza"),
    ("Non riesco a dormire", "concetto", "sonno"),
    ("Sto prendendo l'antibiotico, mi servono dei fermenti", "concetto", "fermenti-lattici"),
    ("Ho la pancia gonfia", "concetto", "gonfiore-addominale"),
    # --- prodotti per nome, principio attivo o storpiatura
    ("Avete la tachipirina?", "prodotto", "REAL-MED-00"),
    ("Cerco dell'ibuprofene", "prodotto", "REAL-MED-008"),
    ("Vorrei del paracetamolo", "prodotto", "REAL-MED-00"),
    ("Una aspirina per favore", "prodotto", "REAL-MED-00"),
    ("Avete il voltaren?", "prodotto", "REAL-MED-03"),
    ("mi serve il canesten in crema", "prodotto", "REAL-MED-038"),
    ("vorrei il nurofen", "prodotto", "REAL-MED-008"),
    ("avete il dicoflor in bustine", "prodotto", "REAL-SUP-008"),
    ("mi dà il fitonasal", "prodotto", "REAL-DM-003"),
    # --- negazioni e passato: il concetto non deve attivarsi
    ("non ho la tosse", "escluso", "tosse"),
    ("non ho né tosse né raffreddore", "escluso", "raffreddore"),
    ("avevo la tosse la settimana scorsa", "escluso", "tosse"),
    ("non è raffreddore", "escluso", "raffreddore"),
]


REAL_PHRASES = Path(__file__).with_name("frasi_banco.jsonl")


def real_phrases(path=REAL_PHRASES):
    """Frasi vere raccolte al banco (scritte a mano, senza dati del cliente)."""
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            rows.append((item["frase"], item.get("tipo", "concetto"), item["concetto"]))
    return rows


def topics_of(result):
    return {item.get("concept_id") for item in result["evidence"]
            if item["kind"] == "topic" and item.get("concept_id")}


def codes_of(result, text):
    codes = set(result.get("candidate_codes") or [])
    for item in result["evidence"]:
        if item.get("code"):
            codes.add(item["code"])
    for match in result.get("spoken_matches") or []:
        if isinstance(match, dict) and match.get("code"):
            codes.add(match["code"])
    for page in search(text)[:3]:
        if page.get("prodotto"):
            codes.add(page["prodotto"])
    return codes


def main(verbose=False):
    products, pages = reference_material()
    terms = product_aliases(products, pages)
    tally = {}
    misses = []
    started = time.perf_counter()
    golden = GOLDEN + real_phrases()
    for text, kind, expected in golden:
        result = analyze(text, terms)
        if kind == "concetto":
            ok = expected in topics_of(result)
        elif kind == "escluso":
            ok = expected not in topics_of(result)
        else:
            ok = any(code.startswith(expected) for code in codes_of(result, text))
        hit, total = tally.get(kind, (0, 0))
        tally[kind] = (hit + ok, total + 1)
        if not ok:
            misses.append((kind, expected, text))
        if verbose:
            print(f"{'OK ' if ok else 'NO '} [{kind}:{expected}] {text}")
    elapsed = (time.perf_counter() - started) * 1000 / len(golden)
    print("\nCopertura retrieval (golden set)")
    for kind, (hit, total) in tally.items():
        print(f"  {kind:9s} {hit:2d}/{total:<2d}  ({hit / total:.0%})")
    all_hit = sum(h for h, _ in tally.values())
    print(f"  totale    {all_hit:2d}/{len(golden):<2d}  ({all_hit / len(golden):.0%})   media {elapsed:.0f} ms/frase")
    if misses and not verbose:
        print("\nMancati:")
        for kind, expected, text in misses:
            print(f"  [{kind}:{expected}] {text}")
    return all_hit, len(golden)


if __name__ == "__main__":
    main(verbose="--verbose" in sys.argv)
