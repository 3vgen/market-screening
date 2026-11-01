import json
from pathlib import Path

from market_screening.adapters.perekrestok import parse_product
from market_screening.models import Store

FEED = json.loads((Path(__file__).parent / "fixtures" / "perekrestok_feed.json").read_text("utf-8"))
STORE = Store("perekrestok", "moscow")


def products():
    return {p.product_id: p for p in (parse_product(i, STORE) for i in FEED["content"]["items"])}


def test_plain_item_prices_are_kopecks():
    p = products()["2059346"]
    assert p.name == "Молоко Домик в деревне стерилизованное 3.2%, 950г"
    assert p.price == 104.99 and not p.is_promo
    assert (p.unit_price, p.unit) == (110.52, "kg")  # size from the title: 950г
    assert p.url == "https://www.perekrestok.ru/cat/114/p/moloko-domik-v-derevne-sterilizovannoe-3-2-950g-2059346"
    assert p.store == "perekrestok:moscow"


def test_discount_uses_gross_price_as_old_price():
    p = next(x for x in products().values() if "Простоквашино" in x.name)
    assert p.price == 99.99 and p.old_price == 119.99 and p.is_promo
    assert "-16%" in p.badges
    assert (p.unit_price, p.unit) == (107.52, "l")


def test_weighted_goods_priced_per_kg():
    bananas = next(x for x in products().values() if x.name == "Бананы фасованные")
    assert bananas.is_weighted and (bananas.unit_price, bananas.unit) == (149.99, "kg")
    cheese = next(x for x in products().values() if "молодой" in x.name)
    assert cheese.is_weighted and cheese.price == 993.99 and cheese.unit == "kg"


def test_size_from_master_data_and_out_of_stock():
    p = products()["9000001"]
    assert (p.unit_price, p.unit) == (99.99, "l")  # 89.99 ₽ / 0.9 l
    assert p.stock == 0.0
