"""Pick where to buy a basket: one store, or split across up to N stores.

The LLM does the fuzzy part (which product in each store matches "молоко 2.5%"),
this module does the exact arithmetic so totals are never hallucinated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations


@dataclass
class Plan:
    stores: tuple[str, ...]
    total: float  # goods only
    penalty: float  # extra_store_cost * (stores - 1)
    assignment: dict[str, tuple[str, float]]  # item -> (store, line cost)
    missing: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        return self.total + self.penalty

    def to_dict(self) -> dict:
        return {
            "stores": list(self.stores),
            "goods_total": round(self.total, 2),
            "extra_trip_penalty": round(self.penalty, 2),
            "score": round(self.score, 2),
            "items": {i: {"store": s, "cost": round(c, 2)} for i, (s, c) in self.assignment.items()},
            "missing": self.missing,
        }


def _plan(stores: tuple[str, ...], basket: list[dict], extra_store_cost: float) -> Plan:
    assignment: dict[str, tuple[str, float]] = {}
    missing: list[str] = []
    for line in basket:
        qty = line.get("quantity", 1)
        offers = [(s, p * qty) for s, p in line["offers"].items() if s in stores and p is not None]
        if offers:
            assignment[line["item"]] = min(offers, key=lambda o: o[1])
        else:
            missing.append(line["item"])
    used = tuple(s for s in stores if any(a[0] == s for a in assignment.values()))
    total = sum(c for _, c in assignment.values())
    return Plan(used or stores, total, extra_store_cost * max(len(used) - 1, 0), assignment, missing)


def optimize(basket: list[dict], max_stores: int = 2, extra_store_cost: float = 0.0) -> dict:
    """basket: [{"item": "молоко", "quantity": 2, "offers": {"magnit:123456": 89.99, ...}}]

    Prices in offers are per one unit of `quantity`. Returns the best single-store
    plan, the best plan with at most `max_stores` stores, and the saving between them.
    Plans that can't buy every item are ranked after complete ones.
    """
    all_stores = sorted({s for line in basket for s in line["offers"]})
    if not all_stores:
        return {"error": "no offers in basket"}

    def rank(p: Plan) -> tuple[int, float]:
        return (len(p.missing), p.score)

    singles = sorted((_plan((s,), basket, extra_store_cost) for s in all_stores), key=rank)
    multi = [
        _plan(combo, basket, extra_store_cost)
        for k in range(1, min(max_stores, len(all_stores)) + 1)
        for combo in combinations(all_stores, k)
    ]
    best_multi = min(multi, key=rank)
    best_single = singles[0]
    return {
        "best_single_store": best_single.to_dict(),
        "best_split": best_multi.to_dict(),
        "saving_vs_single": round(best_single.score - best_multi.score, 2),
        "all_single_stores": [p.to_dict() for p in singles],
    }
