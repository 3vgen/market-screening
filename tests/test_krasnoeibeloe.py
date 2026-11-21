import json
from pathlib import Path

from market_screening.adapters.krasnoeibeloe import parse_search, parse_search_items
from market_screening.models import Store

FIX = Path(__file__).parent / "fixtures"
PAGE = (FIX / "krasnoeibeloe_search.html").read_text(encoding="utf-8")
GET_DATA = json.loads((FIX / "krasnoeibeloe_getdata.json").read_text(encoding="utf-8"))
STORE = Store("krasnoeibeloe", "4500000")


def products():
    return {p.product_id: p for p in parse_search(PAGE, GET_DATA, STORE)}


def test_items_are_products_only():
    ids = [i["id"] for i in parse_search_items(PAGE)]
    assert ids == ["4694555", "3325567", "4699272"]  # news article (iblock 61) dropped


def test_unpublished_price_is_skipped():
    assert set(products()) == {"4694555", "3325567"}  # 4699272 has price 0 ("ЦЕНА" button)


def test_price_volume_stock():
    p = products()["4694555"]
    assert p.name == "Пиво Как тогда Жигулевское 1961 светлое фильтрованное пастеризованное ст"
    assert p.price == 79.99
    assert (p.unit_price, p.unit) == (177.76, "l")  # 0.45 l
    assert p.stock == 16.0
    assert p.store == "krasnoeibeloe:4500000"
    assert p.url.startswith("https://krasnoeibeloe.ru/catalog/")
    assert not any(b.startswith("priceByRegion") for b in p.badges)


def test_lower_regional_price_is_a_badge():
    p = products()["3325567"]
    assert p.price == 54.99
    assert "priceByRegion 44.89 ₽" in p.badges
    assert (p.unit_price, p.unit) == (177.39, "l")  # 0.31 l


def test_no_items_no_data():
    assert parse_search("<html></html>", None, STORE) == []
