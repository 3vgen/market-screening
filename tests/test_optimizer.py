from market_screening.optimizer import optimize

BASKET = [
    {"item": "молоко", "quantity": 2, "offers": {"A": 80.0, "B": 90.0}},
    {"item": "сыр", "offers": {"A": 300.0, "B": 220.0}},
    {"item": "хлеб", "offers": {"A": 50.0}},
]


def test_single_vs_split():
    r = optimize(BASKET, max_stores=2)
    assert r["best_single_store"]["stores"] == ["A"]
    assert r["best_single_store"]["goods_total"] == 510.0  # 160 + 300 + 50
    assert r["best_split"]["goods_total"] == 430.0  # 160 + 220(B) + 50
    assert r["saving_vs_single"] == 80.0


def test_extra_store_cost_can_make_single_store_win():
    r = optimize(BASKET, max_stores=2, extra_store_cost=100)
    assert r["best_split"]["stores"] == ["A"]
    assert r["saving_vs_single"] == 0


def test_store_missing_items_ranks_last():
    r = optimize(BASKET, max_stores=1)
    single_b = next(p for p in r["all_single_stores"] if p["stores"] == ["B"])
    assert single_b["missing"] == ["хлеб"]
    assert r["best_single_store"]["stores"] == ["A"]
