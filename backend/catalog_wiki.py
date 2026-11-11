"""Render source-bounded product sheets from an additive catalog seed."""

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = ROOT / "database" / "catalogo-ampliamento-20261109.json"
DEFAULT_WIKI = ROOT / "wiki" / "schede"


def _toml_string(value):
    return json.dumps(str(value), ensure_ascii=False)


def _source_line(source):
    return f"- [{source['title']}]({source['url']}) — {source.get('version') or 'consultata il ' + source['consulted_at']}."


def render_page(product):
    code = product["code"]
    title = product["name"]
    veterinary = product["category"] == "medicinale_veterinario"
    verified = product.get("market_status") == "verificato"
    status = "documentata" if verified else "bozza"
    main_source = product.get("market_source") or product.get("composition_source")
    fields = [
        "+++",
        f"titolo = {_toml_string(title)}",
        'tipo = "prodotto"',
        f"stato = {_toml_string(status)}",
        f"prodotto = {_toml_string(code)}",
        f"fonte = {_toml_string(main_source['url']) if main_source else '""'}",
    ]
    if veterinary:
        fields.append(f"specie_destinazione = {_toml_string(product['species_scope'])}")
    fields.extend(["+++", "", "<!-- sales-agents-catalog-seed -->", "", f"# {title}", "", f"- Codice catalogo: **{code}**",
                   f"- Categoria: {product['category']}", f"- Forma: {product['form']}"])
    if product.get("strength"):
        fields.append(f"- Concentrazione riportata: {product['strength']}")
    active = product.get("ingredient_details") or product.get("active_ingredients") or []
    ingredients = []
    for item in active:
        if isinstance(item, str):
            ingredients.append(item)
        elif isinstance(item, dict) and item.get("name"):
            detail = " ".join(str(item[key]) for key in ("amount", "unit") if item.get(key) is not None)
            ingredients.append(item["name"] + (f" ({detail})" if detail else ""))
    if ingredients:
        fields.append("- Principio/i attivo/i registrato/i: " + "; ".join(ingredients))
    if product.get("route"):
        fields.append(f"- Via riportata: {product['route']}")
    if veterinary:
        scope = product["species_scope"]
        fields.extend([f"- Destinazione documentata: **uso veterinario · {scope}**",
                       "- La scheda è solo informativa per il farmacista; la valutazione e l’uso spettano al veterinario.",
                       "- Nessun dosaggio, sostituzione o disponibilità presso una farmacia italiana è registrato."])
    if verified:
        fields.append("- Stato della fonte: identità e presenza del prodotto documentate nella fonte ufficiale indicata.")
    else:
        fields.extend(["- Stato della fonte: commercializzazione italiana attuale non verificata.",
                       "- Scheda esclusa dal recupero automatico finché la presenza corrente sul mercato non è verificata."])
    fields.extend(["- Prezzo al banco e scorte locali: **dato non disponibile**; nessun valore è stato inventato.",
                   "- Relazioni sintomo-prodotto: solo quelle presenti nel seed separato, con stato `candidata`; non sono consigli approvati.",
                   "", "## Fonti", ""])
    sources, seen = [], set()
    for key in ("market_source", "composition_source", "regulatory_source"):
        source = product.get(key)
        if not isinstance(source, dict) or source.get("url") in seen:
            continue
        seen.add(source["url"])
        sources.append(source)
    fields.extend(_source_line(source) for source in sources)
    fields.append("")
    return "\n".join(fields)


def sync(seed=DEFAULT_SEED, wiki_dir=DEFAULT_WIKI, *, check=False, force=False):
    payload = json.loads(Path(seed).read_text(encoding="utf-8"))
    products = payload.get("products")
    if not isinstance(products, list):
        raise ValueError("Il seed deve contenere un elenco products.")
    wiki_dir = Path(wiki_dir)
    expected = {}
    for product in products:
        if not isinstance(product, dict) or not isinstance(product.get("code"), str):
            raise ValueError("Record prodotto non valido nel seed wiki.")
        expected[product["code"].casefold() + ".md"] = render_page(product)
    mismatches = []
    for name, content in expected.items():
        path = wiki_dir / name
        existing = path.read_text(encoding="utf-8") if path.is_file() else None
        if check:
            if existing != content:
                mismatches.append(name)
            continue
        if existing is not None and existing != content and "<!-- sales-agents-catalog-seed -->" not in existing:
            if not force:
                raise FileExistsError(f"La scheda esistente non è generata dal seed: {path}")
        path.write_text(content, encoding="utf-8", newline="\n")
    if mismatches:
        raise ValueError("Schede assenti o non allineate al seed: " + ", ".join(mismatches))
    return {"pages": len(expected), "checked": check, "wiki_dir": str(wiki_dir)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Genera schede wiki dai record di un seed catalogo.")
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--wiki-dir", type=Path, default=DEFAULT_WIKI)
    parser.add_argument("--check", action="store_true", help="verifica senza scrivere")
    parser.add_argument("--force", action="store_true", help="sovrascrive anche schede non marcate come generate")
    args = parser.parse_args(argv)
    print(json.dumps(sync(args.seed, args.wiki_dir, check=args.check, force=args.force),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
