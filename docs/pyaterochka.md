# Pyaterochka (5ka.ru): how it works and known limits

The adapter is a headless-browser session (Camoufox), because `5ka.ru` sits behind a
JS challenge. Notes below are what we learned while building it; they explain why some
Pyaterochka results look surprising.

## Browser session

Plain HTTP is not enough, so `PyaterochkaAdapter`:

1. opens `https://5ka.ru` once per server process (~20–30 s warm-up);
2. captures the `x-*` headers (including `x-device-id`) that the site's own JS sends to
   its catalog API;
3. runs `fetch()` from inside the page against `https://5d.5ka.ru/api` afterward
   (~0.5 s per search).

The approach is borrowed from [Open-Inflation/pyaterochka_api](https://github.com/Open-Inflation/pyaterochka_api)
(MIT License, Copyright (c) 2024 Open-Inflation; full text in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)). The implementation here is
original, but the technique and endpoints are theirs.

The browser extra is required:

```bash
.venv/bin/pip install -e ".[browser]" && .venv/bin/python -m camoufox fetch
```

If the warm-up page shows "Проблемы со связью. Проверьте настройки интернета и VPN" and
the adapter times out, this is a routing problem, not a login problem — see
[Network](#network-the-servicepipe-challenge) below.

## Store selection: the lookup returns a delivery hub

`store_code = "auto"` means "whatever store 5ka.ru picked for this session by IP
geolocation". The picked code is read from `localStorage.DeliveryPanelStore`.

`find_store("pyaterochka", address)` and `stores_near(address)` use the delivery
panel's store-picker (`/api/orders/v1/orders/stores/`), the only live public endpoint we
found. It answers with the store that **serves delivery** for the point — in our tests a
single **delivery hub (dark store)** for the whole city, not the nearest retail shop.
The old shop-locator endpoint (`/api/stores/?bbox=`) now answers 404, and we found no
public endpoint mapping a retail address to a 5ka `sap_code`.

Consequences:

- `stores_near` reports Pyaterochka but **never saves it** to `config.toml`
  (`NO_AUTOSAVE_CHAINS` in `server.py`), so a hand-picked code is never overwritten by a
  hub.
- Prices fetched with a hub code (`mode=store`) are the hub's catalog, which may differ
  from the shelf of a nearby shop.

### Workaround: set the shop's sap_code by hand

Take the `sap_code` of a real shop from the 5ka app (store card, "магазин №…") or from a
receipt and put it into `config.toml`:

```toml
[[stores]]
chain = "pyaterochka"
store_code = "<sap_code>"
name = "Пятёрочка (у дома)"
```

## Promotions

There is no "list current discounts" endpoint in the X5 catalog v3 API. `promos()`
walks the category tree (up to 60 top-level categories) and keeps products whose prices
carry a real discount or an offer (`cpd_promo_price`, markdown, promo flags). Promo
badges such as "от N шт" come from `prices.cpd_promo_price`.

## Network: the ServicePipe challenge

`5ka.ru` returns HTTP 200 quickly, but its SPA does not mount until the antibot JS
challenge from **`servicepipe.tech`** completes. If that third domain goes out through
the wrong egress (e.g. a VPN/datacenter IP), its requests hang, `DOMContentLoaded` never
fires, and the adapter times out. Perekrestok uses the same ServicePipe protection, so
one routing fix helps both.

Route all three domains through the same Russian egress:

```
5ka.ru
5d.5ka.ru
servicepipe.tech
```

In v2rayA RoutingA the rules must go **above** broader `geosite:` rules (first match
wins) — see the routing note in the main [README](../README.md#network-note).
