import pytest

from market_screening.units import parse_size, unit_price


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Молоко безлактозное Простоквашино 2.5% 970мл", (0.97, "l")),
        ("Молоко Домик в Деревне 1.8% 950г", (0.95, "kg")),
        ("Напиток овсяный Nemoloko 3.2% 1л", (1.0, "l")),
        ("Мюсли Matti банан и шоколад 250г", (0.25, "kg")),
        ("Йогурт Чудо 4x125г", (0.5, "kg")),
        ("Сахар 1,5 кг", (1.5, "kg")),
        ("Яйца С1 10шт", (10.0, "pcs")),
        ("Бананы", None),
    ],
)
def test_parse_size(name, expected):
    got = parse_size(name)
    if expected is None:
        assert got is None
    else:
        assert got[1] == expected[1]
        assert got[0] == pytest.approx(expected[0])


def test_unit_price():
    assert unit_price(84.99, "Молоко 2.5% 970мл") == (87.62, "l")
