"""Pyaterochka (5ka.ru) — via a real (headless) browser session.

5ka.ru is behind a JS challenge, so plain HTTP doesn't work. We start one
Camoufox browser per server process, open 5ka.ru once (~20-30 s), capture the
headers the site's own JS sends to its catalog API, and then call that API with
`fetch()` from inside the page (~0.5 s per search). Approach borrowed from
https://github.com/Open-Inflation/pyaterochka_api.

Optional dependency: `pip install market-screening[browser] && python -m camoufox fetch`.
Prices are in rubles (strings in the API).
"""

from __future__ import annotations

import asyncio
import json
import urllib.parse

from ..models import Product, Store
from ..units import parse_size, unit_price
from .base import Adapter

SITE = "https://5ka.ru"
API = "https://5d.5ka.ru/api"
WARMUP_TIMEOUT_MS = 60_000

_FETCH_JS = """async ([url, headers]) => {
  const r = await fetch(url, {headers, credentials: 'include'});
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
    package = (p.get("package_quantity") or "").replace("\xa0", " ")
    per_unit: tuple[float, str] | None = None
    if price is not None and is_weighted:
        # weighed goods are priced per price_unit_label: "кг" or e.g. "100 г" (cheese, sausage)
        label = (p.get("price_unit_label") or "кг").replace("\xa0", " ")
        size = parse_size(label if any(c.isdigit() for c in label) else f"1 {label}")
        if size and size[1] == "kg":
            per_unit = (round(price / size[0], 2), "kg")
            if size[0] != 1:
                badges.append(f"цена за {label}")
    elif price is not None:
        # trust the name first: package_quantity sometimes says "320 мл" for "320г" sour cream
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


class PyaterochkaAdapter(Adapter):
    chain = "pyaterochka"

    def __init__(self, client=None):
        super().__init__(client)
        self._camoufox = None
        self._page = None
        self._headers: dict[str, str] = {}
        self._auto_store: str | None = None
        self._lock = asyncio.Lock()

    async def _ensure_session(self) -> None:
        if self._page is not None:
            return
        try:
            from camoufox.async_api import AsyncCamoufox
        except ImportError as e:  # optional dependency
            raise RuntimeError(
                "Pyaterochka needs the browser extra: "
                "pip install 'market-screening[browser]' && python -m camoufox fetch"
            ) from e

        self._camoufox = AsyncCamoufox(headless=True, i_know_what_im_doing=True)
        browser = await self._camoufox.__aenter__()
        context = await browser.new_context()
        page = await context.new_page()

        captured: asyncio.Future[dict[str, str]] = asyncio.get_running_loop().create_future()

        def on_request(request) -> None:
            if captured.done() or not request.url.startswith(API):
                return
            headers = {k: v for k, v in request.headers.items() if k.startswith("x-")}
            if "x-device-id" in headers:
                captured.set_result(headers)

        page.on("request", on_request)
        await page.goto(SITE, wait_until="domcontentloaded", timeout=WARMUP_TIMEOUT_MS)
        await page.wait_for_selector("next-route-announcer", state="attached", timeout=WARMUP_TIMEOUT_MS)
        self._headers = await asyncio.wait_for(captured, WARMUP_TIMEOUT_MS / 1000)
        self._auto_store = json.loads(
            await page.evaluate("() => localStorage.getItem('DeliveryPanelStore')") or "{}"
        ).get("selectedStore", {}).get("sapCode")
        # The SPA keeps navigating/re-checking, which kills in-flight evaluate() calls.
        # Work from a second tab on a static same-origin page: it shares the cookies,
        # and nothing on it navigates. Then close the restless SPA tab.
        worker = await context.new_page()
        await worker.goto(f"{SITE}/robots.txt", wait_until="domcontentloaded", timeout=WARMUP_TIMEOUT_MS)
        await page.close()
        self._page = worker

    async def _reset(self) -> None:
        cm, self._camoufox, self._page = self._camoufox, None, None
        if cm is not None:
            await cm.__aexit__(None, None, None)

    async def _get_json(self, url: str) -> dict:
        async with self._lock:
            for attempt in range(3):
                await self._ensure_session()
                try:
                    res = await self._page.evaluate(_FETCH_JS, [url, self._headers])
                except Exception as e:  # navigation / network hiccup inside the browser
                    if attempt == 2:
                        raise RuntimeError(f"5ka fetch failed: {e}") from e
                    await self._reset()
                    continue
                if res["status"] in (401, 403) and attempt < 2:
                    await self._reset()  # session expired or challenged again: warm up anew
                    continue
                if res["status"] != 200:
                    raise RuntimeError(f"5ka API HTTP {res['status']}: {res['body'][:200]}")
                return json.loads(res["body"])
        raise RuntimeError("unreachable")

    async def selected_store_code(self) -> str:
        """SAP code of the store 5ka.ru picked for this session (by IP geolocation)."""
        async with self._lock:
            await self._ensure_session()
        if not self._auto_store:
            raise RuntimeError("5ka.ru didn't pick a store; set store_code in config")
        return self._auto_store

    async def store_near(self, longitude: float, latitude: float) -> dict:
        """Nearest store serving a point: {sap_code, shop_address}.

        Uses the delivery panel's store-picker, the same endpoint 5ka.ru itself
        calls to place the pin for an address. It returns the nearest store that
        serves the point (``has_delivery`` marks whether it delivers). The old
        shop-locator map endpoint (``/api/stores/?bbox=``) has been removed and now
        answers 404.
        """
        data = await self._get_json(f"{API}/orders/v1/orders/stores/?lon={longitude}&lat={latitude}")
        code = data.get("sap_code")
        if not code:
            raise RuntimeError(f"no Pyaterochka store near ({latitude}, {longitude}): {data}")
        return {"sap_code": str(code), "shop_address": data.get("shop_address") or ""}

    async def store_by_address(self, address: str) -> dict:
        geo = await self._get_json(f"{SITE}/api/maps/geocode/?geocode={urllib.parse.quote(address)}")
        members = geo["response"]["GeoObjectCollection"]["featureMember"]
        if not members:
            raise RuntimeError(f"address not found: {address}")
        obj = members[0]["GeoObject"]
        lon, lat = map(float, obj["Point"]["pos"].split())
        store = await self.store_near(lon, lat)
        return {"address_found": obj.get("metaDataProperty", {}).get("GeocoderMetaData", {}).get("text"),
                "lon": lon, "lat": lat, **store}

    async def _search(self, store: Store, query: str, limit: int) -> list[Product]:
        code = store.store_code
        if code == "auto":
            code = await self.selected_store_code()
        url = (
            f"{API}/catalog/v3/stores/{code}/search?mode=store&include_restrict=true"
            f"&q={urllib.parse.quote(query)}&limit={limit}"
        )
        data = await self._get_json(url)
        return [parse_product(p, store) for p in data.get("products") or []]

    async def aclose(self) -> None:
        await self._reset()
        await super().aclose()
