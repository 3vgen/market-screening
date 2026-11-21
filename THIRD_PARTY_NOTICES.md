# Third-party notices

## pyaterochka_api

This project's browser-session technique for `5ka.ru` — and for the other
browser-based chains that follow the same pattern (Perekrestok, Dixy,
Krasnoe&Beloe, Chizhik) — was borrowed from
[Open-Inflation/pyaterochka_api](https://github.com/Open-Inflation/pyaterochka_api),
an unofficial async client for the Pyaterochka website:

1. warm up one Camoufox browser by opening `https://5ka.ru` once;
2. capture the site's own `x-*` request headers (including `x-device-id`) that its
   JS sends to `https://5d.5ka.ru/api`;
3. read the store the site picked for the session from
   `localStorage.DeliveryPanelStore` (`selectedStore.sapCode`);
4. call the catalog / store-picker / geocode endpoints with `fetch()` from inside
   the warm page.

The API endpoint paths in `src/market_screening/adapters/pyaterochka.py` also follow
what that project documents. The implementation here is original (it does not use
`human_requests`), but the approach is theirs.

`pyaterochka_api` is distributed under the MIT License:

```
MIT License

Copyright (c) 2024 Open-Inflation

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
