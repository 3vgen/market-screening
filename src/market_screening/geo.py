"""Address -> coordinates via OpenStreetMap Nominatim (free, no key; max ~1 req/s)."""

from __future__ import annotations

import httpx

NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "market-screening/0.1 (https://github.com/3vgen/market-screening)"


async def geocode(address: str, client: httpx.AsyncClient | None = None) -> dict:
    """Return {"lon", "lat", "address_found"} for the best match in Russia."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        resp = await client.get(
            NOMINATIM,
            params={"q": address, "format": "jsonv2", "limit": 1, "countrycodes": "ru",
                    "accept-language": "ru"},
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        hits = resp.json()
    finally:
        if own:
            await client.aclose()
    if not hits:
        raise LookupError(f"address not found: {address}")
    hit = hits[0]
    return {"lon": float(hit["lon"]), "lat": float(hit["lat"]), "address_found": hit.get("display_name")}
