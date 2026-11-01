"""Parse pack size from a product name to compute price per kg / l / pcs."""

from __future__ import annotations

import re

# unit -> (base unit, multiplier to base)
_UNITS = {
    "кг": ("kg", 1.0),
    "г": ("kg", 0.001),
    "гр": ("kg", 0.001),
    "л": ("l", 1.0),
    "мл": ("l", 0.001),
    "шт": ("pcs", 1.0),
}

_NUM = r"(\d+(?:[.,]\d+)?)"
_UNIT = r"(кг|гр|г|мл|л|шт)"
_SIZE_RX = re.compile(rf"{_NUM}\s*{_UNIT}(?![а-яё])", re.IGNORECASE)
_MULTI_RX = re.compile(rf"(\d+)\s*[xх×*]\s*{_NUM}\s*{_UNIT}(?![а-яё])", re.IGNORECASE)


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def parse_size(name: str) -> tuple[float, str] | None:
    """Return (amount in base unit, base unit) or None.

    "Молоко 2.5% 970мл" -> (0.97, "l"); "Йогурт 4x125г" -> (0.5, "kg").
    The last size mentioned wins: names usually end with the pack size.
    """
    multi = list(_MULTI_RX.finditer(name))
    if multi:
        count, amount, unit = multi[-1].groups()
        base, k = _UNITS[unit.lower()]
        return int(count) * _num(amount) * k, base

    sizes = list(_SIZE_RX.finditer(name))
    if not sizes:
        return None
    amount, unit = sizes[-1].groups()
    base, k = _UNITS[unit.lower()]
    value = _num(amount) * k
    return (value, base) if value > 0 else None


def unit_price(price: float, name: str) -> tuple[float, str] | None:
    size = parse_size(name)
    if size is None:
        return None
    amount, base = size
    return round(price / amount, 2), base
