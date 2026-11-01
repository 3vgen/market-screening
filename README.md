# market-screening

MCP server that helps an LLM answer **"where should I buy my grocery list?"** across
Russian retail chains. You give the assistant a shopping list; it searches the products
in the stores you shop at, matches comparable items (by price per kg / l), and computes
the cheapest plan: everything in one store, or split across 2–3 stores.

> Status: early prototype. Supported chains: **Magnit**. Dixy and VkusVill are being investigated.

## How it works

| Tool | What it does |
|---|---|
| `list_stores` | Stores from your `config.toml` |
| `search_products(query, stores?, limit?)` | Products with price, promo/old price, price per kg/l, stock, card-only badges |
| `optimize_basket(basket, max_stores, extra_store_cost)` | Exact totals: best single store vs best split, saving |

The LLM does the fuzzy part (which "молоко" in each store is comparable); the server
does the arithmetic, so totals are not hallucinated.

Data comes from the same public JSON endpoints the chains' websites use, without login.
Results are cached for 15 minutes to keep the load on the sites minimal.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp config.example.toml config.toml   # put your store codes there
```

Finding your Magnit store code: open magnit.ru, pick your store, then
DevTools → Network → `goods/search` → Payload → `storeCode`.

### Claude Code

```bash
claude mcp add market-screening -e MARKET_SCREENING_CONFIG=$PWD/config.toml -- $PWD/.venv/bin/market-screening
```

### Claude Desktop / other MCP clients

```json
{
  "mcpServers": {
    "market-screening": {
      "command": "/path/to/market-screening/.venv/bin/market-screening",
      "env": { "MARKET_SCREENING_CONFIG": "/path/to/market-screening/config.toml" }
    }
  }
}
```

## Network note

Chains often block foreign IPs. If you use a VPN, route the chains' domains directly
(split tunneling), e.g. for v2rayA RoutingA — place these **above** any `geosite:` rules:

```
domain(domain:magnit.ru, domain:dixy.ru, domain:vkusvill.ru)->direct
```

## Adding a chain

Create `src/market_screening/adapters/<chain>.py` with an `Adapter` subclass that
implements `_search(store, query, limit) -> list[Product]`, register it in
`adapters/__init__.py`, and add a parsing test with a small fixture in `tests/`.

## Disclaimer

Unofficial project, not affiliated with any retailer. Endpoints are undocumented and
may change. Intended for personal use; respect the sites' terms and keep request
volume low.

## License

MIT
