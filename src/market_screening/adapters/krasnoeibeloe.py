"""Krasnoe&Beloe (krasnoeibeloe.ru) — via a real (headless) browser session.

Catalog pages are behind a JS challenge (bp_chl cookie), so one Camoufox
session per server process. Search = the site's own page /catalog/?q=<query>:
the HTML carries the hits in the `:items` prop of <search-results>, and the
page's Vue code then POSTs their ids to /api/products/get-data/, which returns
price and stock for the shop in the `mainShop` cookie. That endpoint answers
`null` to ids the page didn't render itself, so we navigate the page and
intercept its own get-data response instead of calling the API directly.

store_code in config = Krasnoe&Beloe shop id (see find_store / store_near).
Prices are in rubles. Products with price 0 have no price published on the site
(the card only shows a "ЦЕНА" button) and are skipped.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import json
import math
import re
import urllib.parse
from html.parser import HTMLParser

from ..models import Product, Store
from ..units import parse_size, unit_price
from .base import Adapter

SITE = "https://krasnoeibeloe.ru"
PROMO_PAGE = f"{SITE}/catalog/specpredlozheniya/"  # "Спецпредложения" (multi-buy offers)
MOSCOW_CITY_ID = 878
PRODUCT_IBLOCK = "9"  # other iblocks in search hits are news / press articles
WARMUP_TIMEOUT_MS = 60_000
SEARCH_TIMEOUT_MS = 30_000

_ITEMS_RX = re.compile(r'<search-results[^>]*?\s:items="([^"]*)"', re.S)
_TAG = re.compile(r"<[^>]+>")

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


def parse_search_items(page_html: str) -> list[dict]:
    """Product hits embedded in the search page (news/articles dropped)."""
    m = _ITEMS_RX.search(page_html)
    if not m:
        return []
    items = json.loads(html_lib.unescape(m.group(1)))
    return [i for i in items if str(i.get("iblockId")) == PRODUCT_IBLOCK]


def parse_product(item: dict, data: dict | None, store: Store) -> Product | None:
    data = data or {}
    price = _f(data.get("price"))
    if not price:  # 0 / missing = price not published on the site
        return None
    name = html_lib.unescape(_TAG.sub("", item.get("name") or "")).strip()

    badges = []
    regional = _f(data.get("priceByRegion"))
    if regional and regional < price:
        # shown nowhere on the card; semantics not confirmed — keep as a hint only
        badges.append(f"priceByRegion {regional:.2f} ₽")
    if item.get("alcohol"):
        badges.append(f"{item['alcohol']}% алк.")

    per_unit = None
    volume = _f(item.get("volume"))
    if volume:
        per_unit = (round(price / volume, 2), "l")
    else:
        size = parse_size(item.get("mera") or "")
        per_unit = (round(price / size[0], 2), size[1]) if size else unit_price(price, name)

    stock = _f(data.get("shopAmount"))
    url = item.get("url")
    return Product(
        store=store.key,
        product_id=str(item["id"]),
        name=name,
        price=price,
        stock=stock,
        unit_price=per_unit[0] if per_unit else None,
        unit=per_unit[1] if per_unit else None,
        badges=badges,
        url=f"{SITE}{url}" if url else None,
    )


def parse_search(page_html: str, get_data: dict | None, store: Store) -> list[Product]:
    get_data = get_data or {}
    products = []
    for item in parse_search_items(page_html):
        p = parse_product(item, get_data.get(str(item.get("id"))), store)
        if p:
            products.append(p)
    return products


def _promo_num(value: str | None) -> float | None:
    """Number from a discount-price attr, which nests a <span> and an entity."""
    if not value:
        return None
    text = html_lib.unescape(re.sub(r"<[^>]+>", "", value)).replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", text)
    return float(m.group()) if m else None


class _PromoProductParser(HTMLParser):
    """Collect <product ...> props from the special-offers page (Vue SSR)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict] = []
        self._cur: dict | None = None
        self._in_p = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "product":
            self._cur = {
                "id": a.get(":product-id") or a.get("product-id"),
                "name": a.get("name") or a.get(":name"),
                "discount_price": a.get("discount-price"),
                "percent": a.get(":discount-percent") or a.get("discount-percent"),
                "min_amount": a.get(":discount-min-amount") or a.get("discount-min-amount"),
                "is_discount": a.get(":is-discount") or a.get("is-discount"),
                "is_yellow": a.get(":is-yellow") or a.get("is-yellow"),
            }
            self.items.append(self._cur)
            self._in_p = False
        elif self._cur is not None:
            if tag == "a" and self._cur.get("url") is None:
                self._cur["url"] = a.get("href")
            elif tag == "p" and not self._in_p:
                self._in_p = True
                self._cur["subtitle"] = ""

    def handle_data(self, data):
        if self._cur is not None and self._in_p:
            self._cur["subtitle"] = (self._cur.get("subtitle", "") + " " + data).strip()

    def handle_endtag(self, tag):
        if tag == "p":
            self._in_p = False


def parse_promo_page(page_html: str, get_data: dict | None, store: Store) -> list[Product]:
    get_data = get_data or {}
    parser = _PromoProductParser()
    parser.feed(page_html)
    products = []
    for p in parser.items:
        pid = p.get("id")
        name = html_lib.unescape(re.sub(r"<[^>]+>", "", p.get("name") or "")).strip()
        if not pid or not name:
            continue
        regular = _f((get_data.get(str(pid)) or {}).get("price"))
        if not regular:  # price not published / shop doesn't carry it
            continue
        discount = _promo_num(p.get("discount_price"))
        percent_num = _promo_num(p.get("percent"))
        min_amount = p.get("min_amount")
        is_discount = p.get("is_discount") == "1"
        price, old_price, is_promo = regular, None, False
        badges: list[str] = []
        if is_discount:
            if discount and discount < regular:
                price, old_price, is_promo = discount, regular, True
            elif percent_num and 0 < percent_num < 100:
                # no discounted price in the markup: compute it from the shown % off
                price = round(regular * (1 - percent_num / 100), 2)
                old_price, is_promo = regular, True
            if percent_num and min_amount:
                badges.append(f"-{percent_num:g}% от {min_amount} шт.")
            elif old_price is not None:
                badges.append("по акции")
        elif p.get("is_yellow") == "1":
            badges.append("спеццена")

        per_unit = unit_price(price, f"{name} {p.get('subtitle') or ''}")
        url = p.get("url")
        products.append(Product(
            store=store.key,
            product_id=str(pid),
            name=name,
            price=price,
            old_price=old_price,
            is_promo=is_promo,
            stock=_f((get_data.get(str(pid)) or {}).get("shopAmount")),
            unit_price=per_unit[0] if per_unit else None,
            unit=per_unit[1] if per_unit else None,
            badges=badges,
            url=f"{SITE}{url}" if url else None,
        ))
    return products


class KrasnoeIBeloeAdapter(Adapter):
    chain = "krasnoeibeloe"

    def __init__(self, client=None):
        super().__init__(client)
        self._camoufox = None
        self._context = None
        self._page = None
        self._shops: dict[int, list[dict]] = {}  # city id -> shops
        self._current_shop: str | None = None
        self._lock = asyncio.Lock()

    async def _ensure_session(self) -> None:
        if self._page is not None:
            return
        try:
            from camoufox.async_api import AsyncCamoufox
        except ImportError as e:  # optional dependency
            raise RuntimeError(
                "Krasnoe&Beloe needs the browser extra: "
                "pip install 'market-screening[browser]' && python -m camoufox fetch"
            ) from e

        self._camoufox = AsyncCamoufox(headless=True, i_know_what_im_doing=True)
        browser = await self._camoufox.__aenter__()
        self._context = await browser.new_context()
        await self._context.add_cookies([_cookie("ageApproved", "1")])
        page = await self._context.new_page()
        # the home page isn't challenged; a catalog page is, and that sets bp_chl
        await page.goto(f"{SITE}/catalog/?q=%D0%B2%D0%B8%D0%BD%D0%BE", wait_until="load",
                        timeout=WARMUP_TIMEOUT_MS)
        self._page = page
        self._current_shop = None

    async def _reset(self) -> None:
        cm, self._camoufox, self._page, self._context = self._camoufox, None, None, None
        self._current_shop = None
        if cm is not None:
            await cm.__aexit__(None, None, None)

    async def _get_json(self, url: str):
        """Caller must hold the lock."""
        await self._ensure_session()
        res = await self._page.evaluate(_FETCH_JS, url)
        if res["status"] != 200:
            raise RuntimeError(f"krasnoeibeloe HTTP {res['status']} for {url}")
        return json.loads(res["body"])

    async def _city_shops(self, city_id: int) -> list[dict]:
        if city_id not in self._shops:
            self._shops[city_id] = await self._get_json(f"{SITE}/api/cities/{city_id}/shops/")
        return self._shops[city_id]

    async def _select_shop(self, shop_id: str) -> None:
        """Caller must hold the lock."""
        if self._current_shop == shop_id:
            return
        shop = next((s for s in await self._city_shops(MOSCOW_CITY_ID) if str(s["id"]) == shop_id), None)
        if shop is None:
            raise RuntimeError(f"unknown Krasnoe&Beloe shop id {shop_id!r} (Moscow shops only)")
        main_shop = {"id": shop["id"], "shopNum": shop.get("shopNum") or shop.get("num"),
                     "address": shop.get("address"), "cityId": shop.get("cityId"),
                     "noAlcohol": shop.get("noAlcohol")}
        await self._context.add_cookies([
            _cookie("mainShop", urllib.parse.quote(json.dumps(main_shop, ensure_ascii=False))),
            _cookie("userCityId", str(shop.get("cityId") or MOSCOW_CITY_ID)),
        ])
        self._current_shop = shop_id

    async def store_near(self, longitude: float, latitude: float) -> dict:
        """Nearest Moscow shop to a point: {"store_code", "address", "lat", "lon", ...}."""
        async with self._lock:
            shops = await self._city_shops(MOSCOW_CITY_ID)
        k = math.cos(math.radians(latitude))
        best = min(shops, key=lambda s: math.hypot(float(s["lat"]) - latitude,
                                                   (float(s["lng"]) - longitude) * k))
        return {"store_code": str(best["id"]), "address": f"Москва, {best.get('address')}",
                "lat": float(best["lat"]), "lon": float(best["lng"]), "hours": best.get("time"),
                "no_alcohol": best.get("noAlcohol")}

    async def _search(self, store: Store, query: str, limit: int) -> list[Product]:
        if not store.store_code.isdigit():
            raise RuntimeError("set store_code to a Krasnoe&Beloe shop id (use find_store)")
        url = f"{SITE}/catalog/?q={urllib.parse.quote(query)}"
        async with self._lock:
            for attempt in range(2):
                await self._ensure_session()
                await self._select_shop(store.store_code)
                page_html = ""
                try:
                    async with self._page.expect_response(
                        lambda r: "/api/products/get-data/" in r.url, timeout=SEARCH_TIMEOUT_MS
                    ) as info:
                        doc = await self._page.goto(url, wait_until="domcontentloaded",
                                                    timeout=WARMUP_TIMEOUT_MS)
                        page_html = await doc.text() if doc else ""
                    get_data = json.loads(await (await info.value).text() or "null")
                except Exception as e:
                    if _ITEMS_RX.search(page_html) and not parse_search_items(page_html):
                        return []  # real search page, just no products -> no get-data call
                    if attempt == 0:
                        await self._reset()  # challenged again / navigation broke: warm up anew
                        continue
                    raise RuntimeError(f"krasnoeibeloe search failed: {e}") from e
                if _ITEMS_RX.search(page_html) or attempt == 1:
                    break
                await self._reset()
        return parse_search(page_html, get_data, store)[:limit]

    async def _promos(self, store: Store, limit: int) -> list[Product]:
        if not store.store_code.isdigit():
            raise RuntimeError("set store_code to a Krasnoe&Beloe shop id (use find_store)")
        async with self._lock:
            for attempt in range(2):
                await self._ensure_session()
                await self._select_shop(store.store_code)
                page_html = ""
                try:
                    async with self._page.expect_response(
                        lambda r: "/api/products/get-data/" in r.url, timeout=SEARCH_TIMEOUT_MS
                    ) as info:
                        doc = await self._page.goto(PROMO_PAGE, wait_until="domcontentloaded",
                                                    timeout=WARMUP_TIMEOUT_MS)
                        page_html = await doc.text() if doc else ""
                    get_data = json.loads(await (await info.value).text() or "null")
                except Exception as e:
                    if attempt == 0:
                        await self._reset()
                        continue
                    raise RuntimeError(f"krasnoeibeloe promos failed: {e}") from e
                if "<product" in page_html or attempt == 1:
                    break
                await self._reset()
        return parse_promo_page(page_html, get_data, store)[:limit]

    async def aclose(self) -> None:
        await self._reset()
        await super().aclose()


def _cookie(name: str, value: str) -> dict:
    return {"name": name, "value": value, "domain": "krasnoeibeloe.ru", "path": "/"}
