"""
collector_registry.py — Maps collector names to collector classes.

Collectors register themselves at import time using @register_collector.
The runner resolves names at runtime via get_collector().
"""
from __future__ import annotations

import logging
from typing import Type

log = logging.getLogger(__name__)

_REGISTRY: dict[str, Type] = {}


def register_collector(name: str):
    """Class decorator — register a collector under the given name."""
    def decorator(cls):
        _REGISTRY[name] = cls
        return cls
    return decorator


def get_collector(name: str) -> Type:
    """Return the collector class for the given name. Raises KeyError if unknown."""
    if name not in _REGISTRY:
        raise KeyError(
            f"No collector registered for '{name}'. "
            f"Known collectors: {sorted(_REGISTRY.keys())}"
        )
    return _REGISTRY[name]


def registered_names() -> list[str]:
    return sorted(_REGISTRY.keys())


def _ensure_collectors_imported() -> None:
    """Import all collector modules so their @register_collector decorators run."""
    from .collectors import cpu, memory, disk, service, network  # noqa: F401


# Called once at startup
_ensure_collectors_imported()
