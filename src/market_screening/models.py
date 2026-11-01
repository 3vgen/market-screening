from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Store:
    chain: str
    store_code: str
    name: str = ""

    @property
    def key(self) -> str:
        return f"{self.chain}:{self.store_code}"


@dataclass
class Product:
    store: str  # Store.key, e.g. "magnit:123456"
    product_id: str
    name: str
    price: float  # rubles, price you pay for one unit of sale (pack / piece / weighed portion)
    old_price: float | None = None
    is_promo: bool = False
    promo_until: str | None = None
    stock: float | None = None
    unit_price: float | None = None  # rubles per `unit`
    unit: str | None = None  # "kg" | "l" | "pcs"
    is_weighted: bool = False
    badges: list[str] = field(default_factory=list)
    url: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, [], False)}
