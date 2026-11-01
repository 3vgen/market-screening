"""Dixy (dixy.ru) — via a real (headless) browser session, like the Pyaterochka adapter.

The product listing JSON (/ajax/listing-json.php) is behind a WAF that rejects plain
HTTP clients. We open dixy.ru once in Camoufox (~7-12 s), then call the site's own
endpoints with fetch() from a static same-origin tab (~0.7 s per search):

- /ajax/listing-json.php?...&getFullData&gl_filter=&useTracking=true&collect_stat
  (the exact parameter set the site uses; without it the WAF answers 403)
- /ajax/ajax.php action=getNearestStore / saveStore — the store lives in the PHP session
- /ajax/stores-json.php — all stores as GeoJSON (id, [lat, lon], address)

Optional dependency: `pip install market-screening[browser] && python -m camoufox fetch`
(same browser extra). Prices are in rubles.
"""

from __future__ import annotations

import asyncio
import json
import re
import urllib.parse

from ..models import Product, Store
from ..units import unit_price
from .base import Adapter

SITE = "https://dixy.ru"
WARMUP_TIMEOUT_MS = 60_000

_FETCH_JS = """async ([url, method, form]) => {
  const opts = {method, credentials: 'include'};
  if (form) {
    const fd = new FormData();
    for (const [k, v] of Object.entries(form)) fd.append(k, v);
    opts.body = fd;
  }
  const r = await fetch(url, opts);
  return {status: r.status, body: await r.text()};
}"""


def _f(value) -> float | None:
    if value in (None, ""):
        return None
    s = re.sub(r"[\s   ]", "", str(value)).replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def listing_url(query: str, per_page: int = 30) -> str:
    return (
        f"/ajax/listing-json.php?block=product-list&sid=0&perPage={per_page}&page=1"
        f"&searchQuery={urllib.parse.quote(query)}&getFullData&gl_filter=&useTracking=true&collect_stat"
    )


def parse_card(card: dict, store: Store) -> Product | None:
    price = _f(card.get("priceSimple"))
    title = (card.get("title") or "").strip()
    if price is None or not title or card.get("hidePrice"):
        return None

    old = _f(card.get("oldPriceSimple"))
    is_promo = bool(card.get("crossPrice")) and old is not None and old > price

    is_weighted = (card.get("symbol") or "").lower() == "кг"
    # card["weight"] is the gross shipping weight (e.g. "1000 гр" for 950 ml milk) - don't use it
    if is_weighted:
        per_unit: tuple[float, str] | None = (price, "kg")
    else:
        per_unit = unit_price(price, title)

    url = card.get("url")
    return Product(
        store=store.key,
        product_id=str(card.get("id")),
        name=title,
        price=price,
        old_price=old if is_promo else None,
        is_promo=is_promo,
        stock=_f(card.get("amount")),
        unit_price=per_unit[0] if per_unit else None,
        unit=per_unit[1] if per_unit else None,
        is_weighted=is_weighted,
        url=f"{SITE}{url}" if url else None,
    )


def parse_listing(data: list | dict, store: Store) -> list[Product]:
    blocks = data if isinstance(data, list) else [data]
    products = []
    for block in blocks:
        for card in block.get("cards") or []:
            p = parse_card(card, store)
            if p:
                products.append(p)
    return products


def listing_store_address(data: list | dict) -> str | None:
    blocks = data if isinstance(data, list) else [data]
    for block in blocks:
        for card in block.get("cards") or []:
            addr = (card.get("store") or {}).get("storeAddress")
            if addr:
                return addr
    return None


class DixyAdapter(Adapter):
    chain = "dixy"

    def __init__(self, client=None):
        super().__init__(client)
        self._camoufox = None
        self._page = None
        self._current_store: str | None = None  # store id saved in the PHP session
        self._stores: dict[str, dict] | None = None  # id -> {"lat", "lon", "address"}
        self._lock = asyncio.Lock()

    async def _ensure_session(self) -> None:
        if self._page is not None:
            return
        try:
            from camoufox.async_api import AsyncCamoufox
        except ImportError as e:  # optional dependency
            raise RuntimeError(
                "Dixy needs the browser extra: "
                "pip install 'market-screening[browser]' && python -m camoufox fetch"
            ) from e

        self._camoufox = AsyncCamoufox(headless=True, i_know_what_im_doing=True)
        browser = await self._camoufox.__aenter__()
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(SITE, wait_until="load", timeout=WARMUP_TIMEOUT_MS)
        # Work from a static same-origin tab: shares cookies, never navigates by itself.
        worker = await context.new_page()
        await worker.goto(f"{SITE}/robots.txt", wait_until="domcontentloaded", timeout=WARMUP_TIMEOUT_MS)
        await page.close()
        self._page = worker
        self._current_store = None

    async def _reset(self) -> None:
        cm, self._camoufox, self._page = self._camoufox, None, None
        self._current_store = None
        if cm is not None:
            await cm.__aexit__(None, None, None)

    async def _call(self, url: str, method: str = "GET", form: dict | None = None) -> str:
        """fetch() from the page; caller must hold the lock."""
        for attempt in range(3):
            await self._ensure_session()
            try:
                res = await self._page.evaluate(_FETCH_JS, [url, method, form])
            except Exception as e:  # navigation / network hiccup inside the browser
                if attempt == 2:
                    raise RuntimeError(f"dixy fetch failed: {e}") from e
                await self._reset()
                continue
            if res["status"] == 403 and attempt < 2:
                await self._reset()  # WAF challenged the session: warm up anew
                continue
            if res["status"] != 200:
                raise RuntimeError(f"dixy HTTP {res['status']}: {res['body'][:200]}")
            return res["body"]
        raise RuntimeError("unreachable")

    async def _load_stores(self) -> dict[str, dict]:
        if self._stores is None:
            feats = json.loads(await self._call("/ajax/stores-json.php"))
            self._stores = {}
            for f in feats:
                lat, lon = (float(c) for c in f["geometry"]["coordinates"])
                self._stores[str(f["id"])] = {
                    "lat": lat,
                    "lon": lon,
                    "address": (f.get("properties") or {}).get("balloonContentBody", ""),
                }
        return self._stores

    async def _select_store(self, store_id: str) -> None:
        """Caller must hold the lock."""
        if self._current_store == store_id:
            return
        info = (await self._load_stores()).get(store_id)
        if info is None:
            raise RuntimeError(f"unknown Dixy store id {store_id!r}")
        await self._call(
            "/ajax/ajax.php",
            "POST",
            {
                "action": "saveStore",
                "isDelivery": "false",  # pickup = shelf prices of this store
                "store_id": store_id,
                "coords": f"{info['lon']},{info['lat']}",
                "address": info["address"],
            },
        )
        self._current_store = store_id

    async def store_near(self, longitude: float, latitude: float) -> dict:
        """Nearest Dixy store to a point: {"store_code", "address", "lat", "lon"}."""
        async with self._lock:
            body = await self._call(
                "/ajax/ajax.php",
                "POST",
                {"action": "getNearestStore", "lat": str(latitude), "lon": str(longitude), "isDelivery": "false"},
            )
            found = json.loads(body.strip())
            store_id = str(found["ID"])
            info = (await self._load_stores()).get(store_id, {})
        return {"store_code": store_id, "address": found.get("ADDRESS") or info.get("address"),
                "lat": info.get("lat"), "lon": info.get("lon")}

    async def _search(self, store: Store, query: str, limit: int) -> list[Product]:
        async with self._lock:
            for _ in range(2):
                await self._ensure_session()
                await self._select_store(store.store_code)
                # same perPage as the site itself, to look like it; we slice afterwards
                body = await self._call(listing_url(query))
                if self._current_store == store.store_code:
                    break  # session survived the call, so the listing is for our store
        return parse_listing(json.loads(body), store)[:limit]

    async def aclose(self) -> None:
        await self._reset()
        await super().aclose()
