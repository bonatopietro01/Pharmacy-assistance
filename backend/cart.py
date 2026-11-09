"""Pure helpers for a volatile, non-persistent counter-session cart."""

from copy import deepcopy
from datetime import date
from typing import Any, Mapping


def empty_cart() -> dict[str, list[dict[str, Any]]]:
    """Return fresh mutable state for one listening session."""
    return {"items": []}


def _price(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _source(value: Any) -> Any:
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, Mapping) and value:
        return deepcopy(dict(value))
    return None


def _is_demo(display: Mapping[str, Any], source: Any) -> bool:
    if display.get("dataset_type") == "demo":
        return True
    if isinstance(source, str):
        return "demo" in source.casefold() or "dimostr" in source.casefold()
    if isinstance(source, Mapping):
        return source.get("kind") == "demo" or any(
            marker in str(source.get(key, "")).casefold()
            for key in ("label", "id") for marker in ("demo", "dimostr")
        )
    return False


def _item_for(product: Mapping[str, Any], code: str) -> dict[str, Any]:
    display = product.get("display")
    commercial = product.get("commercial")
    if not isinstance(display, Mapping) or not isinstance(commercial, Mapping):
        raise ValueError("Dati catalogo non validi per il carrello.")
    if display.get("code") != code or not isinstance(display.get("name"), str) or not display["name"].strip():
        raise ValueError("Seleziona uno SKU esatto presente nel catalogo.")

    source = _source(commercial.get("bank_price_source"))
    unit_price = _price(commercial.get("bank_price_cents")) if source is not None else None
    package_label = product.get("package_label")
    if not isinstance(package_label, str) or not package_label.strip():
        package_label = display.get("package_label") or display.get("package") or display.get("form_label") or display.get("form")
    if not isinstance(package_label, str) or not package_label.strip():
        package_label = None

    return {
        "code": code,
        "name": display["name"].strip(),
        "package_label": package_label.strip() if package_label else None,
        "quantity": 0,
        "unit_price_cents": unit_price,
        "price_source": source,
        "demo": _is_demo(display, source),
        "applied_offer": None,
    }


def add_item(cart: dict[str, Any], product: Mapping[str, Any], code: str, *, package_label: str | None = None) -> dict[str, Any]:
    """Add one exact catalog SKU, incrementing its existing quantity."""
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Seleziona uno SKU esatto presente nel catalogo.")
    if not isinstance(cart, dict) or not isinstance(cart.get("items"), list):
        raise ValueError("Carrello di sessione non valido.")
    details = dict(product)
    if package_label is not None:
        details["package_label"] = package_label
    candidate = _item_for(details, code)
    existing = next((item for item in cart["items"] if item.get("code") == code), None)
    if existing is None:
        candidate["quantity"] = 1
        cart["items"].append(candidate)
    else:
        if type(existing.get("quantity")) is not int or existing["quantity"] < 1:
            raise ValueError("Quantità del carrello non valida.")
        existing["quantity"] += 1
    return serialize_cart(cart)


def remove_item(cart: dict[str, Any], code: str) -> dict[str, Any]:
    """Remove an exact SKU from the volatile cart; missing codes are harmless."""
    if not isinstance(cart, dict) or not isinstance(cart.get("items"), list):
        raise ValueError("Carrello di sessione non valido.")
    cart["items"] = [item for item in cart["items"] if item.get("code") != code]
    return serialize_cart(cart)


def _validated_offer(code: str, offer: Mapping[str, Any], today: str | None = None) -> dict[str, Any]:
    offer_code = offer.get("codice") or offer.get("code")
    product_code = offer.get("prodotto_codice") or offer.get("product_code")
    price = _price(offer.get("prezzo_cent", offer.get("price_cents")))
    status = offer.get("stato", offer.get("status"))
    availability = offer.get("disponibilita", offer.get("availability"))
    start = offer.get("inizio", offer.get("start_date"))
    end = offer.get("fine", offer.get("end_date"))
    day = today or date.today().isoformat()
    try:
        valid_dates = (date.fromisoformat(start).isoformat() == start
                       and date.fromisoformat(end).isoformat() == end)
    except (TypeError, ValueError):
        valid_dates = False
    if (not isinstance(offer_code, str) or not offer_code.strip() or product_code != code
            or price is None or status not in {"attiva", "demo"}
            or type(availability) is not int or availability <= 0
            or not isinstance(start, str) or not isinstance(end, str)
            or not valid_dates or not start <= day <= end):
        raise ValueError("L’offerta non è valida e disponibile per questo SKU.")
    return {
        "code": offer_code,
        "title": offer.get("titolo", offer.get("title")),
        "price_cents": price,
        "benefit": offer.get("beneficio", offer.get("benefit")),
        "start_date": start,
        "end_date": end,
        "demo": offer.get("dimostrativa") is True or offer.get("demo") is True or status == "demo",
    }


def apply_offer(cart: dict[str, Any], code: str, offer: Mapping[str, Any], *, today: str | None = None) -> dict[str, Any]:
    """Apply a pre-filtered offer only to the matching SKU already in cart."""
    if not isinstance(cart, dict) or not isinstance(cart.get("items"), list):
        raise ValueError("Carrello di sessione non valido.")
    item = next((row for row in cart["items"] if row.get("code") == code), None)
    if item is None:
        raise ValueError("Aggiungi prima al carrello lo SKU dell’offerta.")
    promotion = _validated_offer(code, offer, today)
    base = _price(item.get("unit_price_cents"))
    if base is not None and promotion["price_cents"] > base:
        raise ValueError("Il prezzo promozionale non può superare il prezzo di catalogo.")
    item["applied_offer"] = promotion
    return serialize_cart(cart)


def remove_offer(cart: dict[str, Any], code: str, offer_code: str | None = None) -> dict[str, Any]:
    """Clear a promotion from one exact SKU without changing cart quantity."""
    if not isinstance(cart, dict) or not isinstance(cart.get("items"), list):
        raise ValueError("Carrello di sessione non valido.")
    item = next((row for row in cart["items"] if row.get("code") == code), None)
    if item is not None and (offer_code is None or (item.get("applied_offer") or {}).get("code") == offer_code):
        item["applied_offer"] = None
    return serialize_cart(cart)


def serialize_cart(cart: Mapping[str, Any]) -> dict[str, Any]:
    """Build a detached snapshot with known subtotals and an explicit partial flag."""
    if not isinstance(cart, Mapping) or not isinstance(cart.get("items"), list):
        raise ValueError("Carrello di sessione non valido.")
    rows = []
    item_count = 0
    total = 0
    original_total = 0
    total_partial = False
    original_partial = False
    savings = 0

    for raw in cart["items"]:
        if not isinstance(raw, Mapping):
            continue
        quantity = raw.get("quantity")
        code = raw.get("code")
        if (not isinstance(code, str) or not code or type(quantity) is not int or quantity < 1):
            continue
        base_price = _price(raw.get("unit_price_cents"))
        promotion = raw.get("applied_offer") if isinstance(raw.get("applied_offer"), Mapping) else None
        promo_price = _price(promotion.get("price_cents")) if promotion else None
        effective_price = promo_price if promo_price is not None else base_price
        subtotal = effective_price * quantity if effective_price is not None else None
        regular_subtotal = base_price * quantity if base_price is not None else None
        if subtotal is None:
            total_partial = True
        else:
            total += subtotal
        if regular_subtotal is None:
            original_partial = True
        else:
            original_total += regular_subtotal
        if base_price is not None and promo_price is not None and promo_price <= base_price:
            savings += (base_price - promo_price) * quantity
        item_count += quantity
        rows.append({
            "code": code,
            "name": raw.get("name"),
            "package_label": raw.get("package_label"),
            "quantity": quantity,
            "unit_price_cents": base_price,
            "price_source": deepcopy(raw.get("price_source")),
            "demo": raw.get("demo") is True,
            "applied_offer": deepcopy(dict(promotion)) if promotion else None,
            "subtotal_cents": subtotal,
        })

    return {
        "items": rows,
        "item_count": item_count,
        "total_cents": total,
        "partial": total_partial,
        "original_total_cents": original_total,
        "original_partial": original_partial,
        "savings_cents": savings,
    }
