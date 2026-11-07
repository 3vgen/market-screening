"""VkusVill (vkusvill.ru) — parses the server-rendered search page.

No authentication and no JSON API needed: product cards are in the HTML.
Prices are in rubles. The site doesn't take a store in the query, so prices are
for the site's default region (Moscow); `store_code` in config is just a label.
"""

from __future__ import annotations

import html
import re

from ..models import Product, Store
from ..units import unit_price
from .base import Adapter

BASE = "https://vkusvill.ru"
SEARCH_URL = f"{BASE}/search/"
PROMOS_URL = f"{BASE}/goods/set-vashi-skidki/"  # "Ваши скидки" — server-rendered
PAGE_SIZE = 24

_CARD_SPLIT = re.compile(r'class="ProductCard\s+js-product')
_TAG = re.compile(r"<[^>]+>")


def _text(fragment: str | None) -> str:
    if not fragment:
        return ""
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub("", fragment))).replace("\xa0", " ").strip()


def _num(s: str | None) -> float | None:
    if not s:
        return None
    s = re.sub(r"[\s  \xa0]", "", s).replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _span(card: str, cls: str) -> str | None:
    m = re.search(rf'class="[^"]*\b{re.escape(cls)}\b[^"]*"[^>]*>(.*?)</span>', card, re.S)
    return m.group(1) if m else None


def parse_card(card: str, store: Store) -> Product | None:
    pid = re.search(r'data-id="(\d+)"', card)
    title = _text(_span(card, "js-product-v-tizer__title-text"))
    # the label contains nested currency spans, so anchor on the hidden datalayer span after it
    label = re.search(
        r'Price--label"\s*>(.*?)</span>\s*<span class="js-datalayer-catalog-list-price', card, re.S
    )
    if not (pid and title and label):
        return None

    label_text = _text(label.group(1))  # e.g. "168 руб/кг", "209.16 руб/шт"
    m = re.match(r"([\d\s.,  ]+)\s*руб\s*/\s*(\S+)", label_text)
    if not m:
        return None
    price = _num(m.group(1))
    sale_unit = m.group(2)

    weight = _text(_span(card, "ProductCard__linkWeight"))  # "900 мл", "~240 г", "996 ₽ / кг"
    dl_price = _num(_text(_span(card, "js-datalayer-catalog-list-price")))
    dl_old = _num(_text(_span(card, "js-datalayer-catalog-list-price-old")))

    is_weighted = sale_unit == "кг"
    if is_weighted:
        per_unit = (price, "kg")
    elif "₽" in weight and "кг" in weight and dl_price:
        per_unit = (dl_price, "kg")  # fixed-weight piece: datalayer price is per kg
    else:
        per_unit = unit_price(price, f"{title} {weight}")

    old_price = None
    if dl_price and dl_old and dl_old > dl_price:
        old_price = round(price * dl_old / dl_price, 2)

    href = re.search(r'href="(/goods/[^"]+)"', card)
    squash = lambda s: re.sub(r"\s+", "", s)  # "150г" in the title == "150 г" weight
    already_there = squash(weight) in squash(title)
    name = title if not weight or "₽" in weight or already_there else f"{title}, {weight}"

    return Product(
        store=store.key,
        product_id=pid.group(1),
        name=name,
        price=price,
        old_price=old_price,
        is_promo=old_price is not None,
        unit_price=per_unit[0] if per_unit else None,
        unit=per_unit[1] if per_unit else None,
        is_weighted=is_weighted,
        url=f"{BASE}{href.group(1)}" if href else None,
    )


def parse_search_page(page: str, store: Store) -> list[Product]:
    products = []
    for card in _CARD_SPLIT.split(page)[1:]:
        p = parse_card(card, store)
        if p:
            products.append(p)
    return products


def parse_promo_card(card: str, store: Store) -> Product | None:
    # The "Ваши скидки" page lays prices out differently from search: the current
    # price is in the "Price--label" span, the crossed old price in the following
    # "Price _last" span, and the numeric datalayer spans come after both.
    pid = re.search(r'data-id="(\d+)"', card)
    title = _text(_span(card, "js-product-v-tizer__title-text"))
    if not (pid and title):
        return None

    start = card.find("Price--label")
    start = card.find(">", start) + 1  # skip past the opening tag's closing '>'
    end = card.find("Price _last", start)
    if start == -1 or end == -1:
        return None
    label_text = _text(card[start:end])  # e.g. "325 руб/кг"
    m = re.match(r"([\d\s.,  ]+)\s*руб\s*/\s*(\S+)", label_text)
    if not m:
        return None
    price = _num(m.group(1))
    sale_unit = m.group(2)

    weight = _text(_span(card, "ProductCard__linkWeight"))
    dl_price = _num(_text(_span(card, "js-datalayer-catalog-list-price")))
    dl_old = _num(_text(_span(card, "js-datalayer-catalog-list-price-old")))

    is_weighted = sale_unit == "кг"
    if is_weighted:
        per_unit = (price, "kg")
    elif "₽" in weight and "кг" in weight and dl_price:
        per_unit = (dl_price, "kg")  # fixed-weight piece: datalayer price is per kg
    else:
        per_unit = unit_price(price, f"{title} {weight}")

    old_price = None
    if dl_price and dl_old and dl_old > dl_price:
        old_price = round(price * dl_old / dl_price, 2)

    href = re.search(r'href="(/goods/[^"]+)"', card)
    squash = lambda s: re.sub(r"\s+", "", s)
    already_there = squash(weight) in squash(title)
    name = title if not weight or "₽" in weight or already_there else f"{title}, {weight}"

    return Product(
        store=store.key,
        product_id=pid.group(1),
        name=name,
        price=price,
        old_price=old_price,
        is_promo=old_price is not None,
        unit_price=per_unit[0] if per_unit else None,
        unit=per_unit[1] if per_unit else None,
        is_weighted=is_weighted,
        url=f"{BASE}{href.group(1)}" if href else None,
    )


def parse_promo_page(page: str, store: Store) -> list[Product]:
    products = []
    for card in _CARD_SPLIT.split(page)[1:]:
        p = parse_promo_card(card, store)
        if p:
            products.append(p)
    return products


class VkusvillAdapter(Adapter):
    chain = "vkusvill"

    async def _search(self, store: Store, query: str, limit: int) -> list[Product]:
        resp = await self._client.get(SEARCH_URL, params={"type": "products", "q": query})
        resp.raise_for_status()
        return parse_search_page(resp.text, store)[:limit]

    async def _promos(self, store: Store, limit: int) -> list[Product]:
        # Bitrix pager: page 1 has no param, then ?PAGEN_1=N (24 cards/page).
        products: list[Product] = []
        page = 1
        while len(products) < limit and page <= 100:
            params = None if page == 1 else {"PAGEN_1": str(page)}
            resp = await self._client.get(PROMOS_URL, params=params)
            resp.raise_for_status()
            batch = parse_promo_page(resp.text, store)
            if not batch:
                break
            products.extend(batch)
            page += 1
        return products[:limit]
