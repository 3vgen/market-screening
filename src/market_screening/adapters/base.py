from __future__ import annotations

import time
from abc import ABC, abstractmethod

import httpx

from ..models import Product, Store

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


class Adapter(ABC):
    """One retail chain. Subclasses implement `_search` for a single store."""

    chain: str = ""
    cache_ttl: float = 15 * 60  # prices don't change minute to minute; be gentle with the sites

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(
            timeout=15, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        self._cache: dict[tuple, tuple[float, list[Product]]] = {}

    async def search(self, store: Store, query: str, limit: int = 10) -> list[Product]:
        key = (store.store_code, query.strip().lower(), limit)
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < self.cache_ttl:
            return hit[1]
        products = await self._search(store, query, limit)
        self._cache[key] = (time.monotonic(), products)
        return products

    @abstractmethod
    async def _search(self, store: Store, query: str, limit: int) -> list[Product]: ...

    async def aclose(self) -> None:
        await self._client.aclose()
