import json
from pathlib import Path

from market_screening.adapters.pyaterochka import parse_product
from market_screening.models import Store

ITEMS = json.loads((Path(__file__).parent / "fixtures" / "pyaterochka_products.json").read_text("utf-8"))
STORE = Store("pyaterochka", "Y000")


def products():
    return {p.product_id: p for p in (parse_product(i, STORE) for i in ITEMS)}


def test_conditional_promo_is_a_badge_not_the_price():
    p = products()["3255206"]
    assert p.price == 94.99 and not p.is_promo
    assert "по акции 86.99 ₽ (% от 2 шт)" in p.badges
    assert (p.unit_price, p.unit) == (102.14, "l")
    assert p.stock == 186.0


def test_plain_discount():
    p = products()["4001"]
    assert p.price == 219.99 and p.old_price == 249.99 and p.is_promo
    assert (p.unit_price, p.unit) == (549.98, "kg")


def test_weighted_per_kg():
    p = products()["809"]
    assert p.is_weighted
    assert (p.unit_price, p.unit) == (174.99, "kg")


def test_weighted_priced_per_100g():
    p = products()["5002"]
    assert p.is_weighted
    assert (p.unit_price, p.unit) == (589.9, "kg")
    assert "цена за 100 г" in p.badges


def test_name_size_wins_over_package_and_unavailable_means_no_stock():
    p = products()["6003"]
    assert p.unit == "kg"  # name says 320г, package_quantity says 320 мл
    assert p.unit_price == 406.22
    assert p.stock == 0.0
