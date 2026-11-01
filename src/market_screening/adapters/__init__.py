from .base import Adapter
from .magnit import MagnitAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    MagnitAdapter.chain: MagnitAdapter,
}

__all__ = ["ADAPTERS", "Adapter", "MagnitAdapter"]
