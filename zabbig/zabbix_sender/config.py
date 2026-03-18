"""
config.py — Configuration for the Zabbix sender client.

Values can be set via environment variables.  CLI flags override env vars.
"""

import os


class Config:
    """
    Runtime configuration.

    Priority: CLI args > environment variables > defaults
    """

    def __init__(
        self,
        server: str | None = None,
        port: int | None = None,
        timeout: float | None = None,
    ) -> None:
        self.server: str = server or os.environ.get("ZABBIX_SERVER", "127.0.0.1")
        self.port: int = port or int(os.environ.get("ZABBIX_PORT", "10051"))
        self.timeout: float = timeout or float(os.environ.get("ZABBIX_TIMEOUT", "10"))

    def __repr__(self) -> str:
        return (
            f"Config(server={self.server!r}, port={self.port}, timeout={self.timeout})"
        )
