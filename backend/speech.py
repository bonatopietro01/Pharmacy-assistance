"""Read Vosk alternatives without replacing the original transcript."""

from backend.conversation import analyze


def decode_result(payload, final):
    if not final:
        return payload.get("partial", ""), ()
    alternatives = payload.get("alternatives")
    if not isinstance(alternatives, list):
        return payload.get("text", ""), ()
    phrases = tuple(
        item["text"] for item in alternatives[:3]
        if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip()
    )
    return (phrases[0], phrases[1:]) if phrases else ("", ())


def find_alternative_codes(primary, alternatives, product_terms):
    """Return bounded, catalogue-only candidates for manual correction."""
    def codes(phrase):
        return dict.fromkeys(
            code for item in analyze(phrase, product_terms)["evidence"]
            if (item["kind"] == "spoken_match" or
                item["kind"] == "product_mention" and item.get("mention_context") != "excluded"
                and item.get("matched_term_basis") in {"product_name", "product_code", "catalog_alias", "demo_wiki_alias"})
            for code in item["product_codes"]
        )

    primary_codes = codes(primary)
    result = dict.fromkeys(code for phrase in alternatives[:2] if phrase != primary
                           for code in codes(phrase) if code not in primary_codes)
    return list(result)[:6]
