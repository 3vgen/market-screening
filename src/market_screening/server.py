"""MCP server: search groceries in your stores and compute the cheapest basket."""

from __future__ import annotations

import asyncio
import os
import re
import tomllib
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from .adapters import ADAPTERS, Adapter
from .geo import geocode, haversine_km
from .models import Store
from .optimizer import optimize

mcp = MCPServer(
    "market-screening",
    instructions=(
        "Helps decide where to buy groceries. Workflow: list_stores (or stores_near with the "
        "user's address to pick the nearest stores first) -> search_products for each item on "
        "the user's list -> for each item pick the comparable product in every store (same "
        "kind, similar size/fat %, compare unit_price per kg/l, prefer in-stock) -> "
        "optimize_basket with those prices -> answer with the plan, totals and the chosen "
        "products. Never add up prices yourself; use optimize_basket. Card-only prices are "
        "marked by the 'По карте' badge."
    ),
)

_adapters: dict[str, Adapter] = {}


def _config_path() -> Path:
    return Path(os.environ.get("MARKET_SCREENING_CONFIG", "config.toml"))


def load_stores() -> list[Store]:
    path = _config_path()
    if not path.exists():
        return []
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return [
        Store(chain=s["chain"], store_code=str(s["store_code"]), name=s.get("name", ""))
        for s in data.get("stores", [])
        if s.get("chain") in ADAPTERS
    ]


def _adapter(chain: str) -> Adapter:
    if chain not in _adapters:
        _adapters[chain] = ADAPTERS[chain]()
    return _adapters[chain]


@mcp.tool()
def list_stores() -> list[dict]:
    """Stores configured by the user (chain, store code, name). Use the `key` field elsewhere."""
    stores = load_stores()
    if not stores:
        return [{"error": f"no stores configured; create {_config_path()} from config.example.toml"}]
    return [{"key": s.key, "chain": s.chain, "store_code": s.store_code, "name": s.name} for s in stores]


@mcp.tool()
async def search_products(query: str, stores: list[str] | None = None, limit: int = 10) -> dict:
    """Search a product in the configured stores.

    query: what to look for, in Russian, e.g. "молоко 2.5%", "куриное филе".
    stores: optional list of store keys from list_stores (default: all).
    Returns per store a list of products: price in rubles, old_price if on promo,
    unit_price per kg / l / pcs (compare by this), stock, badges, url.
    Search is fuzzy: results can include unrelated items (e.g. oat drink for "молоко").
    """
    targets = [s for s in load_stores() if stores is None or s.key in stores]

    async def one(store: Store):
        try:
            found = await _adapter(store.chain).search(store, query, limit)
            return store.key, [p.to_dict() for p in found]
        except Exception as e:  # one broken chain must not break the whole answer
            return store.key, {"error": f"{type(e).__name__}: {e}"}

    results = await asyncio.gather(*(one(s) for s in targets))
    return dict(results)


@mcp.tool()
async def promos(stores: list[str] | None = None, limit: int = 30) -> dict:
    """List current discounts / promotions in the configured stores, biggest discounts first.

    stores: optional list of store keys from list_stores (default: all).
    limit: max promo items per store.
    Returns per store a list of products: price, old_price (pre-discount) and
    discount_pct, plus unit_price per kg/l, stock, badges, url. A chain with no
    promo concept (or that failed) appears as an "error" entry.
    """
    targets = [s for s in load_stores() if stores is None or s.key in stores]

    async def one(store: Store):
        try:
            found = await _adapter(store.chain).promos(store, limit)
        except Exception as e:  # one broken chain must not break the whole answer
            return store.key, {"error": f"{type(e).__name__}: {e}"}
        items = []
        for p in found:
            d = p.to_dict()
            if p.old_price and p.old_price > p.price:
                d["discount_pct"] = round((p.old_price - p.price) / p.old_price * 100)
            items.append(d)
        return store.key, items

    results = await asyncio.gather(*(one(s) for s in targets))
    return dict(results)


STORE_LOOKUP_CHAINS = ("pyaterochka", "dixy", "krasnoeibeloe", "chizhik")
# Lookup returns a delivery hub (dark store), not the nearest retail shop, so its
# code must not overwrite a hand-picked one in config.toml.
NO_AUTOSAVE_CHAINS = ("pyaterochka",)


@mcp.tool()
async def find_store(chain: str, address: str) -> dict:
    """Find the store of a chain nearest to / serving an address.

    chain: "pyaterochka", "dixy", "krasnoeibeloe" (Moscow only) or "chizhik" (others have no per-store
    prices or no lookup: vkusvill, perekrestok — city-level prices; fixprice — store_code is the city
    id, Moscow = 3; magnit — take storeCode from magnit.ru DevTools).
    Returns {"store_code", "address", ...}: put store_code into config.toml.
    """
    if chain not in STORE_LOOKUP_CHAINS:
        return {"error": f"store lookup is not supported for {chain!r}; see the tool description"}
    adapter = _adapter(chain)
    try:
        if chain == "pyaterochka":
            raw = await adapter.store_by_address(address)
            return {"store_code": raw.get("sap_code"), "address": raw.get("shop_address"), **raw}
        point = await geocode(address)
        return {**point, **await adapter.store_near(point["lon"], point["lat"])}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


async def _resolve_nearest(chain: str, lon: float, lat: float) -> dict:
    """Nearest store of `chain` to a point, normalised to {store_code, address, lat, lon}."""
    raw = await _adapter(chain).store_near(lon, lat)
    if chain == "pyaterochka":
        code, address = raw.get("sap_code"), raw.get("shop_address")
    else:
        code, address = raw.get("store_code"), raw.get("address")
    if code is None:
        raise RuntimeError(f"{chain} did not return a store code")
    return {"store_code": str(code), "address": address,
            "lat": raw.get("lat"), "lon": raw.get("lon")}


def _set_store(text: str, chain: str, code: str, name: str | None) -> tuple[str, bool]:
    """Update store_code (and optionally name) of the `[[stores]]` block for `chain` in TOML text."""
    pattern = re.compile(
        r"(?ms)^(\[\[stores\]\]\s*\n\s*chain\s*=\s*\""
        + re.escape(chain) + r"\"[^\n]*\n)(.*?)(?=^\[\[stores\]\]|\Z)"
    )
    m = pattern.search(text)
    if not m:
        return text, False
    head, body = m.group(1), m.group(2)
    new_body, n = re.subn(r'(\bstore_code\s*=\s*)"[^"]*"', r'\g<1>"' + code + '"', body, count=1)
    if n == 0:
        return text, False
    if name is not None:
        esc = name.replace("\\", "\\\\").replace('"', '\\"')
        if re.search(r"\bname\s*=", new_body):
            new_body = re.sub(r'(\bname\s*=\s*)"[^"]*"', r'\g<1>"' + esc + '"', new_body, count=1)
        else:
            new_body = re.sub(r'(store_code\s*=\s*"[^"]*"\s*\n)', r'\g<1>name = "' + esc + '"\n',
                              new_body, count=1)
    return text[: m.start()] + head + new_body + text[m.end():], True


def _write_config(updates: dict[str, dict]) -> dict:
    """Write resolved store_code / name back into config.toml. Returns {updated, skipped}."""
    path = _config_path()
    updated, skipped = [], []
    if path.exists():
        text = path.read_text(encoding="utf-8")
        for chain, info in updates.items():
            text, ok = _set_store(text, chain, info["store_code"], info.get("name"))
            (updated if ok else skipped).append(chain)
        path.write_text(text, encoding="utf-8")
    else:
        skipped = list(updates)
    return {"updated": updated, "skipped": skipped}


@mcp.tool()
async def stores_near(address: str) -> dict:
    """Find the nearest store of every per-store chain for an address and save them to config.toml.

    Geocodes the address once, asks each per-store chain (pyaterochka, dixy, krasnoeibeloe,
    chizhik) for its nearest store, and writes the resulting store_code (and the store address
    as the name) into config.toml, so list_stores / search_products use those stores afterwards.
    Chains without per-store lookup (magnit, vkusvill, fixprice, perekrestok) are left unchanged.
    Pyaterochka is reported but never saved: its lookup returns a delivery hub, not a shop.
    Use this first, then search_products as usual.
    """
    try:
        point = await geocode(address)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}

    configured = {s.chain for s in load_stores()}
    targets = [c for c in STORE_LOOKUP_CHAINS if c in configured]

    async def one(chain: str):
        try:
            found = await _resolve_nearest(chain, point["lon"], point["lat"])
            found["chain"] = chain
            if found.get("lat") is not None and found.get("lon") is not None:
                found["distance_km"] = round(
                    haversine_km(point["lat"], point["lon"], found["lat"], found["lon"]), 2
                )
            return chain, found, None
        except Exception as e:  # one broken chain must not break the whole answer
            return chain, None, f"{type(e).__name__}: {e}"

    updates, stores, errors = {}, [], {}
    for chain, found, err in await asyncio.gather(*(one(c) for c in targets)):
        if err:
            errors[chain] = err
            continue
        stores.append(found)
        if chain in NO_AUTOSAVE_CHAINS:
            found["note"] = ("delivery hub, not the nearest shop; not saved - set the shop's "
                             "sap_code in config.toml by hand (from the 5ka app / receipt)")
            continue
        updates[chain] = {"store_code": found["store_code"], "name": found["address"]}

    result = {
        "address_found": point["address_found"],
        "lon": point["lon"],
        "lat": point["lat"],
        "stores": stores,
        "updated_in_config": _write_config(updates)["updated"],
    }
    if errors:
        result["errors"] = errors
    return result


@mcp.tool()
def optimize_basket(basket: list[dict], max_stores: int = 2, extra_store_cost: float = 0.0) -> dict:
    """Compute the cheapest way to buy the basket.

    basket: [{"item": "молоко", "quantity": 2, "offers": {"magnit:123456": 89.99, "dixy:123": 92.5}}]
      - offers: price in rubles per one unit of quantity, for the product you matched in each store;
        omit a store if it has no suitable product.
    max_stores: how many different stores the user is willing to visit.
    extra_store_cost: rubles the user is willing to pay to avoid each extra store visit.
    """
    return optimize(basket, max_stores=max_stores, extra_store_cost=extra_store_cost)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
