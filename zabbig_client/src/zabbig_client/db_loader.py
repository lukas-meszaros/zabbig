"""
db_loader.py — Load and validate databases.yaml; provide DB connections.

databases.yaml format (version: 1)
-----------------------------------
version: 1
databases:
  - name: local_postgres      # identifier referenced by metrics.yaml params.database
    type: postgres
    host: "127.0.0.1"
    port: 5432
    dbname: "appdb"
    username: "monitor"
    password: "ENC:..."       # from scripts/encrypt_password.py; plaintext also accepted
    connect_timeout: 10       # optional, seconds (default: 10)
    options: {}               # optional driver-specific keyword args

Password decryption
-------------------
  Each entry's password is decrypted at load time if it carries an ENC: prefix.
  The decryption key is loaded from:
    1. ZABBIG_DB_KEY environment variable (base64url-encoded 32-byte key)
    2. secret.key file alongside run.py

  Plain-text passwords (no ENC: prefix) are accepted with a warning.
  To suppress the warning, set strict_passwords=False when calling
  load_databases_config().

Extensibility
-------------
  get_connection() dispatches on the 'type' field.  Adding Oracle / MySQL
  requires only a new _connect_<type>() function and registration in
  _CONNECT_HANDLERS — no collector changes needed.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import yaml  # vendored in src/yaml/

from ._dbcrypto import (
    ENC_PREFIX,
    decrypt,
    load_key,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------

class DatabaseConfigError(ValueError):
    """Raised when databases.yaml contains an invalid value."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_databases_config(
    path: str,
    strict: bool = True,
    strict_passwords: bool = True,
) -> dict[str, dict]:
    """
    Load and validate databases.yaml.

    Returns a registry dict: {name: db_config_dict}.

    The returned dicts have passwords already decrypted (plain strings).
    Any ENC: value is decrypted in-place; a new key 'password' holds the result.

    Args:
        path:              Path to databases.yaml.
        strict:            When True, raise DatabaseConfigError on any problem.
                           When False, log warnings and continue.
        strict_passwords:  When True, raise if a password is stored as plain text
                           (no ENC: prefix).  Defaults to True.

    Raises:
        FileNotFoundError:    When the file does not exist.
        DatabaseConfigError:  On schema/validation errors (strict=True).
    """
    raw = _read_yaml(path)

    version = raw.get("version", 1)
    if version != 1:
        _db_error(f"Unsupported databases.yaml version: {version}", strict)

    entries = raw.get("databases", [])
    if not isinstance(entries, list):
        _db_error("'databases' must be a list", strict)
        entries = []

    registry: dict[str, dict] = {}
    seen_names: set[str] = set()

    # Attempt to load the decryption key once for all entries.
    _key: bytes | None = _try_load_key()

    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            _db_error(f"databases[{i}] must be a mapping", strict)
            continue

        name = entry.get("name")
        if not name:
            _db_error(f"databases[{i}] missing required field 'name'", strict)
            continue
        name = str(name)

        if name in seen_names:
            _db_error(f"Duplicate database name: '{name}'", strict)
            continue
        seen_names.add(name)

        db_type = str(entry.get("type", "")).lower()
        if not db_type:
            _db_error(f"Database '{name}': missing required field 'type'", strict)
            continue

        supported_types = set(_CONNECT_HANDLERS.keys())
        if db_type not in supported_types:
            _db_error(
                f"Database '{name}': unsupported type '{db_type}'. "
                f"Supported: {sorted(supported_types)}",
                strict,
            )
            continue

        host = str(entry.get("host", "127.0.0.1"))
        port = entry.get("port")
        try:
            port = int(port) if port is not None else 5432
        except (TypeError, ValueError):
            _db_error(f"Database '{name}': 'port' must be an integer", strict)
            port = 5432

        dbname = entry.get("dbname")
        if not dbname:
            _db_error(f"Database '{name}': missing required field 'dbname'", strict)
            dbname = ""

        username = entry.get("username")
        if not username:
            _db_error(f"Database '{name}': missing required field 'username'", strict)
            username = ""

        raw_password = entry.get("password", "")
        if raw_password is None:
            raw_password = ""
        raw_password = str(raw_password)

        password = _resolve_password(
            raw_password, name, _key, strict_passwords, strict
        )

        connect_timeout = entry.get("connect_timeout", 10)
        try:
            connect_timeout = int(connect_timeout)
        except (TypeError, ValueError):
            _db_error(
                f"Database '{name}': 'connect_timeout' must be an integer", strict
            )
            connect_timeout = 10

        options: dict = {}
        raw_options = entry.get("options", {})
        if raw_options:
            if not isinstance(raw_options, dict):
                _db_error(
                    f"Database '{name}': 'options' must be a mapping", strict
                )
            else:
                options = dict(raw_options)

        registry[name] = {
            "name": name,
            "type": db_type,
            "host": host,
            "port": port,
            "dbname": str(dbname),
            "username": str(username),
            "password": password,
            "connect_timeout": connect_timeout,
            "options": options,
        }

    return registry


def get_connection(db_config: dict) -> Any:
    """
    Open and return a live DB connection for the given database config dict.

    Uses the 'type' field to dispatch to the appropriate driver.
    The caller is responsible for closing the connection.

    Raises:
        DatabaseConfigError: Unknown type.
        Any driver exception for connection failures.
    """
    db_type = db_config.get("type", "")
    handler = _CONNECT_HANDLERS.get(db_type)
    if handler is None:
        raise DatabaseConfigError(
            f"No handler registered for database type '{db_type}'"
        )
    return handler(db_config)


# ---------------------------------------------------------------------------
# Driver implementations
# ---------------------------------------------------------------------------

def _connect_postgres(db_config: dict) -> Any:
    """
    Open a pg8000 connection for a postgres-type database config.

    pg8000 is a pure-Python PostgreSQL driver vendored in src/pg8000/.
    """
    import pg8000.native  # vendored

    kwargs: dict[str, Any] = {
        "host": db_config["host"],
        "port": db_config["port"],
        "database": db_config["dbname"],
        "user": db_config["username"],
        "password": db_config["password"],
        "timeout": db_config.get("connect_timeout", 10),
    }

    # Merge driver-specific options (e.g. ssl_context, application_name)
    for k, v in db_config.get("options", {}).items():
        kwargs[k] = v

    return pg8000.native.Connection(**kwargs)


# Dispatch table: type string -> connection factory
_CONNECT_HANDLERS: dict[str, Any] = {
    "postgres": _connect_postgres,
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_yaml(path: str) -> dict:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Databases config file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise DatabaseConfigError(
            f"YAML syntax error in '{path}': {exc}"
        ) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise DatabaseConfigError(
            f"databases.yaml must be a YAML mapping, got "
            f"{type(data).__name__}: {path}"
        )
    return data


def _db_error(message: str, strict: bool) -> None:
    if strict:
        raise DatabaseConfigError(message)
    log.warning("Database config warning: %s", message)


def _try_load_key() -> bytes | None:
    """Load the encryption key, returning None if unavailable."""
    try:
        return load_key()
    except Exception:
        log.debug(
            "No encryption key available; ENC: passwords will fail at decrypt time"
        )
        return None


def _resolve_password(
    raw: str,
    db_name: str,
    key: bytes | None,
    strict_passwords: bool,
    strict: bool,
) -> str:
    """Decrypt raw password if ENC:-prefixed; otherwise validate/warn."""
    if raw.startswith(ENC_PREFIX):
        if key is None:
            raise DatabaseConfigError(
                f"Database '{db_name}': password is encrypted (ENC:) but no "
                "decryption key is available. Set ZABBIG_DB_KEY or provide "
                "a secret.key file."
            )
        try:
            return decrypt(raw, key)
        except ValueError as exc:
            raise DatabaseConfigError(
                f"Database '{db_name}': failed to decrypt password: {exc}"
            ) from exc
    else:
        if raw and strict_passwords:
            _db_error(
                f"Database '{db_name}': password is stored as plain text. "
                "Use scripts/encrypt_password.py to encrypt it.",
                strict,
            )
    return raw


# ---------------------------------------------------------------------------
