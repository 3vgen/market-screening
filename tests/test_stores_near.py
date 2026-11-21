from market_screening.geo import haversine_km
from market_screening.server import _set_store, _write_config

SAMPLE = """\
# comment
[[stores]]
chain = "magnit"
store_code = "100001"
name = "Магнит (мой)"

[[stores]]
chain = "dixy"
store_code = "100002"
name = "Дикси (старый)"
"""


def test_haversine_known_distance():
    # 0.01 deg of latitude ~= 1.11 km at Moscow
    d = haversine_km(55.75, 37.61, 55.76, 37.61)
    assert abs(d - 1.11) < 0.01


def test_haversine_same_point_is_zero():
    assert haversine_km(55.75, 37.61, 55.75, 37.61) == 0.0


def test_set_store_updates_code_and_name_only_for_target_chain():
    text, ok = _set_store(SAMPLE, "dixy", "777", "Дикси (Ленинградский пр-т, 77)")
    assert ok
    assert 'chain = "dixy"\nstore_code = "777"' in text
    assert 'name = "Дикси (Ленинградский пр-т, 77)"' in text
    # other chains and the leading comment are left untouched
    assert 'store_code = "100001"' in text
    assert 'name = "Магнит (мой)"' in text
    assert text.startswith("# comment")


def test_set_store_missing_chain_is_noop():
    text, ok = _set_store(SAMPLE, "chizhik", "HBBN", None)
    assert not ok
    assert text == SAMPLE


def test_set_store_adds_name_when_absent():
    text = '[[stores]]\nchain = "dixy"\nstore_code = "100002"\n'
    new, ok = _set_store(text, "dixy", "777", "Новый Дикси")
    assert ok
    assert 'store_code = "777"' in new
    assert 'name = "Новый Дикси"' in new


def test_write_config_updates_file(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text(SAMPLE, encoding="utf-8")
    monkeypatch.setenv("MARKET_SCREENING_CONFIG", str(cfg))
    res = _write_config({"dixy": {"store_code": "999", "name": "Новый"}})
    assert res == {"updated": ["dixy"], "skipped": []}
    assert 'store_code = "999"' in cfg.read_text(encoding="utf-8")


def test_stores_near_does_not_save_pyaterochka(tmp_path, monkeypatch):
    import asyncio

    from market_screening import server

    cfg = tmp_path / "config.toml"
    cfg.write_text('[[stores]]\nchain = "pyaterochka"\nstore_code = "MINE"\n', encoding="utf-8")
    monkeypatch.setenv("MARKET_SCREENING_CONFIG", str(cfg))

    async def fake_geocode(address):
        return {"lon": 37.6, "lat": 55.7, "address_found": "x"}

    async def fake_nearest(chain, lon, lat):
        return {"store_code": "HUB", "address": "hub", "lat": 55.7, "lon": 37.6}

    monkeypatch.setattr(server, "geocode", fake_geocode)
    monkeypatch.setattr(server, "_resolve_nearest", fake_nearest)
    res = asyncio.run(server.stores_near("anywhere"))
    assert res["updated_in_config"] == []
    assert res["stores"][0]["store_code"] == "HUB" and "note" in res["stores"][0]
    assert 'store_code = "MINE"' in cfg.read_text(encoding="utf-8")
