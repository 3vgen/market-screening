"""Chizhik (chizhik.club) — X5 hard discounter, via a real (headless) browser session.

chizhik.club is behind a servicepipe.tech JS challenge, so plain HTTP doesn't work.
We open the site once in Camoufox, wait for the challenge to set its cookies, then
call the site's own catalog API (app.chizhik.club) with fetch() from a static
same-origin tab (~0.5 s per search). The product JSON is the shared X5 catalog
format, identical to Pyaterochka's.

- Search:    /delivery/api/catalog/v3/stores/{sap_id}/search?mode=delivery&q=...&limit=...
- Stores:    /api/v1/shops/?lat=...&lon=...  (nearest first)
  store_code in config = the shop's `sap_id` (4 letters, e.g. "HBBN"), or "auto"
  for the store chizhik.club picks for this session (IP geolocation).

Optional dependency: `pip install 'market-screening[browser]' && python -m camoufox fetch`.
Prices are in rubles (strings in the API).
"""

from __future__ import annotations

import asyncio
import json
import urllib.parse

from ..models import Product, Store
from ..units import parse_size, unit_price
from .base import Adapter

SITE = "https://chizhik.club"
APP = "https://app.chizhik.club"
API = f"{APP}/delivery/api"
WARMUP_TIMEOUT_MS = 60_000

_FETCH_JS = """async (url) => {
  const r = await fetch(url, {credentials: 'include'});
  return {status: r.status, body: await r.text()};
}"""


def _f(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ".").replace("\xa0", ""))
    except ValueError:
        return None


def parse_product(p: dict, store: Store) -> Product:
    prices = p.get("prices") or {}
    regular = _f(prices.get("regular"))
    discount = _f(prices.get("discount"))
    price = discount if discount is not None else regular
    old_price = regular if discount is not None and regular and discount < regular else None

    labels = [lb["label"] for lb in p.get("labels") or [] if lb.get("label")]
    badges = list(labels)
    conditional = _f(prices.get("cpd_promo_price"))  # e.g. price when buying 2+ ("% от 2 шт")
    if conditional is not None and price and conditional < price:
        condition = f" ({', '.join(labels)})" if labels else ""
        badges.append(f"по акции {conditional:.2f} ₽{condition}")

    is_weighted = (p.get("uom") or "").lower() == "кг"
    # Chizhik puts the sizing hint in property_clarification ("Цена за 1 кг", "200 мл")
    package = (p.get("package_quantity") or p.get("property_clarification") or "").replace("\xa0", " ")
    per_unit: tuple[float, str] | None = None
    if price is not None and is_weighted:
        label = (p.get("price_unit_label") or package or "кг").replace("\xa0", " ")
        size = parse_size(label if any(c.isdigit() for c in label) else f"1 {label}")
        if size and size[1] == "kg":
            per_unit = (round(price / size[0], 2), "kg")
            if size[0] != 1:
                badges.append(f"цена за {label}")
    elif price is not None:
        # trust the name first: property_clarification can disagree (205мл vs "200 мл")
        per_unit = unit_price(price, p["name"]) or unit_price(price, package)

    stock = _f(p.get("stock_limit"))
    if p.get("is_available") is False:
        stock = 0.0

    return Product(
        store=store.key,
        product_id=str(p["plu"]),
        name=p["name"].strip(),
        price=price,
        old_price=old_price,
        is_promo=old_price is not None,
        stock=stock,
        unit_price=per_unit[0] if per_unit else None,
        unit=per_unit[1] if per_unit else None,
        is_weighted=is_weighted,
        badges=badges,
    )


class ChizhikAdapter(Adapter):
    chain = "chizhik"

    def __init__(self, client=None):
        super().__init__(client)
        self._camoufox = None
        self._context = None
        self._page = None
        self._auto_store: str | None = None
        self._lock = asyncio.Lock()

    async def _ensure_session(self) -> None:
        if self._page is not None:
            return
        try:
            from camoufox.async_api import AsyncCamoufox
        except ImportError as e:  # optional dependency
            raise RuntimeError(
                "Chizhik needs the browser extra: "
                "pip install 'market-screening[browser]' && python -m camoufox fetch"
            ) from e

        self._camoufox = AsyncCamoufox(headless=True, i_know_what_im_doing=True)
        browser = await self._camoufox.__aenter__()
        self._context = await browser.new_context()
        page = await self._context.new_page()
        await page.goto(SITE, wait_until="load", timeout=WARMUP_TIMEOUT_MS)
        # The servicepipe challenge sets its cookies asynchronously after load.
        for _ in range(40):
            await asyncio.sleep(0.5)
            cookies = await self._context.cookies()
            if any(c["name"] == "tc4_store_id" for c in cookies):
                break
        self._auto_store = next(
            (c["value"] for c in cookies if c["name"] == "tc4_store_id"), None
        )
        # Work from a static same-origin tab: shares cookies, never navigates by itself.
        worker = await self._context.new_page()
        await worker.goto(f"{SITE}/robots.txt", wait_until="domcontentloaded", timeout=WARMUP_TIMEOUT_MS)
        await page.close()
        self._page = worker

    async def _reset(self) -> None:
        cm, self._camoufox, self._page, self._context = self._camoufox, None, None, None
        self._auto_store = None
        if cm is not None:
            await cm.__aexit__(None, None, None)

    async def _get_json(self, url: str) -> dict:
        async with self._lock:
            for attempt in range(3):
                await self._ensure_session()
                try:
                    res = await self._page.evaluate(_FETCH_JS, url)
                except Exception as e:  # navigation / network hiccup inside the browser
                    if attempt == 2:
                        raise RuntimeError(f"chizhik fetch failed: {e}") from e
                    await self._reset()
                    continue
                if res["status"] in (401, 403) and attempt < 2:
                    await self._reset()  # challenged again: warm up anew
                    continue
                if res["status"] != 200:
                    raise RuntimeError(f"chizhik API HTTP {res['status']}: {res['body'][:200]}")
                return json.loads(res["body"])
        raise RuntimeError("unreachable")

    async def selected_store_code(self) -> str:
        """SAP code of the store chizhik.club picked for this session (by IP geolocation)."""
        async with self._lock:
            await self._ensure_session()
        if self._auto_store:
            return self._auto_store
        # Fallback when the challenge didn't leave a tc4_store_id cookie: use the
        # nearest shop from the site's own IP-geolocated list.
        shops = await self._get_json(f"{APP}/api/v1/shops/")
        if not shops:
            raise RuntimeError("chizhik.club didn't pick a store; set store_code in config")
        self._auto_store = str(shops[0]["sap_id"])
        return self._auto_store

    async def store_near(self, longitude: float, latitude: float) -> dict:
        """Nearest Chizhik shop to a point: {"store_code", "address", "lat", "lon", ...}."""
        shops = await self._get_json(f"{APP}/api/v1/shops/?lat={latitude}&lon={longitude}")
        if not shops:
            raise RuntimeError("no Chizhik shops found near the point")
        best = shops[0]
        return {
            "store_code": str(best.get("sap_id")),
            "address": best.get("name"),
            "lat": best.get("lat"),
            "lon": best.get("lon"),
            "hours": best.get("working_hours"),
        }

    async def _search(self, store: Store, query: str, limit: int) -> list[Product]:
        code = store.store_code
        if code == "auto":
            code = await self.selected_store_code()
        url = (
            f"{API}/catalog/v3/stores/{code}/search?mode=delivery&include_restrict=true"
            f"&q={urllib.parse.quote(query)}&limit={limit}"
        )
        data = await self._get_json(url)
        return [parse_product(p, store) for p in data.get("products") or []]

    async def aclose(self) -> None:
        await self._reset()
        await super().aclose()
