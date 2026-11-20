"""Valuta il riconoscimento del destinatario su tests/frasi_destinatario.jsonl.

    python tests/eval_destinatario.py [--mostra]

Per ogni campo atteso misura precisione (valori dichiarati corretti / valori dichiarati)
e copertura (campi attesi trovati). Un campo «dedotto» non conta come dichiarato e non
deve mai filtrare: lo controlla `destinatario.filtering`.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import destinatario  # noqa: E402

FIELDS = ("kind", "gender", "age_band", "age_years", "states", "species")


def evaluate(path=ROOT / "tests" / "frasi_destinatario.jsonl"):
    """`frasi_destinatario.jsonl` è servito a tarare le regole; `frasi_destinatario_nuove.jsonl` no."""
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    hits = found = expected = wrong_filters = predicted = predicted_ok = 0
    misses = []
    for row in rows:
        profile = destinatario.extract(row["testo"])
        want = row["atteso"]
        for field, value in want.items():
            if field == "gender_source":
                ok = (profile["source"].get("gender") == value)
                expected += 1
                hits += ok
                if not ok:
                    misses.append((row["testo"], field, value, profile["source"].get("gender")))
                continue
            got = profile.get(field)
            if field == "states":
                got = sorted(got)
                value = sorted(value)
            expected += 1
            ok = got == value or (value is None and got is None)
            hits += ok
            if got not in (None, []):
                predicted += 1
                predicted_ok += ok
            if not ok:
                misses.append((row["testo"], field, value, got))
        filters = destinatario.filtering(profile)
        if profile["source"].get("gender") == "dedotto" and filters["gender"]:
            wrong_filters += 1
    precision = predicted_ok / max(predicted, 1)
    coverage = hits / max(expected, 1)
    return {"frasi": len(rows), "campi_attesi": expected, "corretti": hits, "precisione": round(precision, 3),
            "copertura": round(coverage, 3), "filtri_da_dedotti": wrong_filters, "mancati": misses}


if __name__ == "__main__":
    files = [arg for arg in sys.argv[1:] if arg.endswith(".jsonl")]
    result = evaluate(files[0]) if files else evaluate()
    shown = result if "--mostra" in sys.argv else {k: v for k, v in result.items() if k != "mancati"}
    print(json.dumps(shown, ensure_ascii=False, indent=1))
    if "--mostra" not in sys.argv and result["mancati"]:
        print(f"{len(result['mancati'])} campi mancati: usa --mostra")
