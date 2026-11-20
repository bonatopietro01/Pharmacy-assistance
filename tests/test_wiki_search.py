"""Ricerca ibrida nella wiki: chunk, hash incrementale, fusione RRF, accettazione.

I test unitari usano un embedder finto (nessun download). Il test di
accettazione con il modello reale parte solo se sentence-transformers e il
modello sono già presenti in locale.
"""

import tempfile
import unittest
from pathlib import Path

from backend import speech_faster_whisper as fw
from backend import wiki_search as ws

PAGES = {
    "bilancio": {"titolo": "Bilancio della farmacia", "termini": [], "testo":
                 "# Bilancio della farmacia\n\n## Spese mensili\n\nLe spese per affitto, personale e utenze "
                 "vanno registrate ogni mese.\n\n## Budget annuale\n\nIl budget fissa quanto si può spendere "
                 "per gli acquisti dell'anno."},
    "aic": {"titolo": "Codici AIC", "termini": ["AIC"], "testo":
            "## Che cos'è\n\nL'AIC è il codice di autorizzazione all'immissione in commercio stampato sulla "
            "confezione.\n\n## Lettura\n\nIl bollino riporta il codice AIC a nove cifre."},
    "tosse": {"titolo": "Tosse secca", "termini": ["tosse"], "testo":
              "## Domande\n\nDa quanto tempo dura la tosse? Ha febbre?"},
}

GROUPS = {"spes": 0, "budget": 0, "cost": 0, "spend": 0, "acquist": 0,
          "aic": 1, "codic": 1, "bollin": 1, "toss": 2, "febbr": 2}


class FakeEmbedder:
    """Bag-of-concepts vectors: 'costi', 'spese' and 'budget' share one axis."""

    def __init__(self):
        self.calls = 0

    def encode(self, texts, query=False):
        self.calls += len(texts)
        vectors = []
        for text in texts:
            vector = [0.0, 0.0, 0.0, 0.01]
            for word in text.casefold().split():
                for root, axis in GROUPS.items():
                    if word.startswith(root):
                        vector[axis] += 1.0
            norm = sum(v * v for v in vector) ** 0.5
            vectors.append([v / norm for v in vector])
        return vectors


class ChunkTests(unittest.TestCase):
    def test_sections_carry_page_title_and_heading(self):
        chunks = ws.chunk_page("bilancio", PAGES["bilancio"])
        self.assertEqual([c["sezione"] for c in chunks], ["Spese mensili", "Budget annuale"])
        self.assertTrue(all(c["titolo"] == "Bilancio della farmacia" for c in chunks))

    def test_long_sections_are_split(self):
        page = {"titolo": "Lunga", "testo": "## A\n\n" + "\n\n".join("parola " * 60 for _ in range(8))}
        chunks = ws.chunk_page("lunga", page)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c["testo"]) <= ws.MAX_CHUNK_CHARS for c in chunks))


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.index = Path(self.tmp.name) / "vettori.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_changed_pages_are_reembedded(self):
        embedder = FakeEmbedder()
        first = ws.update_index(PAGES, embedder, "finto", self.index)
        self.assertEqual(first["pagine_ricalcolate"], 3)
        calls = embedder.calls
        again = ws.update_index(PAGES, embedder, "finto", self.index)
        self.assertEqual(again["pagine_ricalcolate"], 0)
        self.assertEqual(embedder.calls, calls)
        changed = {**PAGES, "tosse": {**PAGES["tosse"], "testo": PAGES["tosse"]["testo"] + " Fuma?"}}
        third = ws.update_index(changed, embedder, "finto", self.index)
        self.assertEqual(third["pagine_ricalcolate"], 1)
        self.assertEqual(embedder.calls, calls + 1)
        removed = ws.update_index({k: v for k, v in changed.items() if k != "aic"}, embedder, "finto", self.index)
        self.assertEqual(removed["pagine_rimosse"], 1)

    def test_model_change_rebuilds_index(self):
        embedder = FakeEmbedder()
        ws.update_index(PAGES, embedder, "finto", self.index)
        result = ws.update_index(PAGES, embedder, "altro", self.index)
        self.assertEqual(result["pagine_ricalcolate"], 3)

    def test_meaning_finds_pages_without_the_exact_word(self):
        result = ws.hybrid_search("costi", PAGES, FakeEmbedder(), "finto", self.index)
        self.assertEqual(result["modo"], "ibrida")
        self.assertEqual(result["risultati"][0]["scheda"], "bilancio")
        self.assertIn("significato", result["risultati"][0]["fonti"])

    def test_exact_acronym_stays_first(self):
        result = ws.hybrid_search("AIC", PAGES, FakeEmbedder(), "finto", self.index)
        top = result["risultati"][0]
        self.assertEqual(top["scheda"], "aic")
        self.assertEqual(set(top["fonti"]), {"parole", "significato"})

    def test_results_show_page_section_and_excerpt(self):
        top = ws.hybrid_search("budget acquisti", PAGES, FakeEmbedder(), "finto", self.index)["risultati"][0]
        self.assertEqual((top["scheda"], top["titolo"], top["sezione"]),
                         ("bilancio", "Bilancio della farmacia", "Budget annuale"))
        self.assertIn("budget", top["estratto"].casefold())

    def test_keywords_only_without_model(self):
        result = ws.hybrid_search("costi", PAGES, None, "finto", self.index)
        self.assertEqual(result, {"modo": "parole", "risultati": []})
        result = ws.hybrid_search("tosse", PAGES, None, "finto", self.index)
        self.assertEqual([r["scheda"] for r in result["risultati"]], ["tosse"])
        self.assertFalse(self.index.exists())

    def test_input_validation(self):
        with self.assertRaises(ValueError):
            ws.hybrid_search("x" * 5000, PAGES)
        self.assertEqual(ws.hybrid_search("  ", PAGES)["risultati"], [])


class FusionTests(unittest.TestCase):
    def test_rrf_rewards_items_in_both_rankings(self):
        a, b, c = ({"slug": s, "sezione": "", "testo": s} for s in "abc")
        fused = ws.reciprocal_rank_fusion([(a, 9), (b, 8)], [(b, .9), (c, .8)])
        self.assertEqual([item[0]["slug"] for item in fused], ["b", "a", "c"])
        self.assertEqual(fused[0][2], {0: 2, 1: 1})


class ThresholdTests(unittest.TestCase):
    def test_semantic_results_below_threshold_are_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "v.sqlite3"
            result = ws.hybrid_search("costi", PAGES, FakeEmbedder(), "finto", index, threshold=2.0)
            self.assertEqual(result["risultati"], [])
            result = ws.hybrid_search("tosse", PAGES, FakeEmbedder(), "finto", index, threshold=2.0)
            self.assertEqual(result["risultati"][0]["scheda"], "tosse")  # keyword hits always stay


class SemanticOnlyCapTests(unittest.TestCase):
    def test_meaning_only_results_are_capped(self):
        pages = {f"p{i}": {"titolo": f"Spese {i}", "termini": [], "testo": f"## Voce\n\nspese numero {i}"}
                 for i in range(12)}
        with tempfile.TemporaryDirectory() as tmp:
            result = ws.hybrid_search("costi", pages, FakeEmbedder(), "finto", Path(tmp) / "v.sqlite3")
        self.assertEqual(len(result["risultati"]), ws.SEMANTIC_ONLY_MAX_RANK)
        self.assertTrue(all(r["fonti"] == ["significato"] for r in result["risultati"]))


class VocabularyTests(unittest.TestCase):
    def test_wiki_vocabulary_has_titles_terms_and_acronyms(self):
        words = ws.wiki_vocabulary(PAGES)
        for item in ("Bilancio della farmacia", "AIC", "Tosse secca"):
            self.assertIn(item, words)

    def test_prompt_is_deduplicated_and_bounded(self):
        prompt = fw.build_prompt("AIC, Tosse", "aic, Brufen")
        self.assertEqual(prompt, "Tosse, aic, Brufen")
        catalog = ", ".join(f"Nome{i}" for i in range(500))
        prompt = fw.build_prompt("Sigla", catalog)
        self.assertLessEqual(len(prompt), fw.MAX_PROMPT_CHARS)
        self.assertTrue(prompt.endswith("Nome499"))  # catalog terms win, the tail is kept
        self.assertNotIn("Sigla", prompt)

    def test_engine_auto_settings_follow_hardware(self):
        auto = {"modello": "auto", "compute_type": "auto", "device": "auto", "beam_size": "auto"}
        self.assertEqual(fw.resolve(auto, has_cuda=False), ("small", "cpu", "int8"))
        self.assertEqual(fw.resolve(auto, has_cuda=True), ("large-v3-turbo", "cuda", "float16"))
        self.assertEqual(fw.resolve({**auto, "modello": "medium"}, has_cuda=False), ("medium", "cpu", "int8"))


class FasterWhisperEngineTests(unittest.TestCase):
    def test_missing_package_raises_a_fixed_error_code(self):
        engine = fw.FasterWhisperEngine()
        original = fw.FasterWhisperEngine.available
        fw.FasterWhisperEngine.available = staticmethod(lambda: False)
        try:
            with self.assertRaises(fw.WhisperError) as caught:
                engine.start()
        finally:
            fw.FasterWhisperEngine.available = original
        self.assertEqual(caught.exception.code, "faster_whisper_non_installato")

    def test_config_is_read_from_the_given_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text('{"faster_whisper": {"modello": "medium", "beam_size": 3}}', encoding="utf-8")
            engine = fw.FasterWhisperEngine(config=path)
        self.assertEqual(engine.conf["modello"], "medium")
        self.assertEqual(engine.beam_size(), 3)

    def test_transcribe_before_start_is_an_error(self):
        with self.assertRaises(fw.WhisperError):
            fw.FasterWhisperEngine().transcribe_wav(b"")


def _real_model():
    if not ws.semantic_available():
        return None
    try:
        return ws.embedder_for(ws.DEFAULT_MODEL)
    except Exception:
        return None


class AcceptanceWithRealModel(unittest.TestCase):
    """Real multilingual model: 'costi' must find 'spese'/'budget'; an exact acronym stays on top."""

    @classmethod
    def setUpClass(cls):
        model = _real_model()
        if model is None:
            raise unittest.SkipTest("modello di embedding locale non disponibile")
        cls.embedder = model
        cls.tmp = tempfile.TemporaryDirectory()
        cls.index = Path(cls.tmp.name) / "vettori.sqlite3"
        cls.pages = {**PAGES, "orari": {"titolo": "Orari di apertura", "termini": [], "testo":
                     "## Turni\n\nLa farmacia apre alle 8:30 e chiude alle 19:30."}}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def search(self, query):
        return ws.hybrid_search(query, self.pages, self.embedder, ws.DEFAULT_MODEL, self.index,
                                threshold=ws.settings()["soglia"])

    def test_costi_finds_spese_and_budget(self):
        result = self.search("costi")
        self.assertEqual(result["risultati"][0]["scheda"], "bilancio")

    def test_acronym_stays_in_top_results(self):
        result = self.search("AIC")
        self.assertEqual(result["risultati"][0]["scheda"], "aic")


if __name__ == "__main__":
    unittest.main()
