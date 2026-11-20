"""Scheda farmaco e integratori collegati: codici, ricerca, aggiunta, aggiornamento, domande, banco."""

import http.client
import json
import shutil
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

from backend import desk, scheda_farmaco, vendita
from backend.catalog_setup import migrate_latest, seed_symptom_associations

ROOT = Path(__file__).resolve().parents[1]
OPERATIVE = ROOT / "database" / "farmacia.sqlite3"
DRUG = "REAL-MED-006"          # Aspirina Influenza e Naso Chiuso, linked to «raffreddore»
OTHER_DRUG = "REAL-MED-015"    # Rinazina, same need
AIFA_CSV = ("codice_aic;denominazione;descrizione;ragione_sociale;stato_amministrativo;codice_atc;"
            "pa_associati;fornitura\n"
            "123456789;FARMACO DI PROVA;10 compresse 200 mg;Ditta Prova;Autorizzata;M01AE01;Ibuprofene;"
            "OTC - medicinali da banco\n")


def gs1(body):
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return body + str((10 - total % 10) % 10)


class CatalogCopy(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        self.catalog = self.dir / "farmacia.sqlite3"
        shutil.copy(OPERATIVE, self.catalog)
        migrate_latest(self.catalog)
        seed_symptom_associations(self.catalog, ROOT / "database" / "collegamenti-concetti-nuovi.json")
        self.wiki = self.dir / "wiki"
        self.wiki.mkdir()
        self.aifa = self.dir / "aifa"
        self.aifa.mkdir()
        (self.aifa / "confezioni.csv").write_text(AIFA_CSV, encoding="utf-8")
        with closing(sqlite3.connect(self.catalog)) as db:
            self.source = db.execute("SELECT id FROM fonti ORDER BY id LIMIT 1").fetchone()[0]

    def link_fixtures(self):
        """Level 1 (approved pairing), level 2 (approved for the need), level 3 (candidate with source)."""
        with closing(sqlite3.connect(self.catalog)) as db, db:
            db.execute("""INSERT INTO relazioni_prodotti (origine, destinazione, tipo, fonte, condizioni, motivo,
                              esclusioni, revisore, stato_revisione, fonte_id, revisionato_il)
                          VALUES (?, 'REAL-SUP-014', 'complemento_revisionato', 'test', '', 'Difese durante il
                              raffreddore', 'gravidanza', 'Test', 'approvata', ?, '2026-11-19')""",
                       (DRUG, self.source))
            db.execute("""INSERT INTO complementi_banco (concetto_id, prodotto_complemento, tipo, motivo,
                              esclusioni, priorita, stato_revisione, revisore, revisionato_il)
                          VALUES ('raffreddore', 'REAL-SUP-001', 'integratore', 'Multivitaminico di supporto', '',
                              10, 'approvata', 'Test', '2026-11-19')""")
            db.execute("""INSERT INTO relazioni_concetto_prodotto (concetto_id, prodotto_codice, tipo, fonte_id,
                              stato_revisione) VALUES ('raffreddore', 'REAL-SUP-019', 'contesto_ricerca', ?,
                              'candidata')""", (self.source,))
            # Out of stock supplement: never shown.
            db.execute("""INSERT INTO relazioni_concetto_prodotto (concetto_id, prodotto_codice, tipo, fonte_id,
                              stato_revisione) VALUES ('raffreddore', 'REAL-SUP-002', 'contesto_ricerca', ?,
                              'candidata')""", (self.source,))
            db.execute("UPDATE prodotti SET quantita = 0 WHERE codice = 'REAL-SUP-002'")


class ParseCodeTest(unittest.TestCase):
    def test_aic_forms(self):
        self.assertEqual({"kind": "aic", "value": "024823080", "valid": True},
                         scheda_farmaco.parse_code("A024823080"))
        self.assertEqual("aic", scheda_farmaco.parse_code("024823080")["kind"])
        self.assertEqual("aic6", scheda_farmaco.parse_code("000590")["kind"])

    def test_code32_letters_decode_to_aic(self):
        value, text = 24823080, ""
        while value:
            value, rest = divmod(value, 32)
            text = scheda_farmaco.CODE32_ALPHABET[rest] + text
        parsed = scheda_farmaco.parse_code("A" + text.rjust(6, "0"))
        self.assertEqual(("aic", "024823080"), (parsed["kind"], parsed["value"]))

    def test_ean_and_gtin_check_digit(self):
        ean = gs1("800123456789")
        self.assertTrue(scheda_farmaco.parse_code(ean)["valid"])
        wrong = ean[:-1] + str((int(ean[-1]) + 1) % 10)
        self.assertFalse(scheda_farmaco.parse_code(wrong)["valid"])
        self.assertEqual("gtin", scheda_farmaco.parse_code("0" + ean)["kind"])

    def test_gs1_keeps_only_the_gtin(self):
        gtin = gs1("0800123456789")
        parsed = scheda_farmaco.parse_code("]d201" + gtin + "17271231" + "10LOTTO1\x1d21SERIALE")
        self.assertEqual({"kind": "gtin", "value": gtin, "valid": True, "from": "gs1"}, parsed)
        self.assertNotIn("LOTTO", json.dumps(parsed))
        human = scheda_farmaco.parse_code("(01)" + gtin + "(17)271231")
        self.assertEqual(gtin, human["value"])

    def test_url_and_text(self):
        gtin = gs1("0800123456789")
        self.assertEqual(gtin, scheda_farmaco.parse_code("https://id.example.it/01/" + gtin + "/10/X")["value"])
        url = scheda_farmaco.parse_code("https://example.it/foglietto?paziente=1")
        self.assertEqual(("url", "https://example.it/foglietto"), (url["kind"], url["value"]))
        self.assertEqual("testo", scheda_farmaco.parse_code("tachipirina")["kind"])
        self.assertEqual("vuoto", scheda_farmaco.parse_code("  ")["kind"])


class FindRegisterTest(CatalogCopy):
    def test_find_by_aic_alias_and_name(self):
        found = scheda_farmaco.find("A024823080", self.catalog, self.aifa)
        self.assertEqual(("trovato", "REAL-MED-009"), (found["status"], found["products"][0]["code"]))
        many = scheda_farmaco.find("multicentrum", self.catalog, self.aifa)
        self.assertEqual("multipli", many["status"])
        ean = gs1("800765432101")
        with closing(sqlite3.connect(self.catalog)) as db, db:
            db.execute("""INSERT INTO alias_prodotto (prodotto_codice, alias, tipo, stato_revisione)
                          VALUES ('REAL-SUP-001', ?, 'codice_pubblico', 'approvata')""", (ean,))
        self.assertEqual("REAL-SUP-001", scheda_farmaco.find(ean, self.catalog)["products"][0]["code"])
        self.assertEqual("REAL-SUP-001", scheda_farmaco.find("0" + ean, self.catalog)["products"][0]["code"])

    def test_aifa_only_needs_confirmation_then_registers_without_price(self):
        found = scheda_farmaco.find("123456789", self.catalog, self.aifa)
        self.assertEqual("aifa", found["status"])
        with closing(sqlite3.connect(self.catalog)) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM prodotti WHERE codice='SCAN-123456789'").fetchone())
        with self.assertRaises(ValueError):
            scheda_farmaco.register(found["aifa"], self.catalog, "", self.wiki)
        added = scheda_farmaco.register(found["aifa"], self.catalog, "Dott.ssa Test", self.wiki)
        self.assertEqual("SCAN-123456789", added["code"])
        with closing(sqlite3.connect(self.catalog)) as db:
            row = db.execute("""SELECT stato_revisione, prezzo_cent, quantita, regime_fornitura, regime_fonte_id,
                                       atc, id_regolatorio FROM prodotti WHERE codice='SCAN-123456789'""").fetchone()
            self.assertEqual(("da_revisionare", None, None, "OTC", "SRC-AIFA-ANAGRAFICA", "M01AE01", "123456789"),
                             row)
            log = db.execute("SELECT revisore FROM registro_revisioni WHERE chiave='SCAN-123456789'").fetchone()
            self.assertEqual("Dott.ssa Test", log[0])
            self.assertEqual(1, db.execute("SELECT count(*) FROM registro_import WHERE fonte='scheda_farmaco'")
                             .fetchone()[0])
        self.assertTrue((self.wiki / "scan-123456789.md").is_file())
        with self.assertRaises(FileExistsError):
            scheda_farmaco.register(found["aifa"], self.catalog, "Dott.ssa Test", self.wiki)

    def test_unknown_code_manual_add_requires_source(self):
        ean = gs1("800111222333")
        self.assertEqual("sconosciuto", scheda_farmaco.find(ean, self.catalog, self.aifa)["status"])
        fields = {"nome": "Crema di prova", "categoria": "cosmetico", "codice": ean}
        with self.assertRaises(ValueError):
            scheda_farmaco.add_manual(fields, self.catalog, "Test", self.wiki)
        added = scheda_farmaco.add_manual({**fields, "fonte_url": "https://produttore.example.it/crema"},
                                          self.catalog, "Test", self.wiki)
        self.assertEqual("SCAN-" + ean, added["code"])
        self.assertEqual("SCAN-" + ean, scheda_farmaco.find(ean, self.catalog)["products"][0]["code"])


class LinkedSupplementsTest(CatalogCopy):
    def test_levels_order_and_exclusions(self):
        self.link_fixtures()
        state = {"desk_results": {"rows": [{"code": DRUG}, {"code": OTHER_DRUG}]}, "evidence": [],
                 "cart": {"items": []}, "transcript": {"testo": "ho il raffreddore"}}
        items = vendita.linked_supplements(state, self.catalog)
        codes = [item["code"] for item in items]
        self.assertEqual(["REAL-SUP-014", "REAL-SUP-001", "REAL-SUP-019"], codes[:3])
        self.assertEqual([1, 2, 3], [item["level"] for item in items[:3]])
        self.assertFalse(items[2]["reviewed"])
        self.assertNotIn("REAL-SUP-002", codes)  # out of stock
        self.assertEqual({DRUG, OTHER_DRUG}, {link["code_farmaco"] for link in items[1]["linked_to"]})
        self.assertEqual(DRUG, items[0]["linked_to"][0]["code_farmaco"])
        # In the cart: left out. Exclusion said at the desk: left out.
        state["cart"]["items"] = [{"code": "REAL-SUP-001"}]
        state["transcript"]["testo"] = "ho il raffreddore e sono in gravidanza"
        codes = [item["code"] for item in vendita.linked_supplements(state, self.catalog)]
        self.assertNotIn("REAL-SUP-001", codes)
        self.assertNotIn("REAL-SUP-014", codes)

    def test_no_record_no_supplement(self):
        state = {"desk_results": {"rows": [{"code": "REAL-MED-038"}]}, "cart": {"items": []}}
        self.assertEqual([], vendita.linked_supplements(state, self.catalog))


class AdviceUpdateAskTest(CatalogCopy):
    def test_consigli_uses_same_levels_and_proposals_stay_candidate(self):
        self.link_fixtures()
        advice = scheda_farmaco.consigli(DRUG, self.catalog)
        self.assertEqual("REAL-SUP-014", advice["integratori"][0]["code"])
        scheda_farmaco.proponi(DRUG, "REAL-SUP-004", "Supporto difese", "gravidanza",
                               "https://www.example.it/fonte", self.catalog, "Test")
        with closing(sqlite3.connect(self.catalog)) as db:
            state = db.execute("""SELECT stato_revisione FROM relazioni_prodotti
                                  WHERE origine=? AND destinazione='REAL-SUP-004'""", (DRUG,)).fetchone()[0]
        self.assertEqual("candidata", state)
        self.assertEqual("REAL-SUP-004", scheda_farmaco.consigli(DRUG, self.catalog)["proposte_in_revisione"][0]["code"])

    def test_update_logs_before_after_and_keeps_pharmacist_regime(self):
        scheda_farmaco.aggiorna(DRUG, {"prezzo_cent": 777, "quantita": 4}, self.catalog, "Test")
        with self.assertRaises(ValueError):
            scheda_farmaco.aggiorna(DRUG, {"regime_fornitura": "SOP"}, self.catalog, "Test")
        with self.assertRaises(ValueError):
            scheda_farmaco.aggiorna(DRUG, {"prezzo_cent": 777}, self.catalog, "")
        scheda_farmaco.aggiorna(DRUG, {"regime_fornitura": "SOP", "fonte_url": "https://www.aifa.gov.it/x"},
                                self.catalog, "Test")
        scheda_farmaco.aggiorna(DRUG, {"alias": {"testo": "aspirina naso", "tipo": "nome_uso_comune"}},
                                self.catalog, "Test")
        with closing(sqlite3.connect(self.catalog)) as db:
            price, source, regime_source = db.execute("""SELECT prezzo_cent, prezzo_banco_fonte_id, regime_fonte_id
                                                         FROM prodotti WHERE codice=?""", (DRUG,)).fetchone()
            self.assertEqual((777, "SRC-FARMACIA-MANUALE"), (price, source))
            self.assertNotEqual("SRC-AIFA-ANAGRAFICA", regime_source)
            logged = db.execute("""SELECT da_stato, a_stato, revisore FROM registro_revisioni
                                   WHERE chiave=?""", (DRUG + ":prezzo_cent",)).fetchone()
            self.assertIn("777", logged[1])
            self.assertEqual("Test", logged[2])
            alias = db.execute("""SELECT stato_revisione FROM alias_prodotto WHERE prodotto_codice=?
                                  AND alias='aspirina naso'""", (DRUG,)).fetchone()[0]
            self.assertEqual("candidata", alias)
        sheet = scheda_farmaco.scheda(DRUG, self.catalog, self.wiki)
        price = next(item for item in sheet["vendita"] if item["label"] == "Prezzo al banco")
        self.assertEqual("farmacia", price["source"]["tipo"])
        with self.assertRaises(ValueError):
            scheda_farmaco.aggiorna(DRUG, {"nome": "Altro"}, self.catalog, "Test")
        history = scheda_farmaco.storico(DRUG, self.catalog)
        self.assertGreaterEqual(len(history["revisioni"]), 4)

    def test_chiedi_answers_from_records_and_never_gives_doses(self):
        scheda_farmaco.aggiorna(DRUG, {"prezzo_cent": 650}, self.catalog, "Test")
        answer = scheda_farmaco.chiedi(DRUG, "quanto costa?", self.catalog, self.wiki)
        self.assertIn("6,50", answer["risposta"])
        self.assertTrue(answer["citazioni"])
        dose = scheda_farmaco.chiedi(DRUG, "quante bustine al giorno, che dose?", self.catalog, self.wiki)
        self.assertIn("foglietto", dose["risposta"])
        self.assertNotRegex(dose["risposta"], r"\d")
        age = scheda_farmaco.chiedi(DRUG, "da che età si può dare?", self.catalog, self.wiki)
        self.assertIn("Età minima registrata: 16 anni", age["risposta"])
        missing = scheda_farmaco.chiedi(DRUG, "è carente?", self.catalog, self.wiki)
        self.assertIn("non risulta", missing["risposta"].lower())  # never checked against the AIFA list
        no_price = scheda_farmaco.chiedi("REAL-SUP-001", "giacenza?", self.catalog, self.wiki)
        self.assertNotIn("non risulta", no_price["risposta"].lower())
        nothing = scheda_farmaco.chiedi(DRUG, "colore della scatola", self.catalog, self.wiki)
        self.assertEqual("Non risulta dalle fonti registrate.", nothing["risposta"])


class DeskIntegrationTest(CatalogCopy):
    def session(self):
        self.now = 10
        listening = desk.Listening(catalog=self.catalog, requests=self.dir / "requests.sqlite3",
                                   settings=self.dir / "settings.json", clock=lambda: self.now)
        self.addCleanup(listening.stop)
        return listening

    def test_show_at_desk_selects_without_confirming_or_cart(self):
        listening = self.session()
        with self.assertRaises(LookupError):
            listening.show_from_scheda(DRUG)
        started = listening.start(background=False)
        listening.ingest(started["session_id"], "buongiorno", final=True)
        self.now += 4
        listening.evaluate()
        result = listening.show_from_scheda(DRUG)
        self.assertEqual("scheda farmaco", result["evidenza"])
        state = listening.snapshot()
        self.assertEqual(DRUG, state["desk_results"]["rows"][0]["code"])
        self.assertEqual(DRUG, state["product"]["current_code"])
        self.assertIsNone(state["product"]["confirmed_code"])
        self.assertEqual([], state["cart"]["items"])

    def test_session_exposes_linked_supplements_and_cart_accepts_them(self):
        self.link_fixtures()
        listening = self.session()
        started = listening.start(background=False)
        listening.ingest(started["session_id"], "ho il raffreddore", final=True)
        self.now += 4
        listening.evaluate()
        state = listening.snapshot()
        linked = state["desk_results"]["linked_supplements"]
        self.assertTrue(linked)
        code = linked[0]["code"]
        status, after = listening.action({"session_id": state["session_id"],
                                          "expected_action_version": state["action_version"],
                                          "action": "aggiungi_carrello", "payload": {"code": code}})
        self.assertEqual(200, status)
        self.assertIn(code, [item["code"] for item in after["cart"]["items"]])
        with closing(sqlite3.connect(self.catalog)) as db:
            self.assertEqual(1, db.execute("""SELECT count(*) FROM feedback_banco WHERE evento='accettato'
                                               AND prodotto_codice=?""", (code,)).fetchone()[0])


class HttpTest(CatalogCopy):
    def setUp(self):
        super().setUp()
        listening = desk.Listening(catalog=self.catalog, requests=self.dir / "requests.sqlite3",
                                   settings=self.dir / "settings.json")
        self.addCleanup(listening.stop)
        handler = type("Handler", (desk.Desk,), {"listening": listening})
        self.server = desk.LocalServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.original_port = desk.PORT
        desk.PORT = self.port
        self.addCleanup(setattr, desk, "PORT", self.original_port)
        self.original_origin = desk.ORIGIN
        desk.ORIGIN = f"http://127.0.0.1:{self.port}"
        self.addCleanup(setattr, desk, "ORIGIN", self.original_origin)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, path, body, origin=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json", "Host": f"127.0.0.1:{self.port}"}
        if origin:
            headers["Origin"] = f"http://127.0.0.1:{self.port}"
        conn.request("POST", path, json.dumps(body), headers)
        response = conn.getresponse()
        data = json.loads(response.read() or b"{}")
        conn.close()
        return response.status, data

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path, headers={"Host": f"127.0.0.1:{self.port}"})
        response = conn.getresponse()
        body = response.read()
        conn.close()
        return response.status, body

    def test_origin_is_required_for_every_farmaco_write(self):
        for route in ("codice", "cerca", "aggiungi", "aggiorna", "proponi", "chiedi", "mostra-al-banco"):
            status, _ = self.post("/api/farmaco/" + route, {"codice": "x"}, origin=False)
            self.assertEqual(403, status, route)

    def test_code_endpoint_accepts_only_the_code_text(self):
        status, _ = self.post("/api/farmaco/codice", {"codice": "A024823080", "immagine": "data:image/png;base64,AA"})
        self.assertEqual(400, status)
        status, _ = self.post("/api/farmaco/codice", {"codice": "A024823080", "frame": [1, 2, 3]})
        self.assertEqual(400, status)
        status, data = self.post("/api/farmaco/codice", {"codice": "A024823080", "origine": "telecamera"})
        self.assertEqual((200, "trovato"), (status, data["status"]))
        self.assertEqual("trovato", scheda_farmaco.CAMERA_STATUS["esito"])
        self.assertNotIn("024823080", json.dumps(scheda_farmaco.CAMERA_STATUS))

    def test_pages_and_sheet_are_served(self):
        for path in ("/farmaco", "/farmaco.js", "/scanner.js"):
            status, _ = self.get(path)
            self.assertEqual(200, status, path)
        status, body = self.get("/api/farmaco/scheda?code=" + DRUG)
        self.assertEqual(200, status)
        sheet = json.loads(body)
        self.assertFalse(sheet["banco_attivo"])
        self.assertTrue(all("source" in item for item in sheet["identita"]))
        status, _ = self.get("/api/farmaco/scheda?code=../../etc")
        self.assertEqual(400, status)
        status, _ = self.post("/api/farmaco/mostra-al-banco", {"code": DRUG})
        self.assertEqual(409, status)
        status, body = self.get("/api/interfaccia")
        self.assertEqual({"mostra_trascrizione": True}, json.loads(body))


if __name__ == "__main__":
    unittest.main()
