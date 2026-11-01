"""MCP server: search groceries in your stores and compute the cheapest basket."""

from __future__ import annotations

import asyncio
import os
import tomllib
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from .adapters import ADAPTERS, Adapter
from .models import Store
from .optimizer import optimize

mcp = MCPServer(
    "market-screening",
    instructions=(
        "Helps decide where to buy groceries. Workflow: list_stores -> search_products for "
        "each item on the user's list -> for each item pick the comparable product in every "
        "store (same kind, similar size/fat %, compare unit_price per kg/l, prefer in-stock) -> "
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
