import json
from pathlib import Path

from market_screening.adapters.fixprice import parse_product
from market_screening.models import Store

ITEMS = json.loads((Path(__file__).parent / "fixtures" / "fixprice_search.json").read_text("utf-8"))
STORE = Store("fixprice", "3")


def products():
    return {p.product_id: p for p in (parse_product(i, STORE) for i in ITEMS)}


def test_parses_fixture():
    assert len(products()) == len(ITEMS) == 3


def test_special_price_is_a_badge():
    p = products()["1001076"]
    assert p.price == 99.0
    assert "спец цена 93.00 ₽" in p.badges
    assert (p.unit_price, p.unit) == (101.75, "l")  # 973 мл
    assert p.stock == 23
    assert p.store == "fixprice:3"
    assert p.url.startswith("https://fix-price.com/catalog/produkty-i-napitki/p-1001076-")


def test_every_item_has_price_and_unit_price():
    for p in products().values():
        assert p.price and p.price > 0
        assert p.unit in ("l", "kg")
