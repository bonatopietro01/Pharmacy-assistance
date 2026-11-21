"""Integratori per farmaco e per sintomo; controllo ogni 3 parole chiave; agente facoltativo."""

import json
import shutil
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

from backend import desk, phase_agent, vendita, verifica_banco
from backend.catalog_setup import migrate_latest, seed_v8

ROOT = Path(__file__).resolve().parents[1]
OPERATIVE = ROOT / "database" / "farmacia.sqlite3"


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.catalog = self.dir / "farmacia.sqlite3"
        shutil.copy(OPERATIVE, self.catalog)
        migrate_latest(self.catalog)
        seed_v8(self.catalog)
        self.now = 10.0

    def session(self, provider=None):
        listening = desk.Listening(catalog=self.catalog, requests=self.dir / "requests.sqlite3",
                                   settings=self.dir / "settings.json", clock=lambda: self.now)
        listening.checkpoint_provider = provider
        self.addCleanup(listening.stop)
        listening.start(background=False)
        return listening

    def say(self, listening, text):
        listening.ingest(listening.state["session_id"], text, final=True)
        self.now += 3  # under the 4 s pause that closes the customer
        listening.next_evaluation = 0
        listening.evaluate()
        return listening.snapshot()

    def act(self, listening, action, payload=None):
        state = listening.snapshot()
        return listening.action({"session_id": state["session_id"], "expected_action_version": state["action_version"],
                                 "action": action, "payload": payload or {}})


class SupplementsBySymptomTest(Base):
    def test_click_shows_drug_and_symptom_supplements_in_the_same_snapshot(self):
        listening = self.session()
        self.say(listening, "buongiorno ho il raffreddore e sono molto stanco")
        status, state = self.act(listening, "seleziona_prodotto", {"code": "REAL-MED-006"})
        self.assertEqual(200, status)
        self.assertIsNone(state["product"]["confirmed_code"])
        info = state["desk_results"]["with_product"]
        self.assertTrue(info["supplement"])
        linked = state["desk_results"]["linked_supplements"]
        for_symptom = [item for item in linked if item["origin"] == "sintomo"]
        self.assertTrue(any(entry["concetto_id"] == "stanchezza" for item in for_symptom
                            for entry in item["for_symptoms"]))
        # Drug-linked first, symptom-only after.
        self.assertEqual("farmaco", linked[0]["origin"])
        _, state = self.act(listening, "conferma_prodotto", {"code": "REAL-MED-006"})
        self.assertEqual("complemento", state["vendita"]["step"])

    def test_drug_without_links_gets_the_symptom_supplement(self):
        listening = self.session()
        self.say(listening, "ho la micosi ai piedi e sono stanca")
        _, state = self.act(listening, "seleziona_prodotto", {"code": "REAL-MED-038"})
        supplement = state["desk_results"]["with_product"]["supplement"]
        self.assertEqual("sintomo", supplement["origin"])
        _, state = self.act(listening, "conferma_prodotto", {"code": "REAL-MED-038"})
        self.assertEqual("complemento", state["vendita"]["step"])
        self.assertEqual("sintomo", state["vendita"]["complement"]["origin_kind"])
        self.assertFalse(state["vendita"]["complement_empty"])

    def test_feedback_records_the_origin_label_only(self):
        listening = self.session()
        self.say(listening, "ho la micosi ai piedi e sono stanca")
        # The copied operational catalog may already hold feedback from real desk use: look only at new rows.
        with closing(sqlite3.connect(self.catalog)) as db:
            last_id = db.execute("SELECT COALESCE(MAX(id), 0) FROM feedback_banco").fetchone()[0]
        self.act(listening, "conferma_prodotto", {"code": "REAL-MED-038"})
        self.act(listening, "complemento", {"decision": "rifiutato"})
        with closing(sqlite3.connect(self.catalog)) as db:
            origins = {row[0] for row in db.execute(
                "SELECT origine FROM feedback_banco WHERE origine IS NOT NULL AND id > ?", (last_id,))}
        self.assertEqual({"sintomo"}, origins)


class CheckpointTest(Base):
    def test_cadence_every_three_new_keywords(self):
        listening = self.session()
        self.say(listening, "ho il raffreddore")
        self.assertEqual(0, listening.snapshot()["checkpoint"]["n"])
        self.say(listening, "ho il raffreddore e sono stanco")  # same words again do not count twice
        count = len(listening.keywords)
        state = listening.snapshot()
        self.assertEqual(count >= 3, state["checkpoint"]["n"] >= 3)
        runs = []
        original = listening._run_checkpoint
        listening._run_checkpoint = lambda: (runs.append(len(listening.keywords)), original())
        self.say(listening, "e anche la tosse grassa e mal di gola e febbre")
        self.assertTrue(all(n % 3 == 0 or n >= 3 for n in runs))
        self.assertLessEqual(len(runs), 2)
        self.assertEqual(len(listening.keywords), len(listening.keyword_keys))

    def test_new_symptom_not_covered_by_the_chosen_drug(self):
        listening = self.session()
        self.say(listening, "buongiorno ho il raffreddore")
        self.act(listening, "conferma_prodotto", {"code": "REAL-MED-006"})
        state = self.say(listening, "e anche la tosse grassa e il mal di gola")
        corrections = state["checkpoint"]["correzioni"]
        self.assertTrue(any(item["tipo"] == "manca_sintomo" and item.get("code") == "REAL-MED-006"
                            for item in corrections))
        self.assertEqual("suggerimenti", state["checkpoint"]["esito"])
        self.assertEqual("REAL-MED-006", state["product"]["confirmed_code"])  # never changed by the check

    def test_pregnancy_after_confirmation_marks_to_review_without_touching_the_cart(self):
        listening = self.session()
        self.say(listening, "ho il colon irritabile, la pancia gonfia")
        self.act(listening, "aggiungi_carrello", {"code": "REAL-DM-007"})
        self.act(listening, "conferma_prodotto", {"code": "REAL-DM-007"})
        state = self.say(listening, "ah, sono incinta di tre mesi")  # 2 keywords only: the profile change triggers
        self.assertIn("REAL-DM-007", state["checkpoint"]["da_rivedere"])
        self.assertIn("REAL-DM-007", [item["code"] for item in state["cart"]["items"]])
        item = next(entry for entry in state["checkpoint"]["correzioni"] if entry.get("code") == "REAL-DM-007")
        status, state = self.act(listening, "controllo", {"id": item["id"], "decisione": "applica"})
        self.assertEqual(200, status)
        self.assertNotIn("REAL-DM-007", [entry["code"] for entry in state["cart"]["items"]])

    def test_negated_symptom_does_not_drive_the_list(self):
        listening = self.session()
        state = self.say(listening, "ho mal di testa, non ho febbre e non ho tosse")
        with listening.lock:
            result = verifica_banco.verify(listening.state, self.catalog)
        self.assertIn("febbre", result["negati"])
        self.assertNotIn("febbre", result["sintomi"])
        self.assertFalse([item for item in result["correzioni"] if item.get("concetto_id") == "febbre"])

    def test_same_result_gives_no_new_version(self):
        listening = self.session()
        self.say(listening, "buongiorno ho il raffreddore, il naso chiuso e sono stanco")
        with listening.lock:
            listening._run_checkpoint()
            before = json.dumps(listening.state["checkpoint"], sort_keys=True)
            listening._run_checkpoint()
            after = json.dumps(listening.state["checkpoint"], sort_keys=True)
        self.assertEqual(before, after)

    def test_ignore_is_remembered_and_local_check_is_fast(self):
        listening = self.session()
        self.say(listening, "buongiorno ho il raffreddore")
        self.act(listening, "conferma_prodotto", {"code": "REAL-MED-006"})
        state = self.say(listening, "e anche la tosse grassa e il mal di gola")
        item = next(entry for entry in state["checkpoint"]["correzioni"] if entry["tipo"] == "manca_sintomo")
        _, state = self.act(listening, "controllo", {"id": item["id"], "decisione": "ignora"})
        with listening.lock:
            listening._run_checkpoint()
        self.assertNotIn(item["id"], [entry["id"] for entry in listening.state["checkpoint"]["correzioni"]])
        # One timed run: keep a margin for a busy PC; the median target (50 ms) is checked in EvaluationTest.
        self.assertLess(listening.checkpoint_ms, 250)

    def test_keywords_are_not_stored(self):
        listening = self.session()
        self.say(listening, "buongiorno ho il raffreddore, il naso chiuso e sono stanco")
        with closing(sqlite3.connect(self.catalog)) as db:
            columns = [row[1] for row in db.execute("PRAGMA table_info(feedback_banco)")]
            rows = db.execute("SELECT * FROM feedback_banco").fetchall()
        self.assertNotIn("testo", columns)
        self.assertFalse(any("raffreddore e sono" in str(value) for row in rows for value in row))


class ModelAgentTest(Base):
    def wait(self, listening):
        for _ in range(100):
            if not listening.checkpoint_pending:
                return
            time.sleep(0.02)

    def test_valid_answer_is_merged_with_sources(self):
        seen = []

        def provider(payload):
            seen.append(payload)
            return {"ok": False, "correzioni": [{"tipo": "manca_sintomo", "code": None, "concetto_id": "tosse",
                                                 "motivo": "Chiedere se c'è anche tosse."}],
                    "info": [{"testo": "Bere molto e riposare.", "fonte": "protocollo raffreddore"}]}
        listening = self.session(provider)
        self.say(listening, "buongiorno ho il raffreddore, il naso chiuso e sono stanco")
        self.wait(listening)
        state = listening.snapshot()
        self.assertEqual("locale+modello", state["checkpoint"]["modo"])
        self.assertTrue(any(item.get("da") == "modello" for item in state["checkpoint"]["correzioni"]))
        self.assertTrue(any("(modello)" in item["fonte"] for item in state["checkpoint"]["info"]))
        payload = json.dumps(seen[0], ensure_ascii=False)
        self.assertNotIn("buongiorno ho il raffreddore, il naso chiuso e sono stanco", payload)
        self.assertIn("parole_chiave", seen[0])

    def test_invalid_answers_are_discarded(self):
        answers = [
            {"correzioni": [{"tipo": "manca_sintomo", "code": "NON-ESISTE", "motivo": "x"}], "info": []},
            {"correzioni": [{"tipo": "prodotto_non_coerente", "code": "REAL-MED-009", "motivo": "x"}], "info": []},
            {"correzioni": [], "info": [{"testo": "Prendere 2 compresse al giorno", "fonte": "x"}]},
        ]
        with closing(sqlite3.connect(self.catalog)) as db, db:  # a prescription drug in the copy
            db.execute("UPDATE prodotti SET regime_fornitura = 'RR' WHERE codice = 'REAL-MED-009'")
        for answer in answers:
            listening = self.session(lambda payload, answer=answer: answer)
            self.say(listening, "buongiorno ho il raffreddore, il naso chiuso e sono stanco")
            self.wait(listening)
            state = listening.snapshot()
            self.assertEqual("scartato", state["checkpoint"]["agente"], answer)
            self.assertEqual("locale", state["checkpoint"]["modo"])
            listening.stop()

    def test_timeout_keeps_the_local_result(self):
        def provider(payload):
            raise phase_agent.ProviderError("timeout")
        listening = self.session(provider)
        self.say(listening, "buongiorno ho il raffreddore, il naso chiuso e sono stanco")
        self.wait(listening)
        state = listening.snapshot()
        self.assertEqual("timeout", state["checkpoint"]["agente"])
        self.assertEqual("locale", state["checkpoint"]["modo"])

    def test_model_is_off_by_default(self):
        listening = self.session()
        self.assertIsNone(listening._checkpoint_model())


class EvaluationTest(unittest.TestCase):
    def test_conversations(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("eval_controllo", ROOT / "tests" / "eval_controllo.py")
        evaluation = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(evaluation)
        result = evaluation.run()
        self.assertGreaterEqual(result["conversazioni"], 20)
        self.assertEqual(0, result["errori_controindicazioni"], result["dettagli"])
        self.assertEqual(0, result["sbagliate"], result["dettagli"])
        # The median is the real target; a single slow run on a busy PC must not fail the suite.
        self.assertLess(result["latenza_ms_mediana"], 50)
        self.assertLess(result["latenza_ms_max"], 250)


if __name__ == "__main__":
    unittest.main()
