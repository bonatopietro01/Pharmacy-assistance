"""Vendita guidata: ammissibilità, passi, complemento unico, offerte, feedback, import."""

import io
import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path

from backend import desk, import_dati, knowledge, protocolli, revisione, semantica, vendita
from backend.catalog_setup import migrate_latest, seed_symptom_associations

ROOT = Path(__file__).resolve().parents[1]
OPERATIVE = ROOT / "database" / "farmacia.sqlite3"


class SalesCatalogTest(unittest.TestCase):
    """A migrated copy of the operational catalog with a published protocol."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.catalog = self.dir / "farmacia.sqlite3"
        shutil.copy(OPERATIVE, self.catalog)
        migrate_latest(self.catalog)
        seed_symptom_associations(self.catalog, ROOT / "database" / "collegamenti-concetti-nuovi.json")
        import_dati.ages_from_relations(self.catalog, apply=True)
        with closing(sqlite3.connect(self.catalog)) as db, db:
            # A prescription-only product linked to "raffreddore", for the admissibility rule.
            db.execute("UPDATE prodotti SET regime_fornitura='RR' WHERE codice='REAL-MED-009'")
        page = (ROOT / "wiki" / "schede" / "protocollo-raffreddore.md").read_text(encoding="utf-8")
        page = page.replace('stato = "bozza"', 'stato = "pubblicata"').replace('revisore = ""', 'revisore = "Test"')
        page = page.replace('versione = ""', 'versione = "1"')
        self.protocol = self.dir / "protocollo-raffreddore.md"
        self.protocol.write_text(page, encoding="utf-8")
        protocolli.publish(self.protocol, self.catalog)
        self.now = 10

    def session(self):
        listening = desk.Listening(catalog=self.catalog, requests=self.dir / "requests.sqlite3",
                                   settings=self.dir / "settings.json", clock=lambda: self.now)
        self.addCleanup(listening.stop)
        started = listening.start(background=False)
        return listening, started["session_id"]

    def say(self, listening, session_id, text):
        listening.ingest(session_id, text, final=True)
        self.now += 4
        listening.evaluate()
        return listening.snapshot()

    def act(self, listening, action, payload=None):
        state = listening.snapshot()
        return listening.action({"session_id": state["session_id"], "expected_action_version": state["action_version"],
                                 "action": action, "payload": payload or {}})

    def approve_complements(self):
        with closing(revisione._connect(self.catalog)) as db, redirect_stdout(io.StringIO()):
            answers = iter(["a", ""] * 80)
            revisione.rivedi_complementi(db, "Test", ask=lambda _: next(answers, "q"))


class AdmissibilityTest(SalesCatalogTest):
    def test_prescription_product_is_never_proposed_from_a_symptom(self):
        listening, sid = self.session()
        state = self.say(listening, sid, "Buongiorno ho il raffreddore")
        codes = [row["code"] for row in state["desk_results"]["rows"]]
        self.assertNotIn("REAL-MED-009", codes)
        excluded = {item["code"]: item["reason"] for item in state["desk_results"]["excluded"]}
        self.assertIn("ricetta", excluded["REAL-MED-009"])

    def test_declared_age_below_minimum_excludes_with_reason(self):
        listening, sid = self.session()
        self.act(listening, "destinatario", {"kind": "altra_persona", "relation": "figlio",
                                             "declared_fields": {"age": 14}})
        state = self.say(listening, sid, "ho il raffreddore")
        codes = [row["code"] for row in state["desk_results"]["rows"]]
        self.assertNotIn("REAL-MED-006", codes)  # età minima 16 dal foglio illustrativo
        reasons = [item["reason"] for item in state["desk_results"]["excluded"] if item["code"] == "REAL-MED-006"]
        self.assertTrue(reasons and "16" in reasons[0])

    def test_rows_explain_their_position(self):
        listening, sid = self.session()
        state = self.say(listening, sid, "ho il raffreddore")
        self.assertTrue(state["desk_results"]["rows"])
        self.assertTrue(all(row.get("rank_reason") for row in state["desk_results"]["rows"]))


class SalesFlowTest(SalesCatalogTest):
    def test_cold_flow_questions_then_product_then_complement_then_offer(self):
        self.approve_complements()
        listening, sid = self.session()
        state = self.say(listening, sid, "Buongiorno ho il raffreddore")
        view = state["vendita"]
        self.assertEqual("inquadramento", view["step"])
        self.assertLessEqual(len(view["questions"]), 3)
        self.assertTrue(any(q["filter"] == "eta" for q in view["questions"]))
        _, state = self.act(listening, "salta_passo", {"step": "inquadramento"})
        self.assertEqual("proposta", state["vendita"]["step"])
        self.assertIsNone(state["vendita"]["complement"])  # niente complemento prima della conferma
        code = state["desk_results"]["rows"][0]["code"]
        _, state = self.act(listening, "conferma_prodotto", {"code": code})
        self.assertEqual("complemento", state["vendita"]["step"])
        complement = state["vendita"]["complement"]
        self.assertIsNotNone(complement)
        self.assertEqual("complementi_banco", complement["origin"])
        _, state = self.act(listening, "complemento", {"decision": "accettato"})
        self.assertEqual("offerta", state["vendita"]["step"])

    def test_without_approved_complements_a_candidate_opens_the_step_labelled(self):
        # 19 Nov 2026 (PROMPT_DATI_COMPLEMENTO_CAMERA): the step is never skipped in silence;
        # without approvals it opens with the best candidate, marked «non revisionato».
        listening, sid = self.session()
        self.say(listening, sid, "ho il raffreddore")
        self.act(listening, "salta_passo", {"step": "inquadramento"})
        code = listening.snapshot()["desk_results"]["rows"][0]["code"]
        _, state = self.act(listening, "conferma_prodotto", {"code": code})
        self.assertFalse(state["vendita"]["complement"]["reviewed"])
        self.assertEqual("complemento", state["vendita"]["step"])

    def test_named_but_not_confirmed_product_opens_no_complement(self):
        self.approve_complements()
        listening, sid = self.session()
        state = self.say(listening, sid, "ho il raffreddore, avete la tachipirina?")
        self.assertIsNone(state["product"]["confirmed_code"])
        self.assertIsNone(state["vendita"]["complement"])
        self.assertNotEqual("complemento", state["vendita"]["step"])

    def test_refusal_after_confirmation_returns_to_proposal(self):
        self.approve_complements()
        listening, sid = self.session()
        self.say(listening, sid, "ho il raffreddore")
        self.act(listening, "salta_passo", {"step": "inquadramento"})
        code = listening.snapshot()["desk_results"]["rows"][0]["code"]
        self.act(listening, "conferma_prodotto", {"code": code})
        _, state = self.act(listening, "correggi_prodotto", {"code": None})
        self.assertIsNone(state["product"]["confirmed_code"])
        self.assertIsNone(state["vendita"]["complement"])
        self.assertEqual("proposta", state["vendita"]["step"])

    def test_red_flag_stops_proposals_until_handled(self):
        listening, sid = self.session()
        state = self.say(listening, sid, "ho la tosse e mi manca il respiro")
        self.assertEqual("allarme", state["vendita"]["step"])
        self.assertTrue(state["vendita"]["proposals_blocked"])
        _, state = self.act(listening, "allarme_gestito")
        self.assertNotEqual("allarme", state["vendita"]["step"])

    def test_negated_red_flag_is_not_an_alarm(self):
        self.assertEqual([], vendita.detect_red_flags("ho la tosse ma non ho dolore al petto"))
        self.assertEqual(["petto"], [f["id"] for f in vendita.detect_red_flags("ho dolore al petto da ieri")])


class OfferRulesTest(SalesCatalogTest):
    def setUp(self):
        super().setUp()
        with closing(sqlite3.connect(self.catalog)) as db, db:
            db.execute("UPDATE prodotti SET quantita=5, quantita_fonte_id='SRC-SALES-DEMOBANCO-20261108' "
                       "WHERE codice IN ('REAL-MED-001','REAL-DM-003','REAL-MED-017')")
            for code, product in (("T-1", "REAL-MED-001"), ("T-2", "REAL-DM-003"), ("T-3", "REAL-MED-017"),
                                  ("T-OLD", "REAL-MED-001")):
                start, end = ("2026-01-01", "2026-01-31") if code == "T-OLD" else ("2026-01-01", "2099-12-31")
                db.execute("""INSERT INTO offerte (codice, prodotto_codice, titolo, criterio, prezzo_cent, inizio, fine,
                              stato, beneficio, disponibilita, criterio_tipo) VALUES (?,?,?,?,?,?,?,'attiva','',3,'prodotto')""",
                           (code, product, "Prova " + code, "prodotto", 100, start, end))

    def test_offers_only_for_products_in_the_conversation_and_at_most_two(self):
        listening, sid = self.session()
        self.say(listening, sid, "ho il raffreddore")
        stable = listening.snapshot()["evidence"]
        closing_cue = {"id": "x", "span": {"start": 0, "end": 0}}
        listening.state["product"]["confirmed_code"] = "REAL-MED-001"
        rows = listening._desk_offers(stable, closing_cue)
        codes = [row["code"] for row in rows]
        self.assertLessEqual(len(rows), 2)
        self.assertIn("REAL-MED-001", codes)
        self.assertNotIn("REAL-MED-017", codes)  # mai entrato nella conversazione
        self.assertEqual(["T-1"], [row["offer"]["codice"] for row in rows if row["code"] == "REAL-MED-001"])

    def test_expired_offer_is_not_listed(self):
        from datetime import date
        from backend.offers import active_offers
        listed = [row["codice"] for row in active_offers(date(2026, 11, 18), {"product_codes": {"REAL-MED-001"}},
                                                         self.catalog)]
        self.assertNotIn("T-OLD", listed)


class FeedbackAndAnalysisTest(SalesCatalogTest):
    def test_feedback_stores_no_text_and_feeds_the_weekly_analysis(self):
        listening, sid = self.session()
        self.say(listening, sid, "mia moglie ha il raffreddore e le cola il naso")
        self.act(listening, "salta_passo", {"step": "inquadramento"})
        code = listening.snapshot()["desk_results"]["rows"][0]["code"]
        self.act(listening, "conferma_prodotto", {"code": code})
        with closing(sqlite3.connect(self.catalog)) as db:
            columns = [row[1] for row in db.execute("PRAGMA table_info(feedback_banco)")]
            rows = db.execute("SELECT * FROM feedback_banco").fetchall()
        # v9 adds only «origine», a closed label (farmaco/sintomo): still no conversation text.
        self.assertEqual(["id", "creato_il", "concetto_id", "prodotto_codice", "complemento_id", "evento",
                          "protocollo_versione", "origine"], columns)
        self.assertTrue(rows)
        for row in rows:
            for value in row:
                self.assertNotIn("moglie", str(value))
                self.assertNotIn("naso", str(value))
        analysis = vendita.weekly_analysis(self.catalog)
        steps = {item["passo"]: item["n"] for item in analysis["imbuto"]}
        self.assertGreaterEqual(steps["Prodotto confermato"], 1)


class ImportTest(SalesCatalogTest):
    def write(self, name, text):
        folder = self.dir / "aifa"
        folder.mkdir(exist_ok=True)
        (folder / name).write_text(text, encoding="utf-8")
        return folder

    def test_aifa_import_changes_only_matching_rows_and_respects_reviewed_fields(self):
        with closing(sqlite3.connect(self.catalog)) as db, db:
            db.execute("""INSERT INTO fonti (id, titolo, ente, consultata_il, tipo)
                          VALUES ('SRC-FARMACISTA', 'Verifica al banco', 'Farmacia', '2026-11-18', 'farmacia')""")
            db.execute("UPDATE prodotti SET regime_fornitura='OTC', regime_fonte_id='SRC-FARMACISTA' "
                       "WHERE codice='REAL-MED-004'")
        folder = self.write("confezioni.csv", "codice_aic;descrizione_fornitura;codice_atc\n"
                                              "012745028;SOP;N02BE01\n041962010;RR;N02BA01\n")
        self.write("carenti.csv", "Codice AIC|Nome\n012745028|TACHIPIRINA\n")
        report = import_dati.import_aifa(folder, self.catalog, config={})
        with closing(sqlite3.connect(self.catalog)) as db:
            tachi = db.execute("SELECT regime_fornitura, atc, carente FROM prodotti WHERE codice='REAL-MED-001'").fetchone()
            aspirina = db.execute("SELECT regime_fornitura FROM prodotti WHERE codice='REAL-MED-004'").fetchone()
            others = db.execute("SELECT count(*) FROM prodotti WHERE regime_fonte_id='SRC-AIFA-ANAGRAFICA'").fetchone()
        self.assertEqual(("SOP", "N02BE01", 1), tachi)
        self.assertEqual(("OTC",), aspirina)  # campo verificato dal farmacista: non sovrascritto
        self.assertEqual((1,), others)
        self.assertEqual(2, report["applicati"])

    def test_gestionale_rejects_incomplete_rows_and_counts_them(self):
        path = self.dir / "export.csv"
        path.write_text("codice;prezzo;giacenza\nREAL-MED-001;4,90;12\nREAL-MED-002;;3\nSCONOSCIUTO;1,00;1\n",
                        encoding="utf-8")
        report = import_dati.import_gestionale(path, self.catalog, config={})
        self.assertEqual((1, 1, 1), (report["applicati"], report["rifiutati"], report["sconosciuti"]))
        status = {row["fonte"]: row for row in import_dati.import_status(self.catalog)}
        self.assertEqual("parziale", status["gestionale"]["esito"])


class OptionalPartsTest(SalesCatalogTest):
    def test_semantic_search_off_or_missing_changes_nothing(self):
        settings = self.dir / "conf.json"
        settings.write_text(json.dumps({"ricerca_semantica": {"attiva": False}}), encoding="utf-8")
        self.assertEqual("spenta", semantica.semantic_status(settings))
        self.assertIsNone(semantica.suggest_concept("mi gratto dappertutto", config=settings))

    def test_draft_protocol_cannot_be_published(self):
        with self.assertRaises(ValueError):
            protocolli.publish(ROOT / "wiki" / "schede" / "protocollo-raffreddore.md", self.catalog)

    def test_configuration_save_keeps_sections_of_other_tools(self):
        settings = self.dir / "settings.json"
        settings.write_text(json.dumps({"import": {"gestionale": {"chiave": "aic"}},
                                        "ricerca_semantica": {"attiva": True}}), encoding="utf-8")
        desk.save_configuration({"ritardo_secondi": 3, "pausa_secondi": 4, "fonti": {}}, settings)
        saved = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual({"chiave": "aic"}, saved["import"]["gestionale"])
        self.assertTrue(saved["ricerca_semantica"]["attiva"])


if __name__ == "__main__":
    unittest.main()
