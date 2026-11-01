"""Magnit (magnit.ru) — uses the same JSON endpoint the website calls.

No authentication needed. Prices in the API are in kopecks.
"""

from __future__ import annotations

from ..models import Product, Store
from ..units import unit_price
from .base import Adapter

BASE = "https://magnit.ru"
SEARCH_URL = f"{BASE}/webgate/v2/goods/search"


def _rub(kopecks: int | None) -> float | None:
    return None if kopecks is None else round(kopecks / 100, 2)


def parse_item(item: dict, store: Store) -> Product:
    price = _rub(item["price"])
    promo = item.get("promotion") or {}
    weighted = item.get("weighted") or {}
    is_weighted = bool(weighted.get("isWeighted"))

    if is_weighted and weighted.get("unitPrice"):
        per_unit: tuple[float, str] | None = (_rub(weighted["unitPrice"]), "kg")
    else:
        per_unit = unit_price(price, item["name"])

    # isPromotion is also true for plain loyalty-card prices; only a real old price means a discount
    old_price = _rub(promo.get("oldPrice"))
    is_promo = old_price is not None and old_price > price

    product_id = str(item.get("productId") or item["id"])
    seo = item.get("seoCode")
    url = f"{BASE}/product/{product_id}-{seo}?shopCode={store.store_code}" if seo else None

    return Product(
        store=store.key,
        product_id=product_id,
        name=item["name"].strip(),
        price=price,
        old_price=old_price if is_promo else None,
        is_promo=is_promo,
        promo_until=promo.get("endDate") if is_promo else None,
        stock=item.get("quantity"),
        unit_price=per_unit[0] if per_unit else None,
        unit=per_unit[1] if per_unit else None,
        is_weighted=is_weighted,
        badges=[b["text"] for b in item.get("badges") or [] if b.get("text")],
        url=url,
    )


class MagnitAdapter(Adapter):
    chain = "magnit"

    async def _search(self, store: Store, query: str, limit: int) -> list[Product]:
        body = {
            "term": query,
            "pagination": {"limit": limit, "offset": 0},
            "sort": {"order": "desc", "type": "popularity"},
            "includeAdultGoods": True,
            "storeCode": store.store_code,
            "storeType": "1",
            "catalogType": "1",
        }
        resp = await self._client.post(
            SEARCH_URL, json=body, headers={"Origin": BASE, "Referer": f"{BASE}/"}
        )
        resp.raise_for_status()
        return [parse_item(it, store) for it in resp.json().get("items", [])]
