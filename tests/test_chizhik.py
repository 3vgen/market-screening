import json
from pathlib import Path

from market_screening.adapters.chizhik import parse_product
from market_screening.models import Store

ITEMS = json.loads((Path(__file__).parent / "fixtures" / "chizhik_products.json").read_text("utf-8"))
STORE = Store("chizhik", "HBBN")


def products():
    return {p.product_id: p for p in (parse_product(i, STORE) for i in ITEMS)}


def test_regular_packaged_item():
    p = products()["4309774"]
    assert p.price == 34.0 and not p.is_promo and p.old_price is None
    # size from the name (205мл) wins over property_clarification ("200 мл")
    assert (p.unit_price, p.unit) == (165.85, "l")
    assert p.stock == 37.0
    assert p.store == "chizhik:HBBN"


def test_discount_is_promo():
    p = products()["3490515"]
    assert p.price == 159.0 and p.old_price == 179.0 and p.is_promo
    assert (p.unit_price, p.unit) == (1590.0, "kg")


def test_weighted_per_kg():
    p = products()["4275231"]
    assert p.is_weighted
    assert (p.unit_price, p.unit) == (129.0, "kg")


def test_weighted_second_item():
    p = products()["4327479"]
    assert p.is_weighted and (p.unit_price, p.unit) == (749.0, "kg")


def test_conditional_promo_is_a_badge_and_unavailable_means_no_stock():
    p = products()["6001"]
    assert p.price == 89.99 and not p.is_promo
    assert "по акции 79.99 ₽ (% от 2 шт)" in p.badges
    assert p.stock == 0.0
