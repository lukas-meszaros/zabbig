from scramp.core import (
    ScramClient,
    ScramException,
    ScramMechanism,
    make_channel_binding,
)

__all__ = ["ScramClient", "ScramException", "ScramMechanism", "make_channel_binding"]

try:
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("scramp")
except Exception:
    __version__ = "unknown"
