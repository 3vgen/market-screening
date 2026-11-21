import asyncio

import pytest

from market_screening import server
from market_screening.adapters.base import Adapter
from market_screening.adapters.dixy import _last_page, promos_url
from market_screening.adapters.krasnoeibeloe import _promo_num, parse_promo_page
from market_screening.adapters.pyaterochka import _category_keys, is_promo_product
from market_screening.adapters.vkusvill import parse_promo_page as vv_parse_promo_page
from market_screening.models import Product, Store

# ---------- base: caching and the default "no promos" ----------


class _Fake(Adapter):
    chain = "fake"

    def __init__(self):
        super().__init__()
        self.calls = 0

    async def _search(self, store, query, limit):
        return []


class _FakeWithPromos(_Fake):
    async def _promos(self, store, limit):
        self.calls += 1
        return [Product(store=store.key, product_id="1", name="x", price=1.0)]


def test_promos_default_raises():
    with pytest.raises(NotImplementedError):
        asyncio.run(_Fake().promos(Store("fake", "1")))


def test_promos_are_cached_per_store_and_limit():
    a = _FakeWithPromos()
    s = Store("fake", "1")

    async def run():
        await a.promos(s, 5)
        await a.promos(s, 5)
        await a.promos(s, 10)
        await a.promos(Store("fake", "2"), 5)

    asyncio.run(run())
    assert a.calls == 3


# ---------- X5 (Pyaterochka / Chizhik) helpers ----------


@pytest.mark.parametrize(
    "product, expected",
    [
        ({"prices": {"regular": "100", "discount": "80"}}, True),
        ({"prices": {"regular": "100", "discount": "100"}}, False),
        ({"prices": {"regular": "100", "discount": None}}, False),
        ({"prices": {"regular": "100", "cpd_promo_price": "90"}}, True),
        ({"prices": {"regular": "100", "markdown": {"price": 50}}}, True),
        ({"prices": {"regular": "100"}, "is_promo": True}, True),
        ({}, False),
    ],
)
def test_is_promo_product(product, expected):
    assert is_promo_product(product) is expected


def test_category_keys_walks_tree_with_fallback_field():
    tree = [
        {"id": "a", "categories": [{"id": "a1"}, {"code": "a2", "categories": [{"id": "a2x"}]}]},
        {"id": "b"},
        {"name": "no key at all"},
    ]
    assert _category_keys(tree, "id", []) == ["a", "a1", "a2", "a2x", "b"]


# ---------- Dixy ----------


def test_dixy_promos_url_paginates_card_discount_section():
    url = promos_url(per_page=30, page=3)
    assert "sid=839" in url and "perPage=30" in url and "page=3" in url


@pytest.mark.parametrize(
    "data, last",
    [
        ([{"pagenData": {"isLastPage": True}}], True),
        ({"pagenData": {"isLastPage": "Y"}}, True),
        ([{"pagenData": {"isLastPage": False}}], False),
        ([{}], False),
        ([], False),
    ],
)
def test_dixy_last_page(data, last):
    assert _last_page(data) is last


# ---------- Krasnoe&Beloe ----------

KB_STORE = Store("krasnoeibeloe", "1")
KB_PAGE = """
<product :product-id="7" name="Вино красное" discount-price="499<span>,90</span> &#8381;"
         :discount-percent="20" :discount-min-amount="2" :is-discount="1">
  <a href="/catalog/wine/7/"></a><p>0.75 л</p>
</product>
<product :product-id="8" name="Пиво" :discount-percent="10" :is-discount="1">
  <p>0.5 л</p>
</product>
<product :product-id="9" name="Сок" :is-yellow="1"><p>1 л</p></product>
<product :product-id="10" name="Нет в магазине" :is-discount="1"></product>
"""
KB_GET_DATA = {
    "7": {"price": "599.90", "shopAmount": 5},
    "8": {"price": "100", "shopAmount": 0},
    "9": {"price": "120", "shopAmount": 3},
}


def test_kb_promo_num_strips_markup():
    assert _promo_num("499<span>,90</span> &#8381;") == 499.9
    assert _promo_num(None) is None
    assert _promo_num("—") is None


def test_kb_parse_promo_page():
    got = {p.product_id: p for p in parse_promo_page(KB_PAGE, KB_GET_DATA, KB_STORE)}
    assert set(got) == {"7", "8", "9"}  # 10 has no published price -> skipped

    wine = got["7"]
    assert (wine.price, wine.old_price, wine.is_promo) == (499.9, 599.9, True)
    assert wine.badges == ["-20% от 2 шт."]
    assert wine.stock == 5
    assert wine.url.endswith("/catalog/wine/7/")

    beer = got["8"]  # no discount price in markup: computed from the percentage
    assert (beer.price, beer.old_price, beer.is_promo) == (90.0, 100.0, True)

    juice = got["9"]
    assert (juice.price, juice.old_price, juice.is_promo) == (120.0, None, False)
    assert juice.badges == ["спеццена"]


# ---------- VkusVill ----------

VV_STORE = Store("vkusvill", "moscow")
VV_PAGE = """<div>
<div class="ProductCard js-product-card" data-id="42">
  <a href="/goods/syr-gauda-42.html">
  <span class="js-product-v-tizer__title-text">Сыр Гауда</span></a>
  <span class="ProductCard__linkWeight">200 г</span>
  <span class="Price Price--label">160 руб/шт</span><span class="Price _last">200</span>
  <span class="js-datalayer-catalog-list-price">160</span>
  <span class="js-datalayer-catalog-list-price-old">200</span>
</div>
<div class="ProductCard js-product-card" data-id="43">
  <span class="js-product-v-tizer__title-text">Яблоки</span>
  <span class="Price Price--label">99 руб/кг</span><span class="Price _last">129</span>
  <span class="js-datalayer-catalog-list-price">99</span>
  <span class="js-datalayer-catalog-list-price-old">129</span>
</div>
<div class="ProductCard js-product-card" data-id="44">
  <span class="js-product-v-tizer__title-text">Без цены</span>
</div>
</div>"""


def test_vkusvill_parse_promo_page():
    got = {p.product_id: p for p in vv_parse_promo_page(VV_PAGE, VV_STORE)}
    assert set(got) == {"42", "43"}  # card without a price label is dropped

    cheese = got["42"]
    assert cheese.name == "Сыр Гауда, 200 г"
    assert (cheese.price, cheese.old_price, cheese.is_promo) == (160.0, 200.0, True)
    assert (cheese.unit_price, cheese.unit) == (800.0, "kg")
    assert cheese.url.endswith("/goods/syr-gauda-42.html")

    apples = got["43"]
    assert apples.is_weighted
    assert (apples.unit_price, apples.unit) == (99.0, "kg")
    assert apples.old_price == 129.0


# ---------- server tool ----------


def test_promos_tool_adds_discount_and_isolates_errors(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[[stores]]\nchain = "magnit"\nstore_code = "1"\n\n'
        '[[stores]]\nchain = "chizhik"\nstore_code = "2"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("MARKET_SCREENING_CONFIG", str(cfg))

    class Ok:
        async def promos(self, store, limit):
            return [
                Product(store=store.key, product_id="1", name="a", price=75.0, old_price=100.0),
                Product(store=store.key, product_id="2", name="b", price=50.0),
            ]

    class Broken:
        async def promos(self, store, limit):
            raise RuntimeError("down")

    monkeypatch.setattr(server, "_adapter", lambda chain: Ok() if chain == "magnit" else Broken())
    res = asyncio.run(server.promos())

    assert res["magnit:1"][0]["discount_pct"] == 25
    assert "discount_pct" not in res["magnit:1"][1]
    assert res["chizhik:2"] == {"error": "RuntimeError: down"}

    only = asyncio.run(server.promos(stores=["magnit:1"]))
    assert list(only) == ["magnit:1"]
