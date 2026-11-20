"""Schema v8 e vendita: bisogni nuovi, popolazioni, destinatario, complemento sempre visibile, offerte, revisione."""

import http.client
import json
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

from backend import desk, destinatario, knowledge, revisione_web, scheda_farmaco, vendita
from backend.catalog_setup import inspect_catalog, migrate_latest, seed_symptom_associations, seed_v8

ROOT = Path(__file__).resolve().parents[1]
OPERATIVE = ROOT / "database" / "farmacia.sqlite3"


class V8Catalog(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.catalog = self.dir / "farmacia.sqlite3"
        shutil.copy(OPERATIVE, self.catalog)
        migrate_latest(self.catalog)
        seed_symptom_associations(self.catalog, ROOT / "database" / "collegamenti-concetti-nuovi.json")
        seed_v8(self.catalog)
        self.wiki = self.dir / "wiki"
        self.wiki.mkdir()
        self.now = 10

    def session(self):
        listening = desk.Listening(catalog=self.catalog, requests=self.dir / "requests.sqlite3",
                                   settings=self.dir / "settings.json", clock=lambda: self.now)
        self.addCleanup(listening.stop)
        listening.start(background=False)
        return listening

    def say(self, listening, text):
        listening.ingest(listening.state["session_id"], text, final=True)
        self.now += 4
        listening.evaluate()
        return listening.snapshot()

    def act(self, listening, action, payload=None):
        state = listening.snapshot()
        return listening.action({"session_id": state["session_id"], "expected_action_version": state["action_version"],
                                 "action": action, "payload": payload or {}})


class SchemaTest(V8Catalog):
    def test_migration_and_seed_are_complete_and_idempotent(self):
        report = inspect_catalog(self.catalog)
        self.assertGreaterEqual(report["user_version"], 8)
        self.assertEqual(("ok", []), (report["integrity_check"], report["foreign_key_check"]))
        self.assertGreaterEqual(report["counts"]["concetti"], 53)
        self.assertGreaterEqual(report["counts"]["prodotto_popolazione"], 25)
        self.assertGreaterEqual(report["counts"]["complementi_banco"], 20)
        again = seed_v8(self.catalog)
        self.assertEqual((0, 0), (again["populations"], again["complements"]))
        with closing(sqlite3.connect(self.catalog)) as db:
            self.assertEqual(0, db.execute("""SELECT count(*) FROM relazioni_concetto_prodotto
                                              WHERE stato_revisione = 'approvata'""").fetchone()[0])
            self.assertEqual(0, db.execute("""SELECT count(*) FROM relazioni_concetto_prodotto
                                              WHERE fonte_id IS NULL""").fetchone()[0])

    def test_every_new_concept_has_lexicon_flags_and_protocol_draft(self):
        lexicon = json.loads((ROOT / "database" / "lessico-concetti.json").read_text(encoding="utf-8"))
        seed = json.loads((ROOT / "database" / "collegamenti-concetti-v8.json").read_text(encoding="utf-8"))
        for concept in seed["concepts"]:
            self.assertIn(concept["id"], lexicon["concetti"])
        new = [c["id"] for c in seed["concepts"] if c["id"] in {"tosse-secca", "cistite", "coliche-lattante"}]
        for concept_id in new:
            self.assertTrue((ROOT / "wiki" / "schede" / f"protocollo-{concept_id}.md").is_file())
        self.assertIn("cistite_complicata", lexicon["segnali_allarme"])


class RecipientTest(unittest.TestCase):
    def test_metrics_on_tuning_and_held_out_phrases(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("eval_destinatario", ROOT / "tests" / "eval_destinatario.py")
        evaluation = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(evaluation)
        for name in ("frasi_destinatario.jsonl", "frasi_destinatario_nuove.jsonl"):
            result = evaluation.evaluate(ROOT / "tests" / name)
            self.assertGreaterEqual(result["precisione"], 0.95, name)
            self.assertGreaterEqual(result["copertura"], 0.85, name)
            self.assertEqual(0, result["filtri_da_dedotti"], name)

    def test_inferred_gender_never_filters(self):
        profile = destinatario.extract("sono stanca morta")
        self.assertEqual(("donna", "dedotto"), (profile["gender"], profile["source"]["gender"]))
        self.assertIsNone(destinatario.filtering(profile)["gender"])
        self.assertIn("da confermare", destinatario.label(profile))

    def test_last_explicit_statement_wins_and_manual_overrides(self):
        profile = destinatario.extract("è per mia figlia di 6 anni. anzi no, per me")
        self.assertEqual("sé", profile["kind"])
        manual = destinatario.merge_manual(profile, destinatario.validate_manual({"states": ["gravidanza"]}))
        self.assertEqual(["gravidanza"], destinatario.filtering(manual)["states"])
        with self.assertRaises(ValueError):
            destinatario.validate_manual({"gender": "x"})


class PopulationTest(V8Catalog):
    def display(self, code):
        return knowledge.product_display(code, catalog=self.catalog)["display"]

    def test_child_excludes_adult_formula_and_promotes_paediatric(self):
        child = destinatario.filtering(destinatario.extract("per mio figlio di 5 anni"))
        verdict = knowledge.admissibility(self.display("REAL-DM-001"), None, child)
        self.assertFalse(verdict["allowed"])
        paediatric = knowledge.admissibility(self.display("REAL-DM-004"), None, child)
        self.assertTrue(paediatric["allowed"])
        self.assertEqual(1, paediatric["boost"])

    def test_pregnancy_excludes_contraindicated_device(self):
        pregnant = destinatario.filtering(destinatario.extract("sono incinta"))
        self.assertFalse(knowledge.admissibility(self.display("REAL-DM-007"), None, pregnant)["allowed"])
        self.assertTrue(knowledge.admissibility(self.display("REAL-DM-007"), None, {})["allowed"])

    def test_man_never_gets_vaginal_ovules(self):
        man = destinatario.filtering(destinatario.extract("per mio marito"))
        self.assertFalse(knowledge.admissibility(self.display("REAL-MED-049"), None, man)["allowed"])
        inferred = destinatario.filtering(destinatario.extract("sono stato male"))
        self.assertTrue(knowledge.admissibility(self.display("REAL-MED-049"), None, inferred)["allowed"])

    def test_supplements_follow_population(self):
        base = {"desk_results": {"rows": []}, "cart": {"items": []}, "transcript": {"testo": ""}}
        codes = lambda state: [item["code"] for item in vendita.linked_supplements(state, self.catalog, ["REAL-SUP-016"])]
        # Pregnancy supplement only with declared pregnancy; melatonin hidden in pregnancy.
        plain = vendita.linked_supplements({**base, "evidence": []}, self.catalog, ["REAL-MED-006"])
        self.assertNotIn("REAL-SUP-005", [item["code"] for item in plain])
        pregnant = {**base, "recipient_profile": destinatario.extract("sono incinta")}
        sleepy = vendita.linked_supplements(pregnant, self.catalog, ["REAL-DM-001"])
        self.assertNotIn("REAL-SUP-018", [item["code"] for item in sleepy])
        self.assertIsInstance(codes(base), list)


class SalesFlowTest(V8Catalog):
    def test_confirmation_always_opens_complement_with_candidate(self):
        listening = self.session()
        self.say(listening, "buongiorno ho il raffreddore")
        status, state = self.act(listening, "conferma_prodotto", {"code": "REAL-MED-006"})
        self.assertEqual(200, status)
        view = state["vendita"]
        self.assertEqual("complemento", view["step"])
        self.assertFalse(view["complement"]["reviewed"])
        self.assertEqual(3, view["complement"]["level"])
        status, state = self.act(listening, "complemento", {"decision": "accettato"})
        self.assertIn(view["complement"]["code"], [item["code"] for item in state["cart"]["items"]])

    def test_without_any_link_the_step_says_so(self):
        listening = self.session()
        self.say(listening, "ho la micosi ai piedi")
        _, state = self.act(listening, "conferma_prodotto", {"code": "REAL-MED-038"})
        self.assertTrue(state["vendita"]["complement_empty"])
        self.assertEqual("offerta", state["vendita"]["step"])

    def test_one_approval_makes_the_complement_reviewed(self):
        item = next(entry for entry in revisione_web.queue(self.catalog, self.wiki, kind="complemento",
                                                           concept="raffreddore")
                    if "Supradyn" in entry["title"])
        revisione_web.decide("complemento", item["key"], "approva", "Dott.ssa Prova", self.catalog, self.wiki)
        listening = self.session()
        self.say(listening, "ho il raffreddore")
        _, state = self.act(listening, "conferma_prodotto", {"code": "REAL-MED-006"})
        self.assertEqual("complemento", state["vendita"]["step"])
        self.assertTrue(state["vendita"]["complement"]["reviewed"])

    def test_selection_shows_supplement_and_offers(self):
        scheda_farmaco.crea_offerta("REAL-MED-006", {"titolo": "Seconda confezione -50%", "beneficio": "-50% sulla seconda",
                                                     "inizio": "2026-01-01", "fine": "2099-12-31"},
                                    self.catalog, "Dott.ssa Prova")
        listening = self.session()
        self.say(listening, "ho il raffreddore")
        _, state = self.act(listening, "seleziona_prodotto", {"code": "REAL-MED-006"})
        info = state["desk_results"]["with_product"]
        self.assertEqual("REAL-MED-006", info["code"])
        self.assertTrue(info["supplement"])
        self.assertEqual("sul prodotto scelto", info["offers"][0]["reason"])
        _, state = self.act(listening, "seleziona_prodotto", {"code": "REAL-DM-003"})
        self.assertTrue(state["desk_results"]["with_product"]["offers_empty"])

    def test_child_recipient_on_the_desk(self):
        listening = self.session()
        state = self.say(listening, "è per mio figlio di 5 anni, ha la tosse secca")
        self.assertEqual("bambino", state["recipient_profile"]["age_band"])
        codes = [row["code"] for row in state["desk_results"]["rows"]]
        self.assertNotIn("REAL-DM-001", codes)
        excluded = {item["code"] for item in state["desk_results"]["excluded"]}
        self.assertIn("REAL-DM-001", excluded)

    def test_manual_choice_rechecks_rows(self):
        listening = self.session()
        state = self.say(listening, "ho la tosse secca")
        self.assertIn("REAL-DM-001", [row["code"] for row in state["desk_results"]["rows"]])
        _, state = self.act(listening, "profilo_destinatario", {"kind": "altra_persona", "age_years": 6})
        self.assertNotIn("REAL-DM-001", [row["code"] for row in state["desk_results"]["rows"]])
        self.assertIn("manuale", state["recipient_profile"]["label"])

    def test_population_red_flag(self):
        listening = self.session()
        state = self.say(listening, "è per mio marito, ha la cistite")
        self.assertIn("pop_cistite", [flag["id"] for flag in state["vendita"]["red_flags"]])


class ReviewTest(V8Catalog):
    def test_name_note_and_fields_are_required(self):
        item = revisione_web.queue(self.catalog, self.wiki, kind="relazione", concept="crampi")[0]
        with self.assertRaises(ValueError):
            revisione_web.decide("relazione", item["key"], "approva", "", self.catalog, self.wiki)
        with self.assertRaises(ValueError):
            revisione_web.decide("relazione", item["key"], "respingi", "Prova", self.catalog, self.wiki)
        with self.assertRaises(ValueError):  # «rischi» empty in the seed
            revisione_web.decide("relazione", item["key"], "approva", "Prova", self.catalog, self.wiki)
        revisione_web.decide("relazione", item["key"], "approva", "Prova", self.catalog, self.wiki,
                             fields={"rischi": "Insufficienza renale: chiedere al medico."})
        with closing(sqlite3.connect(self.catalog)) as db:
            state = db.execute("""SELECT stato_revisione, revisore FROM relazioni_concetto_prodotto
                                  WHERE concetto_id='crampi' AND prodotto_codice=?""",
                               (item["key"].split("|")[1],)).fetchone()
            self.assertEqual(("approvata", "Prova"), state)
            self.assertTrue(db.execute("SELECT 1 FROM registro_revisioni WHERE revisore='Prova'").fetchone())

    def test_protocol_approval_publishes(self):
        source = ROOT / "wiki" / "schede" / "protocollo-crampi.md"
        (self.wiki / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        result = revisione_web.decide("protocollo", source.name, "approva", "Prova", self.catalog, self.wiki)
        self.assertEqual("pubblicata", result["state"])
        self.assertIn('stato = "pubblicata"', (self.wiki / source.name).read_text(encoding="utf-8"))
        protocols = vendita.protocol_for(["crampi"], self.catalog)
        self.assertTrue(protocols["crampi"]["questions"])


class HttpV8Test(V8Catalog):
    def setUp(self):
        super().setUp()
        listening = desk.Listening(catalog=self.catalog, requests=self.dir / "requests.sqlite3",
                                   settings=self.dir / "settings.json")
        self.addCleanup(listening.stop)
        handler = type("Handler", (desk.Desk,), {"listening": listening})
        self.server = desk.LocalServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        for name, value in (("PORT", self.port), ("ORIGIN", f"http://127.0.0.1:{self.port}")):
            self.addCleanup(setattr, desk, name, getattr(desk, name))
            setattr(desk, name, value)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, origin=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Host": f"127.0.0.1:{self.port}", "Content-Type": "application/json"}
        if origin:
            headers["Origin"] = f"http://127.0.0.1:{self.port}"
        conn.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data

    def test_pages_queue_and_origin(self):
        for path in ("/revisione", "/revisione.js", "/barcode1d.js"):
            self.assertEqual(200, self.request("GET", path)[0], path)
        status, body = self.request("GET", "/api/revisione?tipo=complemento")
        self.assertEqual(200, status)
        self.assertTrue(json.loads(body)["voci"])
        self.assertEqual(400, self.request("GET", "/api/revisione?tipo=altro")[0])
        self.assertEqual(403, self.request("POST", "/api/revisione/decidi", {}, origin=False)[0])
        self.assertEqual(400, self.request("POST", "/api/revisione/decidi", {"tipo": "complemento", "chiave": "1",
                                                                             "decisione": "approva"})[0])

    def test_camera_reader_field(self):
        status, _ = self.request("POST", "/api/farmaco/codice", {"codice": "A024823080", "origine": "telecamera",
                                                                  "lettore": "integrato"})
        self.assertEqual(200, status)
        self.assertEqual("integrato", scheda_farmaco.CAMERA_STATUS["lettore"])
        status, _ = self.request("POST", "/api/farmaco/codice", {"codice": "A024823080", "lettore": "<img>"})
        self.assertEqual(400, status)


@unittest.skipUnless(shutil.which("node"), "Node non installato")
class DecoderTest(unittest.TestCase):
    def test_builtin_decoder(self):
        result = subprocess.run(["node", str(ROOT / "tests" / "barcode1d.test.js")], capture_output=True, text=True,
                                timeout=120)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
