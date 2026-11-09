import unittest

from backend.conversation import analyze


class ConversationTests(unittest.TestCase):
    analyze = staticmethod(analyze)

    def setUp(self):
        self.products = [
            {"codice": "DEMO-COS-01", "nome": "Mascara Demo", "termini": ["mascara waterproof", "mascara"]},
            {"code": "DEMO-COS-02", "term": "struccante"},
            {"code": "DEMO-OTC-01", "term": "Banco Demo A"},
        ]

    def test_exact_alias_has_a_span_in_original_text(self):
        text = "✨ Cerco un MASCARA waterproof"
        result = self.analyze(text, self.products)
        self.assertEqual(result["phase"]["value"], "Verifica prodotto")
        self.assertEqual(result["candidate_codes"], ["DEMO-COS-01"])
        evidence, = (item for item in result["evidence"] if item["kind"] == "product_candidate")
        self.assertEqual(evidence["span"], {"start": 11, "end": 29})
        self.assertEqual(text[11:29], "MASCARA waterproof")
        self.assertEqual(evidence["source"]["id"], "DEMO-COS-01")
        self.assertTrue(evidence["rule_id"])

    def test_product_mention_without_explicit_request_has_no_commercial_intent(self):
        result = self.analyze("Ho letto di Banco Demo A", self.products)
        self.assertFalse(result["commercial_intent"]["product_codes"])
        self.assertFalse(result["candidate_codes"])
        self.assertIn("product_mention", [e["kind"] for e in result["events"]])

    def test_explicit_commercial_intent_requires_a_product_and_current_request(self):
        result = self.analyze("Cerco un mascara waterproof con budget di 15,50 euro", self.products)
        self.assertEqual(result["commercial_intent"], {"product_codes": ["DEMO-COS-01"], "budget_cent": 1550})
        result = self.analyze("C’è un’offerta?", self.products)
        self.assertFalse(result["commercial_intent"]["product_codes"])

    def test_request_does_not_transfer_to_unrelated_product_mentions(self):
        result = self.analyze("Cerco un mascara, mia sorella usa Banco Demo A", self.products)
        self.assertEqual(result["candidate_codes"], ["DEMO-COS-01"])
        self.assertEqual(result["commercial_intent"]["product_codes"], ["DEMO-COS-01"])

    def test_price_question_binds_to_product_before_or_after(self):
        for text in ("Quanto costa il mascara?", "Il mascara quanto costa?"):
            with self.subTest(text=text):
                self.assertEqual(self.analyze(text, self.products)["commercial_intent"]["product_codes"], ["DEMO-COS-01"])
        self.assertFalse(self.analyze("Il prezzo del mascara è 10 euro", self.products)["commercial_intent"]["product_codes"])

    def test_ambiguous_alias_does_not_select_a_product_or_trigger_offer(self):
        ambiguous = [{"code": "DEMO-1", "term": "compresse"}, {"code": "DEMO-2", "term": "compresse"}]
        result = self.analyze("Cerco le compresse", ambiguous)
        self.assertEqual(result["phase"]["value"], "Domande")
        self.assertFalse(result["candidate_codes"])
        self.assertFalse(result["commercial_intent"]["product_codes"])

    def test_general_catalog_category_is_not_a_product_alias(self):
        products = [{"codice": "DEMO-DIS-01", "nome": "Termometro Demo", "categoria": "Dispositivo medico"}]
        result = self.analyze("Cerco un dispositivo medico", products)
        self.assertFalse(result["candidate_codes"])
        self.assertFalse(result["commercial_intent"]["product_codes"])

    def test_decimal_budget_with_period_stays_with_the_request(self):
        result = self.analyze("Cerco un mascara con budget di 15.50 euro", self.products)
        self.assertEqual(result["commercial_intent"].get("budget_cent"), 1550)

    def test_budget_belongs_only_to_the_product_with_the_stated_limit(self):
        result = self.analyze("Cerco un mascara e vorrei uno struccante, massimo 10 euro", self.products)
        interests = {item["product_codes"][0]: item for item in result["evidence"] if item["kind"] == "commercial_intent"}
        self.assertEqual(interests["DEMO-COS-02"].get("budget_cent"), 1000)
        self.assertNotIn("budget_cent", interests["DEMO-COS-01"])
        self.assertNotIn("budget_cent", result["commercial_intent"])

    def test_negation_and_refusal_have_separate_events(self):
        result = self.analyze("Non cerco il mascara. Non voglio lo struccante", self.products)
        self.assertFalse(result["candidate_codes"])
        self.assertFalse(result["commercial_intent"]["product_codes"])
        kinds = {e["kind"] for e in result["events"]}
        self.assertTrue({"negation", "refusal"} <= kinds)
        named_refusals = [item for item in result["evidence"]
                          if item["kind"] == "refusal" and item["product_codes"]]
        self.assertEqual([item["product_codes"] for item in named_refusals], [["DEMO-COS-02"]])

    def test_negative_alternative_does_not_erase_different_explicit_request(self):
        result = self.analyze("Cerco un mascara, non uno struccante", self.products)
        self.assertEqual(result["candidate_codes"], ["DEMO-COS-01"])
        self.assertEqual(result["commercial_intent"]["product_codes"], ["DEMO-COS-01"])

    def test_past_use_and_previously_stated_purchase_do_not_trigger_offers(self):
        for text in ("Banco Demo A l’ho usato il mese scorso", "Il mese scorso cercavo un mascara waterproof"):
            with self.subTest(text=text):
                result = self.analyze(text, self.products)
                self.assertFalse(result["commercial_intent"]["product_codes"])
                self.assertFalse(result["candidate_codes"])
                self.assertIn("past", [e["kind"] for e in result["events"]])

    def test_correction_retires_earlier_candidate_and_allows_new_explicit_request(self):
        result = self.analyze("Cerco un mascara, anzi, cerco uno struccante", self.products)
        self.assertEqual(result["candidate_codes"], ["DEMO-COS-02"])
        self.assertEqual(result["commercial_intent"]["product_codes"], ["DEMO-COS-02"])
        self.assertIn("correction", [e["kind"] for e in result["events"]])
        self.assertFalse(any(e["product_codes"] == ["DEMO-COS-01"] and e["kind"] == "product_candidate"
                             for e in result["evidence"]))

    def test_pronominal_refusal_retires_previous_request(self):
        result = self.analyze("Cerco un mascara. No, non lo voglio", self.products)
        self.assertFalse(result["candidate_codes"])
        self.assertFalse(result["commercial_intent"]["product_codes"])

    def test_pronominal_negation_retires_previous_request(self):
        result = self.analyze("Cerco un mascara. Non lo cerco", self.products)
        self.assertFalse(result["candidate_codes"])
        self.assertFalse(result["commercial_intent"]["product_codes"])

    def test_proposal_and_acceptance_leave_manual_confirmation_pending(self):
        for text, event in (("Le propongo Banco Demo A", "proposal"), ("Va bene Banco Demo A", "acceptance")):
            with self.subTest(text=text):
                result = self.analyze(text, self.products)
                self.assertEqual(result["phase"]["value"], "Verifica prodotto")
                self.assertIn(event, [e["kind"] for e in result["events"]])
                self.assertFalse(result["commercial_intent"]["product_codes"])

    def test_partial_uses_same_rule_and_span_until_revised(self):
        provisional = self.analyze("Cerco un mascara", self.products, partial=True)
        final = self.analyze("Cerco un mascara", self.products)
        revised = self.analyze("Non cerco un mascara", self.products, partial=True)
        self.assertTrue(provisional["evidence"])
        self.assertTrue(all(item["state"] == "provisional" for item in provisional["evidence"]))
        self.assertEqual([e["id"] for e in provisional["evidence"]], [e["id"] for e in final["evidence"]])
        self.assertTrue(all(item["state"] == "active" for item in final["evidence"]))
        self.assertFalse(revised["candidate_codes"])
        self.assertFalse(revised["commercial_intent"]["product_codes"])

    def test_explicit_recipients_use_only_declared_relation_and_age(self):
        for text, kind, relation, fields in (
            ("È per mio figlio di 14 anni", "altra_persona", "figlio", {"age": 14}),
            ("È per mio padre di 78 anni, prende già delle medicine", "altra_persona", "padre", {"age": 78}),
            ("È per me", "sé", None, {}),
            ("È per mia figlia", "altra_persona", "figlia", {}),
        ):
            with self.subTest(text=text):
                result = self.analyze(text, self.products)
                self.assertEqual(result["recipient"], {
                    "kind": kind, "relation": relation, "declared_fields": fields, "source": "dichiarato",
                })

    def test_unconnected_age_negation_and_question_do_not_declare_recipient(self):
        for text in ("Mario ha 78 anni", "Non è per mio figlio", "È per tuo figlio?", "È per suo figlio?", "Per me costa troppo"):
            with self.subTest(text=text):
                result = self.analyze(text, self.products)
                self.assertEqual(result["recipient"]["kind"], "sconosciuto")
                self.assertEqual(result["recipient"]["declared_fields"], {})

    def test_speaker_age_does_not_transfer_to_declared_other_recipient(self):
        result = self.analyze("È per mio padre ho 14 anni", self.products)
        self.assertEqual(result["recipient"]["relation"], "padre")
        self.assertEqual(result["recipient"]["declared_fields"], {})

    def test_recipient_gender_is_explicit_and_does_not_trigger_offer(self):
        for text, fields in (("È per una donna di 34 anni", {"gender": "donna", "age": 34}),
                             ("È per un uomo", {"gender": "uomo"}), ("È per mio padre", {})):
            with self.subTest(text=text):
                result = self.analyze(text, self.products)
                self.assertEqual(result["recipient"]["declared_fields"], fields)
                self.assertFalse(result["commercial_intent"]["product_codes"])
                self.assertFalse(result["candidate_codes"])
                evidence = next(item for item in result["evidence"] if item["kind"] == "recipient")
                self.assertEqual(evidence["source"]["id"], "destinatario-dichiarato")
        self.assertEqual(self.analyze("Non è per una donna")["recipient"]["kind"], "sconosciuto")

    def test_later_negation_retires_the_same_recipient(self):
        result = self.analyze("È per mio figlio di 14 anni. Anzi, non è per mio figlio")
        self.assertEqual(result["recipient"]["kind"], "sconosciuto")
        self.assertFalse(any(item["kind"] == "recipient" for item in result["evidence"]))

    def test_service_requires_operator_context(self):
        result = self.analyze("C’è una farmacia di turno stasera?", self.products)
        self.assertEqual(result["phase"]["value"], "Servizio")
        self.assertEqual(result["phase"]["missing"], ["comune", "data"])
        self.assertEqual(result["service"], {"kind": "turni"})
        self.assertEqual(self.analyze("Quali sono gli orari?")["service"]["kind"], "orari")
        self.assertEqual(self.analyze("Avete un sito web?")["service"]["kind"], "sito")

    def test_clinical_topic_opens_question_without_a_product(self):
        result = self.analyze("Sono in menopausa", self.products)
        self.assertEqual(result["phase"]["value"], "Domande")
        self.assertTrue(result["phase"]["missing"])
        evidence, = (item for item in result["evidence"] if item["kind"] == "topic")
        self.assertEqual(evidence["source"]["id"], "menopausa-e-pillola")
        self.assertFalse(result["candidate_codes"])
        self.assertFalse(result["commercial_intent"]["product_codes"])

    def test_cosmetic_removal_is_only_a_request_signal(self):
        result = self.analyze("Cerco un mascara waterproof. Come lo rimuovo?", self.products)
        matches = [item for item in result["evidence"] if item["kind"] == "cosmetic_removal"]
        self.assertEqual(len(matches), 1)
        removal, = matches
        self.assertEqual(removal["source"]["id"], "struccante-demo")
        self.assertFalse(removal["product_codes"])
        self.assertEqual(result["candidate_codes"], ["DEMO-COS-01"])
        result = self.analyze("Non voglio sapere come rimuovere il mascara", self.products)
        self.assertFalse(any(item["kind"] == "cosmetic_removal" for item in result["evidence"]))

    def test_low_signal_and_prefix_collisions_are_insufficient(self):
        result = self.analyze("Parliamo di mascarata", self.products)
        self.assertEqual(result["phase"]["value"], "Raccolta")
        self.assertTrue(result["phase"]["missing"])
        self.assertFalse(result["evidence"])

    def test_age_in_italian_words_is_kept_when_explicitly_declared(self):
        for text, age in (("È per mio figlio di quattordici anni", 14), ("Per mio padre di settantotto anni", 78)):
            with self.subTest(text=text):
                self.assertEqual(self.analyze(text)["recipient"]["declared_fields"], {"age": age})


if __name__ == "__main__":
    unittest.main()
