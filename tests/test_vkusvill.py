from pathlib import Path

from market_screening.adapters.vkusvill import parse_search_page
from market_screening.models import Store

PAGE = (Path(__file__).parent / "fixtures" / "vkusvill_search.html").read_text(encoding="utf-8")
STORE = Store("vkusvill", "moscow")


def products():
    return {p.product_id: p for p in parse_search_page(PAGE, STORE)}


def test_parses_all_cards():
    assert set(products()) == {"36296", "100", "200"}


def test_packed_item_with_promo():
    p = products()["36296"]
    assert p.name == "Молоко 2,5% в бутылке, 900 мл"
    assert p.price == 100.0
    assert p.old_price == 120.0 and p.is_promo
    assert (p.unit_price, p.unit) == (111.11, "l")
    assert p.url == "https://vkusvill.ru/goods/moloko-2-36296/"
    assert p.store == "vkusvill:moscow"


def test_weighted_item_price_is_per_kg():
    p = products()["100"]
    assert p.is_weighted
    assert p.price == 1168.0  # "1 168" with a space as thousands separator
    assert (p.unit_price, p.unit) == (1168.0, "kg")
    assert not p.is_promo


def test_fixed_weight_piece_uses_datalayer_price_per_kg():
    p = products()["200"]
    assert not p.is_weighted
    assert p.price == 209.16
    assert (p.unit_price, p.unit) == (996.0, "kg")
    assert p.name == 'Сыр "Российский", ~210 г'
