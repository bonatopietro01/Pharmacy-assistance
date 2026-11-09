import json
import sqlite3
from contextlib import closing
from threading import Event, Thread
from unittest.mock import patch

from backend import desk
from test_offers import CatalogTest


class SyntheticRecognizer:
    def AcceptWaveform(self, audio):
        return audio == b"final"

    def Result(self):
        return '{"text":"segmento"}'

    def PartialResult(self):
        return '{"partial":"ipotesi"}'


class SessionTest(CatalogTest):
    def setUp(self):
        super().setUp()
        self.assertTrue(hasattr(desk.Listening, "ingest"), "Live transcription API unavailable")
        self.now = 10
        self.settings = self.catalog.with_suffix(".json")
        self.requests = self.catalog.with_name("requests.sqlite3")
        self.session = desk.Listening(catalog=self.catalog, requests=self.requests, settings=self.settings,
                                      clock=lambda: self.now)
        self.addCleanup(self.session.stop)
        self.started = self.session.start(background=False)
        self.session_id = self.started["session_id"]

    def action(self, action, payload=None, snapshot=None):
        state = snapshot or self.session.snapshot()
        return self.session.action({"session_id": state["session_id"], "expected_action_version": state["action_version"],
                                    "action": action, "payload": payload or {}})

    def test_recognition_reads_partial_before_any_final(self):
        recognizer = SyntheticRecognizer()
        self.assertEqual(("ipotesi", False), desk.recognize(recognizer, b"continuous"))
        self.assertEqual(("segmento", True), desk.recognize(recognizer, b"final"))

    def test_partial_replaces_while_final_segments_remain(self):
        self.session.ingest(self.session_id, "prima")
        self.session.ingest(self.session_id, "seconda")
        self.assertEqual("seconda", self.session.snapshot()["transcript"]["testo"])
        self.session.ingest(self.session_id, "completo", final=True)
        self.session.ingest(self.session_id, "terza")
        state = self.session.snapshot()
        self.assertEqual([{"text": "completo"}], state["transcript"]["final_segments"])
        self.assertEqual("completo terza", state["transcript"]["testo"])
        self.assertEqual(self.started["action_version"], state["action_version"])

    def test_final_segment_keeps_an_earlier_refusal_out_of_a_new_request(self):
        self.session.ingest(self.session_id, "Non voglio il mascara waterproof", final=True)
        self.now = 13
        self.session.ingest(self.session_id, "Cerco un termometro", final=True)
        self.session.evaluate()
        self.assertEqual("DEMO-DIS-01", self.session.snapshot()["product"]["candidate_code"])

    def test_cosmetic_complement_needs_an_explicit_removal_request_and_confirmation(self):
        self.now = 13
        self.session.ingest(self.session_id, "Cerco un mascara waterproof", final=True)
        self.session.evaluate()
        self.assertEqual([], self.session.snapshot()["stock"][0]["complements"])
        self.session.ingest(self.session_id, "Come lo rimuovo", final=True)
        self.session.evaluate()
        self.assertEqual([], self.session.snapshot()["stock"][0]["complements"])
        _, confirmed = self.action("conferma_prodotto", {"code": "DEMO-COS-01"})
        self.assertEqual("DEMO-COS-02", confirmed["stock"][0]["complements"][0]["product_code"])
        _, corrected = self.action("correggi_prodotto", {"code": "DEMO-OTC-03"})
        self.assertTrue(all(not row["complements"] for row in corrected["stock"]))

    def test_only_one_restock_request_and_it_closes_after_replenishment(self):
        def requests_for(code):
            snapshot = self.session.snapshot(inventory=True)
            return [row for row in snapshot["restock"] if row["codice"] == code]

        code = "DEMO-INT-02"
        self.assertEqual(1, len(requests_for(code)))
        self.now += 1
        self.assertEqual(1, len(requests_for(code)))
        with closing(sqlite3.connect(self.catalog)) as db, db:
            db.execute("UPDATE prodotti SET quantita=4 WHERE codice=?", (code,))
        self.now += 1
        self.assertEqual([], requests_for(code))
        with closing(sqlite3.connect(self.requests)) as db:
            self.assertIsNone(db.execute("SELECT codice FROM richieste WHERE codice=?", (code,)).fetchone())

    def test_manual_search_shows_cards_without_saving_query_or_touching_transcript(self):
        marker = "marcatore_privato_ricerca"
        status, state = self.session.manual_search(f"mascara {marker}", self.session_id)
        self.assertEqual(200, status)
        self.assertTrue(any(card["id"] == "mascara-demo" for card in state["cards"]))
        self.assertNotIn(marker, json.dumps(state))
        self.assertEqual("", state["transcript"]["testo"])
        self.session.stop()
        self.assertEqual([], self.session.snapshot()["cards"])
        self.assertNotIn(marker, json.dumps(list(desk.EVENTS)))
        for path in (self.catalog, self.requests):
            with closing(sqlite3.connect(path)) as db:
                self.assertNotIn(marker, "\n".join(db.iterdump()))

    def test_partial_starts_assistance_after_gate_without_a_final(self):
        self.session.ingest(self.session_id, "😀 Cerco un mascara waterproof")
        self.session.evaluate()
        self.now = 12.99
        self.session.evaluate()
        self.assertEqual([], self.session.snapshot()["cards"])
        self.now = 13
        self.session.ingest(self.session_id, "😀 Cerco un mascara waterproof per favore")
        self.session.evaluate()
        state = self.session.snapshot()
        self.assertEqual([], state["transcript"]["final_segments"])
        self.assertEqual("DEMO-COS-01", state["product"]["candidate_code"])
        self.assertEqual("provisional", state["cards"][0]["state"])
        evidence = next(item for item in state["evidence"] if "DEMO-COS-01" in item["product_codes"])
        span = evidence["span"]
        text = state["transcript"]["testo"].encode("utf-16-le")[2*span["start"]:2*span["end"]].decode("utf-16-le")
        self.assertIn("mascara", text.lower())
        self.assertEqual(state["transcript"]["revision"], span["transcript_revision"])
        self.session.ingest(self.session_id, "Non voglio il mascara waterproof")
        self.session.evaluate()
        self.assertEqual([], self.session.snapshot()["cards"])

    def test_reset_rejects_delayed_results_and_actions(self):
        self.session.ingest(self.session_id, "marcatore_sintetico")
        status, reset = self.action("reset")
        self.assertEqual(200, status)
        self.assertNotEqual(self.session_id, reset["session_id"])
        self.assertFalse(self.session.ingest(self.session_id, "ritardato"))
        self.assertEqual(409, self.action("fase", {"value": "Domande"}, self.started)[0])
        self.assertEqual("", self.session.snapshot()["transcript"]["testo"])

    def test_late_interpretation_cannot_publish_over_newer_transcript(self):
        self.now = 13
        self.session.ingest(self.session_id, "Cerco un mascara waterproof", final=True)
        entered, released = Event(), Event()
        analyze = desk.analyze

        def delayed(*args, **kwargs):
            entered.set()
            released.wait(2)
            return analyze(*args, **kwargs)

        worker = Thread(target=self.session.evaluate)
        with patch.object(desk, "analyze", delayed):
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                self.session.ingest(self.session_id, "Non voglio il mascara waterproof")
            finally:
                released.set()
                worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual([], self.session.snapshot()["cards"])
        self.assertIn("Non voglio", self.session.snapshot()["transcript"]["testo"])

    def test_restarts_while_old_audio_worker_is_still_exiting(self):
        old_entered, old_released, new_entered = Event(), Event(), Event()
        old_ids = []

        def audio(session_id, stopped):
            if not old_ids:
                old_ids.append(session_id)
                old_entered.set()
                old_released.wait(2)
                raise RuntimeError("old worker fault")
            new_entered.set()
            stopped.wait(2)

        with patch.object(self.session, "_capture_audio", audio):
            first = self.session.start()
            try:
                self.assertTrue(old_entered.wait(1))
                self.assertEqual(200, self.action("reset", snapshot=first)[0])
                second = self.session.start()
                self.assertNotEqual(first["session_id"], second["session_id"])
                self.assertTrue(self.session.ingest(second["session_id"], "nuova sessione"))
            finally:
                old_released.set()
            self.assertTrue(new_entered.wait(1))
            after = self.session.snapshot()
            self.assertEqual(second["session_id"], after["session_id"])
            self.assertEqual("avvio", after["status"]["microphone"])
            self.assertEqual("nuova sessione", after["transcript"]["testo"])
            self.session.stop()

    def test_retracted_partial_immediately_removes_candidate_and_stock(self):
        self.session.ingest(self.session_id, "Cerco un mascara waterproof")
        self.session.evaluate()
        self.now = 13
        self.session.evaluate()
        self.assertEqual("DEMO-COS-01", self.session.snapshot()["product"]["candidate_code"])
        self.session.ingest(self.session_id, "Frase diversa")
        state = self.session.snapshot()
        self.assertEqual([], state["cards"])
        self.assertIsNone(state["product"]["candidate_code"])
        self.assertEqual([], state["stock"])

    def test_only_session_owner_renews_the_lease(self):
        self.now = 20
        self.session.snapshot(self.session_id)
        self.now = 31.5
        self.assertEqual(self.session_id, self.session.snapshot("stale-id")["session_id"])
        self.now = 32
        self.assertNotEqual(self.session_id, self.session.snapshot()["session_id"])

    def test_idle_manual_recipient_also_expires_without_owner(self):
        self.session.stop()
        _, state = self.action("destinatario", {"kind": "altra_persona", "declared_fields": {"age": 14}})
        self.assertEqual({"age": 14}, state["recipient"]["declared_fields"])
        self.now += 12
        self.assertEqual({}, self.session.snapshot()["recipient"]["declared_fields"])

    def test_manual_gender_is_explicit_and_cleared_for_unknown_recipient(self):
        status, state = self.action("destinatario", {"kind": "altra_persona", "declared_fields": {"gender": "donna"}})
        self.assertEqual(200, status)
        self.assertEqual({"gender": "donna"}, state["recipient"]["declared_fields"])
        self.assertEqual("manuale", state["recipient"]["source"])
        status, state = self.action("destinatario", {"kind": "sconosciuto", "declared_fields": {"gender": "donna"}})
        self.assertEqual({}, state["recipient"]["declared_fields"])

    def test_configuration_rejects_credentials_and_non_public_urls(self):
        for url in ("http://example.org", "https://user@example.org", "https://127.0.0.1/",
                    "https://example.org/?to%6ben=value", "https://example.org/{trascrizione}",
                    "https://example.org/?comune=Roma", "https://example.org/?search={comune}",
                    "https://example.org/?comune={comune}#fragment"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                desk.save_configuration({"fonti": {"turni": url}}, self.settings)

    def test_lease_expiry_and_microphone_failure_clear_private_state(self):
        marker = "marker_sintetico_privato"
        self.session.ingest(self.session_id, marker, final=True)
        self.now = 22
        expired = self.session.snapshot()
        self.assertEqual("", expired["transcript"]["testo"])
        self.assertNotEqual(self.session_id, expired["session_id"])
        started = self.session.start(background=False)
        self.session.ingest(started["session_id"], marker)
        self.session.finish(started["session_id"], "microfono_o_ricerca")
        failed = self.session.snapshot()
        self.assertEqual("errore", failed["status"]["microphone"])
        self.assertEqual("", failed["transcript"]["testo"])
        desk.diagnostic("audio", marker, "errore")
        self.assertNotIn(marker, json.dumps(list(desk.EVENTS)))
        self.assertTrue(all("durata_ms" in event for event in desk.EVENTS))
        with closing(sqlite3.connect(self.catalog)) as db:
            self.assertNotIn(marker, "\n".join(db.iterdump()))

    def test_manual_confirmation_and_correction(self):
        self.action("seleziona_prodotto", {"code": "DEMO-EQV-01"})
        status, state = self.action("conferma_prodotto", {"code": "DEMO-EQV-01"})
        self.assertEqual(200, status)
        self.assertEqual("DEMO-EQV-01", state["product"]["confirmed_code"])
        self.assertEqual("farmacista", state["product"]["confirmed_by"])
        self.assertEqual("DEMO-EQV-02", state["stock"][0]["equivalents"][0]["product_code"])
        status, state = self.action("correggi_prodotto", {"code": "DEMO-OTC-03"})
        self.assertEqual(200, status)
        self.assertIsNone(state["product"]["confirmed_code"])
        self.assertEqual([], state["stock"][0]["equivalents"])

    def test_turns_require_operator_location_and_date(self):
        desk.save_configuration({"ritardo_secondi": 3, "fonti": {"turni": "https://example.org/turni?comune={comune}&data={data}"}},
                                self.settings)
        status, state = self.action("servizio", {"kind": "turni"})
        self.assertEqual(200, status)
        self.assertEqual("missing", state["service"]["status"])
        self.assertIsNone(state["service"]["source"])
        self.session.ingest(self.session_id, "testo da non inviare")
        status, state = self.action("servizio", {"kind": "turni", "comune": "Reggio Emilia", "data": "2026-11-07"})
        self.assertEqual(200, status)
        self.assertEqual("https://example.org/turni?comune=Reggio%20Emilia&data=2026-11-07", state["service"]["source"]["url"])
        self.assertIsNone(state["service"]["answer"])
