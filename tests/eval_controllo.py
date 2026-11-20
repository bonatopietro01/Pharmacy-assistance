"""Valuta il controllo ogni 3 parole chiave su tests/conversazioni_controllo.jsonl.

    python tests/eval_controllo.py [--mostra]

Per ogni conversazione simula i turni al banco (con eventuali conferme ✓), poi forza
l'ultimo controllo e confronta correzioni e «da rivedere» con l'atteso.
Misura: correzioni giuste, correzioni sbagliate, errori su controindicazioni
(«da rivedere» mancati o in più: obiettivo 0) e latenza del verificatore locale.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import desk  # noqa: E402
from backend.catalog_setup import migrate_latest  # noqa: E402


def run(path=ROOT / "tests" / "conversazioni_controllo.jsonl", catalog=ROOT / "database" / "farmacia.sqlite3"):
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    folder = Path(tempfile.mkdtemp())
    copy = folder / "farmacia.sqlite3"
    shutil.copy(catalog, copy)
    migrate_latest(copy)
    right = wrong = missed = contraindication_errors = 0
    timings, details = [], []
    for conversation in rows:
        now = [10.0]
        listening = desk.Listening(catalog=copy, requests=folder / f"{conversation['id']}.sqlite3",
                                   settings=folder / "settings.json", clock=lambda: now[0])
        listening.start(background=False)
        for turn in conversation["turni"]:
            if isinstance(turn, dict):
                state = listening.snapshot()
                listening.action({"session_id": state["session_id"], "expected_action_version": state["action_version"],
                                  "action": "conferma_prodotto", "payload": {"code": turn["conferma"]}})
                continue
            listening.ingest(listening.state["session_id"], turn, final=True)
            now[0] += 3
            listening.next_evaluation = 0
            listening.evaluate()
        with listening.lock:
            listening._run_checkpoint()
            checkpoint = dict(listening.state["checkpoint"])
            timings.append(listening.checkpoint_ms)
        listening.stop()
        got = {(item["tipo"], item.get("code")) for item in checkpoint["correzioni"] if not item.get("automatica")
               and item["tipo"] == "manca_sintomo"}
        want = {tuple(item) for item in conversation["atteso"]["correzioni"]}
        review_got, review_want = set(checkpoint["da_rivedere"]), set(conversation["atteso"]["da_rivedere"])
        right += len(got & want) + len(review_got & review_want)
        wrong += len(got - want) + len(review_got - review_want)
        missed += len(want - got) + len(review_want - review_got)
        contraindication_errors += len(review_got ^ review_want)
        if got != want or review_got != review_want:
            details.append({"id": conversation["id"], "correzioni": sorted(map(str, got)), "attese": sorted(map(str, want)),
                            "da_rivedere": sorted(review_got), "attesi": sorted(review_want)})
    timings.sort()
    return {"conversazioni": len(rows), "giuste": right, "sbagliate": wrong, "mancate": missed,
            "errori_controindicazioni": contraindication_errors,
            "latenza_ms_mediana": timings[len(timings) // 2] if timings else None,
            "latenza_ms_max": timings[-1] if timings else None, "dettagli": details}


if __name__ == "__main__":
    result = run()
    if "--mostra" not in sys.argv:
        result.pop("dettagli")
    print(json.dumps(result, ensure_ascii=False, indent=1))
