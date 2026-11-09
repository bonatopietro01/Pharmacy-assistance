from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date

from backend import knowledge


class CatalogTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.catalog = Path(temp.name) / "catalog.sqlite3"
        with closing(sqlite3.connect(self.catalog)) as db:
            for script in ("demo/catalogo.sql", "database/002_assistenza.sql", "database/003_live_assistenza.sql"):
                self.assertTrue(Path(script).is_file(), f"Required migration unavailable: {script}")
                db.executescript(Path(script).read_text(encoding="utf-8"))


class OfferTest(CatalogTest):
    def setUp(self):
        super().setUp()
        from backend.offers import active_offers, save_offer
        self.active_offers = active_offers
        self.save_offer = save_offer
        self.today = date(2026, 11, 7)
        self.offer = dict(codice="TEST-01", prodotto_codice="DEMO-COS-01", titolo="Prova", criterio="Richiesta mascara",
                          criterio_tipo="cosmetico", prezzo_cent=990, beneficio="", inizio="2026-11-07",
                          fine="2026-11-07", disponibilita=1, stato="attiva", budget_cent=None)

    def test_requires_explicit_matching_interest_and_validity(self):
        self.save_offer(self.offer, self.catalog)
        def listed(intent, day=self.today):
            return [row["codice"] for row in self.active_offers(day, intent, self.catalog)]
        self.assertIn("TEST-01", listed({"product_codes": ["DEMO-COS-01"]}))
        self.assertNotIn("TEST-01", listed({"product_codes": ["DEMO-COS-02"]}))
        self.assertEqual([], listed({"product_codes": []}))
        self.assertNotIn("TEST-01", listed({"product_codes": ["DEMO-COS-01"]}, date(2026, 11, 8)))

    def test_excludes_zero_offer_availability_or_product_stock(self):
        intent = {"product_codes": ["DEMO-COS-01"]}
        self.save_offer(dict(self.offer, disponibilita=0), self.catalog)
        self.assertNotIn("TEST-01", [row["codice"] for row in self.active_offers(self.today, intent, self.catalog)])
        self.save_offer(self.offer, self.catalog)
        with closing(sqlite3.connect(self.catalog)) as db, db:
            db.execute("UPDATE prodotti SET quantita=0 WHERE codice='DEMO-COS-01'")
        self.assertEqual([], self.active_offers(self.today, intent, self.catalog))

    def test_rejects_non_integer_price_invalid_dates_and_missing_product(self):
        for change in ({"prezzo_cent": True}, {"inizio": "2026-02-30"},
                       {"prodotto_codice": "non-presente"}, {"criterio": ""}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.save_offer(dict(self.offer, **change), self.catalog)

    def test_budget_must_be_declared_and_cover_the_offer(self):
        self.save_offer(dict(self.offer, criterio_tipo="budget", budget_cent=1500), self.catalog)
        intent = {"product_codes": ["DEMO-COS-01"]}
        for budget, expected in ((None, False), (950, False), (1100, True)):
            result = self.active_offers(self.today, dict(intent, budget_cent=budget), self.catalog)
            self.assertEqual(expected, "TEST-01" in [row["codice"] for row in result])

    def test_only_exact_relations_provide_equivalent_stock(self):
        rows = knowledge.stock_for(["DEMO-EQV-01", "DEMO-OTC-03"], self.catalog)
        self.assertEqual(0, rows[0]["quantity"])
        self.assertEqual("DEMO-EQV-02", rows[0]["equivalents"][0]["product_code"])
        self.assertEqual("equivalente_demo", rows[0]["equivalents"][0]["tipo"])
        self.assertEqual([], rows[1]["equivalents"])

    def test_migration_preserves_foreign_keys_and_demo_state(self):
        with closing(sqlite3.connect(self.catalog)) as db:
            self.assertEqual(("ok",), db.execute("PRAGMA integrity_check").fetchone())
            self.assertEqual([], db.execute("PRAGMA foreign_key_check").fetchall())
            self.assertEqual((3,), db.execute("PRAGMA user_version").fetchone())
            self.assertEqual(("demo",), db.execute("SELECT stato FROM offerte WHERE codice='DEMO-OFF-01'").fetchone())


if __name__ == "__main__":
    unittest.main()
