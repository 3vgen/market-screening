"""Perekrestok (perekrestok.ru) — via a real (headless) browser session.

Same idea as the Pyaterochka adapter: perekrestok.ru is behind a JS challenge,
so we open the site once in Camoufox (~7 s), capture the anonymous-session
headers the SPA sends to its API (`auth: Bearer …`, `x-device-id`), and call
`POST /catalog/product/feed` with `fetch()` from a static same-origin tab
(~0.1–0.2 s per search).

Prices are in **kopecks**. Without a delivery address the site shows city-level
(Moscow) prices; `store_code` in config is just a label.

Optional dependency: `pip install market-screening[browser] && python -m camoufox fetch`
(same browser as Pyaterochka).
"""

from __future__ import annotations

import asyncio
import json
import re

from ..models import Product, Store
from ..units import unit_price
from .base import Adapter

SITE = "https://www.perekrestok.ru"
API = f"{SITE}/api/customer/1.4.1.0"
WARMUP_TIMEOUT_MS = 60_000

_FETCH_JS = """async ([url, method, headers, body]) => {
  const r = await fetch(url, {method, headers, body, credentials: 'include'});
  return {status: r.status, body: await r.text()};
}"""

UNIT_PIECE, UNIT_KG = 1, 2
_OUT_OF_STOCK = {"none", "empty", "outofstock", "out_of_stock", "absent"}


def _rub(kopecks) -> float | None:
    return None if kopecks is None else round(kopecks / 100, 2)


def parse_product(item: dict, store: Store) -> Product:
    md = item.get("masterData") or {}
    tag = item.get("priceTag") or {}
    price = _rub(tag.get("price"))
    gross = _rub(tag.get("grossPrice"))
    old_price = gross if gross and price and gross > price else None

    badges = [lb["text"] for lb in tag.get("labels") or [] if lb.get("text")]
    conditional = _rub(tag.get("unitPriceWithConditionalDiscount"))
    if conditional is not None and price and conditional < price:
        cond = tag.get("discountCondition")
        badges.append(f"по акции {conditional:.2f} ₽" + (f" ({cond})" if isinstance(cond, str) else ""))

    is_weighted = md.get("unit") == UNIT_KG
    per_unit: tuple[float, str] | None = None
    if price is not None:
        if is_weighted:
            per_unit = (price, "kg")  # weighed goods are priced per kg
        else:
            per_unit = unit_price(price, item["title"])
            if per_unit is None and md.get("volume"):
                per_unit = (round(price / (md["volume"] / 1000), 2), "l")
            elif per_unit is None and md.get("weight"):
                per_unit = (round(price / (md["weight"] / 1000), 2), "kg")

    balance = (item.get("balanceState") or "").lower()
    stock = 0.0 if balance in _OUT_OF_STOCK else None
    if balance and balance not in _OUT_OF_STOCK and balance != "many":
        badges.append(f"остаток: {balance}")

    category = (item.get("catalogPrimaryCategory") or {}).get("id")
    url = (
        f"{SITE}/cat/{category}/p/{md['slug']}-{md['plu']}"
        if category and md.get("slug") and md.get("plu")
        else None
    )

    return Product(
        store=store.key,
        product_id=str(md.get("plu") or item["id"]),
        name=" ".join(item["title"].replace(" ,", ",").split()),
        price=price,
        old_price=old_price,
        is_promo=old_price is not None,
        stock=stock,
        unit_price=per_unit[0] if per_unit else None,
        unit=per_unit[1] if per_unit else None,
        is_weighted=is_weighted,
        badges=badges,
        url=url,
    )


class PerekrestokAdapter(Adapter):
    chain = "perekrestok"

    def __init__(self, client=None):
        super().__init__(client)
        self._camoufox = None
        self._page = None
        self._headers: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def _ensure_session(self) -> None:
        if self._page is not None:
            return
        try:
            from camoufox.async_api import AsyncCamoufox
        except ImportError as e:  # optional dependency
            raise RuntimeError(
                "Perekrestok needs the browser extra: "
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
            headers = {k: v for k, v in request.headers.items() if k in ("auth", "x-device-id")}
            if "auth" in headers:
                captured.set_result(headers)

        page.on("request", on_request)
        await page.goto(f"{SITE}/", wait_until="domcontentloaded", timeout=WARMUP_TIMEOUT_MS)
        self._headers = await asyncio.wait_for(captured, WARMUP_TIMEOUT_MS / 1000)
        # Work from a static same-origin tab: shares cookies, never navigates by itself.
        worker = await context.new_page()
        await worker.goto(f"{SITE}/robots.txt", wait_until="domcontentloaded", timeout=WARMUP_TIMEOUT_MS)
        await page.close()
        self._page = worker

    async def _reset(self) -> None:
        cm, self._camoufox, self._page = self._camoufox, None, None
        if cm is not None:
            await cm.__aexit__(None, None, None)

    async def _call(self, path: str, body: dict | None = None) -> dict:
        method = "POST" if body is not None else "GET"
        async with self._lock:
            for attempt in range(3):
                await self._ensure_session()
                headers = {**self._headers, "content-type": "application/json"}
                try:
                    res = await self._page.evaluate(
                        _FETCH_JS, [API + path, method, headers, json.dumps(body) if body else None]
                    )
                except Exception as e:  # navigation / network hiccup inside the browser
                    if attempt == 2:
                        raise RuntimeError(f"perekrestok fetch failed: {e}") from e
                    await self._reset()
                    continue
                if res["status"] in (401, 403) and attempt < 2:
                    await self._reset()  # anonymous token expired or challenged again
                    continue
                if res["status"] != 200:
                    raise RuntimeError(f"perekrestok API HTTP {res['status']}: {res['body'][:200]}")
                return json.loads(res["body"])
        raise RuntimeError("unreachable")

    async def _search(self, store: Store, query: str, limit: int) -> list[Product]:
        # strict search: "3,2%" finds nothing, titles use "3.2%"
        query = re.sub(r"(\d),(\d)", r"\1.\2", query)
        body = {"page": 1, "perPage": limit, "filter": {"textQuery": query}, "withBestProductReviews": False}
        data = await self._call("/catalog/product/feed", body)
        items = (data.get("content") or {}).get("items") or []
        return [parse_product(it, store) for it in items]

    async def aclose(self) -> None:
        await self._reset()
        await super().aclose()
