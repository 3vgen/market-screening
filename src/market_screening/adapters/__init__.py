from .base import Adapter
from .chizhik import ChizhikAdapter
from .dixy import DixyAdapter
from .fixprice import FixPriceAdapter
from .krasnoeibeloe import KrasnoeIBeloeAdapter
from .magnit import MagnitAdapter
from .perekrestok import PerekrestokAdapter
from .pyaterochka import PyaterochkaAdapter
from .vkusvill import VkusvillAdapter

# plain HTTP: magnit, vkusvill, fixprice; headless browser (extra [browser]): the rest
ADAPTERS: dict[str, type[Adapter]] = {
    a.chain: a
    for a in (
        MagnitAdapter,
        VkusvillAdapter,
        FixPriceAdapter,
        PyaterochkaAdapter,
        PerekrestokAdapter,
        DixyAdapter,
        KrasnoeIBeloeAdapter,
        ChizhikAdapter,
    )
}

__all__ = [
    "ADAPTERS",
    "Adapter",
    "ChizhikAdapter",
    "DixyAdapter",
    "FixPriceAdapter",
    "KrasnoeIBeloeAdapter",
    "MagnitAdapter",
    "PerekrestokAdapter",
    "PyaterochkaAdapter",
    "VkusvillAdapter",
]
