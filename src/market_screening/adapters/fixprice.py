"""Fix Price (fix-price.com) — the website's public JSON API, plain HTTP.

The API wants an anonymous session token in `X-Key`; any API response hands one
out in its `x-key` header (the site does the same on first load). City is the
`x-city` header: store_code in config is the Fix Price city id (Moscow = 3).
Prices are in rubles (strings).
"""

from __future__ import annotations

from ..models import Product, Store
from ..units import unit_price
from .base import Adapter

SITE = "https://fix-price.com"
API = "https://api.fix-price.com/buyer/v1"
MOSCOW_CITY_ID = "3"


def _f(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def parse_product(p: dict, store: Store) -> Product:
    price = _f(p.get("price"))
    special = _f((p.get("specialPrice") or {}).get("price"))
    badges = [b["title"] for b in p.get("badges") or [] if b.get("title")]
    if special is not None and price is not None and special < price:
        # "спец цена" — lower price shown next to the regular one (loyalty-card style);
        # replace the bare site badge with one that carries the number
        badges = [b for b in badges if b.lower() != "спец цена"] + [f"спец цена {special:.2f} ₽"]

    per_unit = unit_price(price, p["title"]) if price is not None else None
    url = p.get("url")
    return Product(
        store=store.key,
        product_id=str(p.get("sku") or p["id"]),
        name=p["title"].strip(),
        price=price,
        is_promo=bool(p.get("isPromo")),
        stock=_f(p.get("inStock")),
        unit_price=per_unit[0] if per_unit else None,
        unit=per_unit[1] if per_unit else None,
        badges=badges,
        url=f"{SITE}/catalog/{url}" if url else None,
    )


class FixPriceAdapter(Adapter):
    chain = "fixprice"

    def __init__(self, client=None):
        super().__init__(client)
        self._xkey: str | None = None

    def _headers(self, city: str) -> dict[str, str]:
        h = {"Origin": SITE, "Referer": f"{SITE}/", "x-language": "ru", "x-city": city}
        if self._xkey:
            h["X-Key"] = self._xkey
        return h

    async def _ensure_key(self, city: str) -> None:
        if self._xkey:
            return
        resp = await self._client.get(f"{API}/currency/current", headers=self._headers(city))
        resp.raise_for_status()
        self._xkey = resp.headers.get("x-key")
        if not self._xkey:
            raise RuntimeError("fix-price API did not issue an X-Key")

    async def _search(self, store: Store, query: str, limit: int) -> list[Product]:
        city = store.store_code if store.store_code.isdigit() else MOSCOW_CITY_ID
        for attempt in range(2):
            await self._ensure_key(city)
            resp = await self._client.post(
                f"{API}/product/search",
                params={"autocomplete": 0, "page": 1, "limit": limit, "sort": "sold"},
                json={"searchText": query},
                headers=self._headers(city),
            )
            if resp.status_code in (400, 401, 403) and attempt == 0:
                self._xkey = None  # token expired or rejected: get a fresh one
                continue
            resp.raise_for_status()
            if resp.headers.get("x-key"):
                self._xkey = resp.headers["x-key"]
            return [parse_product(p, store) for p in resp.json().get("products") or []]
        raise RuntimeError("fix-price search failed")
