import json
from pathlib import Path

from market_screening.adapters.dixy import listing_store_address, listing_url, parse_listing
from market_screening.models import Store

DATA = json.loads((Path(__file__).parent / "fixtures" / "dixy_listing.json").read_text("utf-8"))
STORE = Store("dixy", "1000")


def products():
    return {p.product_id: p for p in parse_listing(DATA, STORE)}


def test_parses_all_cards():
    assert set(products()) == {"210289", "211897", "209399", "209587"}
    assert listing_store_address(DATA).startswith("100000, Москва")


def test_regular_item_no_promo():
    p = products()["210289"]
    assert p.price == 129.99 and not p.is_promo and p.old_price is None
    # size from the title (950 мл), not the gross "weight" field (1000 гр)
    assert (p.unit_price, p.unit) == (136.83, "l")
    assert p.stock == 35
    assert p.store == "dixy:1000"
    assert p.url.startswith("https://dixy.ru/product/")


def test_crossed_price_is_promo():
    p = products()["211897"]
    assert p.price == 99.99 and p.old_price == 109.99 and p.is_promo


def test_weighted_per_kg():
    p = products()["209399"]
    assert p.is_weighted and (p.unit_price, p.unit) == (129.99, "kg")


def test_weighted_promo_with_thousands_separator():
    p = products()["209587"]
    assert p.is_weighted and p.price == 799.9
    assert p.old_price == 1119.9 and p.is_promo
    assert (p.unit_price, p.unit) == (799.9, "kg")


def test_listing_url_uses_full_site_parameter_set():
    url = listing_url("молоко")
    assert "perPage=30" in url
    assert url.endswith("&getFullData&gl_filter=&useTracking=true&collect_stat")
