"""
collector_registry.py — Maps collector names to collector classes.

Collectors register themselves at import time using @register_collector.
The runner resolves names at runtime via get_collector().
"""
from __future__ import annotations

import importlib
import logging
from typing import Type

log = logging.getLogger(__name__)

_REGISTRY: dict[str, Type] = {}

# Mapping of logical collector name → submodule name under .collectors
_COLLECTOR_MODULE_MAP: dict[str, str] = {
    "cpu":      "cpu",
    "memory":   "memory",
    "disk":     "disk",
    "service":  "service",
    "network":  "network",
    "log":      "log",
    "probe":    "probe",
    "database": "database",
}


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


def load_collectors_for(names: set[str]) -> None:
    """Import only the collector modules needed for the given collector names.

    Safe to call multiple times — Python's import system caches modules, so
    already-imported modules are not re-executed. Unrecognised names are
    logged as warnings rather than raising an exception, so a misconfigured
    metric degrades gracefully at collection time instead of at startup.
    """
    for name in names:
        if name in _REGISTRY:
            continue  # already registered by a previous import
        module_slug = _COLLECTOR_MODULE_MAP.get(name)
        if module_slug is None:
            log.warning("Unknown collector name: %r — no module mapping", name)
            continue
        importlib.import_module(f".collectors.{module_slug}", package=__package__)
        log.debug("Loaded collector module: %s", module_slug)


def _ensure_collectors_imported() -> None:
    """Import all collector modules so their @register_collector decorators run.

    Prefer load_collectors_for() in production code to import only what is
    needed.  This function exists for tests and tooling that need the complete
    registry populated upfront.
    """
    load_collectors_for(set(_COLLECTOR_MODULE_MAP.keys()))
