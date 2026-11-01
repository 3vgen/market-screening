from .base import Adapter
from .magnit import MagnitAdapter
from .vkusvill import VkusvillAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    MagnitAdapter.chain: MagnitAdapter,
    VkusvillAdapter.chain: VkusvillAdapter,
}

__all__ = ["ADAPTERS", "Adapter", "MagnitAdapter", "VkusvillAdapter"]
