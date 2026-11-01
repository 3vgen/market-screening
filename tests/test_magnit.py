from market_screening.adapters.magnit import parse_item
from market_screening.models import Store

STORE = Store("magnit", "123456")

PACKED = {
    "id": "8000034165",
    "productId": "8000034165",
    "name": "Молоко безлактозное Простоквашино 2.5% 970мл",
    "price": 16999,
    "promotion": {"isPromotion": True, "oldPrice": 19999, "endDate": "2026-11-24T00:00:00Z"},
    "quantity": 18,
    "seoCode": "prostokvashino_moloko",
    "badges": [{"text": "По карте"}],
    "weighted": {"isWeighted": False, "unitPrice": None},
}

WEIGHTED = {
    "id": "1",
    "name": "Бананы фасованные",
    "price": 16086,
    "promotion": {"isPromotion": False, "oldPrice": None},
    "weighted": {"isWeighted": True, "unitPrice": 11490, "shelfWeight": 1400},
    "badges": [],
}


def test_packed_item():
    p = parse_item(PACKED, STORE)
    assert p.price == 169.99
    assert p.old_price == 199.99
    assert p.is_promo
    assert p.unit == "l" and p.unit_price == 175.25
    assert p.badges == ["По карте"]
    assert p.store == "magnit:123456"
    assert p.url.endswith("8000034165-prostokvashino_moloko?shopCode=123456")


def test_weighted_item_uses_api_unit_price():
    p = parse_item(WEIGHTED, STORE)
    assert p.is_weighted
    assert p.price == 160.86
    assert (p.unit_price, p.unit) == (114.9, "kg")


def test_loyalty_flag_without_old_price_is_not_a_discount():
    item = {**WEIGHTED, "promotion": {"isPromotion": True, "oldPrice": None, "endDate": "2026-11-16"}}
    p = parse_item(item, STORE)
    assert not p.is_promo
    assert p.old_price is None and p.promo_until is None
