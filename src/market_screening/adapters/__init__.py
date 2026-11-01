from .base import Adapter
from .magnit import MagnitAdapter
from .pyaterochka import PyaterochkaAdapter
from .vkusvill import VkusvillAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    MagnitAdapter.chain: MagnitAdapter,
    VkusvillAdapter.chain: VkusvillAdapter,
    PyaterochkaAdapter.chain: PyaterochkaAdapter,
}

__all__ = ["ADAPTERS", "Adapter", "MagnitAdapter", "PyaterochkaAdapter", "VkusvillAdapter"]
