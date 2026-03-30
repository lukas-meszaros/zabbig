"""
test_db_loader.py — Unit tests for zabbig_client.db_loader.

Tests cover:
  - load_databases_config() with valid and invalid inputs
  - Password decryption (ENC: prefix) and plain-text warnings
  - Missing field errors
  - Duplicate name errors
  - get_connection() dispatch
  - _try_load_key() returns None gracefully when no key is available
"""
import os
import sys
import pytest
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CLIENT_SRC = os.path.join(_ROOT, "zabbig_client", "src")
for _p in [_CLIENT_SRC]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import yaml

from zabbig_client.db_loader import (
    DatabaseConfigError,
    load_databases_config,
    _resolve_password,
    _connect_postgres,
)
from zabbig_client._dbcrypto import (
    generate_key,
    key_to_str,
    encrypt,
    ENC_PREFIX,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(tmp_path, data: dict) -> str:
    p = os.path.join(str(tmp_path), "databases.yaml")
    with open(p, "w") as f:
        yaml.dump(data, f)
    return p


# ---------------------------------------------------------------------------
# load_databases_config — happy path
# ---------------------------------------------------------------------------

class TestLoadDatabasesConfigBasic:
    def test_empty_databases_list(self, tmp_path):
        path = _write_yaml(tmp_path, {"version": 1, "databases": []})
        registry = load_databases_config(path, strict=True, strict_passwords=False)
        assert registry == {}

    def test_single_plaintext_entry(self, tmp_path):
        path = _write_yaml(tmp_path, {
            "version": 1,
            "databases": [{
                "name": "mydb",
                "type": "postgres",
                "host": "127.0.0.1",
                "port": 5432,
                "dbname": "appdb",
                "username": "monitor",
                "password": "secret",
            }],
        })
        registry = load_databases_config(path, strict=True, strict_passwords=False)
        assert "mydb" in registry
        cfg = registry["mydb"]
        assert cfg["host"] == "127.0.0.1"
        assert cfg["port"] == 5432
        assert cfg["dbname"] == "appdb"
        assert cfg["username"] == "monitor"
        assert cfg["password"] == "secret"
        assert cfg["type"] == "postgres"
        assert cfg["connect_timeout"] == 10

    def test_defaults_applied(self, tmp_path):
        path = _write_yaml(tmp_path, {
            "version": 1,
            "databases": [{
                "name": "minimal",
                "type": "postgres",
                "dbname": "db",
                "username": "u",
                "password": "p",
            }],
        })
        reg = load_databases_config(path, strict=False, strict_passwords=False)
        cfg = reg["minimal"]
        assert cfg["host"] == "127.0.0.1"
        assert cfg["port"] == 5432
        assert cfg["connect_timeout"] == 10
        assert cfg["options"] == {}

    def test_custom_connect_timeout(self, tmp_path):
        path = _write_yaml(tmp_path, {
            "version": 1,
            "databases": [{
                "name": "fast",
                "type": "postgres",
                "dbname": "db",
                "username": "u",
                "password": "p",
                "connect_timeout": 30,
            }],
        })
        reg = load_databases_config(path, strict=False, strict_passwords=False)
        assert reg["fast"]["connect_timeout"] == 30

    def test_options_forwarded(self, tmp_path):
        path = _write_yaml(tmp_path, {
            "version": 1,
            "databases": [{
                "name": "opts",
                "type": "postgres",
                "dbname": "db",
                "username": "u",
                "password": "p",
                "options": {"application_name": "zabbig"},
            }],
        })
        reg = load_databases_config(path, strict=False, strict_passwords=False)
        assert reg["opts"]["options"] == {"application_name": "zabbig"}


# ---------------------------------------------------------------------------
# load_databases_config — encrypted passwords
# ---------------------------------------------------------------------------

class TestEncryptedPasswords:
    def test_enc_password_decrypted(self, tmp_path, monkeypatch):
        key = generate_key()
        token = encrypt("my_secret_pw", key)
        monkeypatch.setenv("ZABBIG_DB_KEY", key_to_str(key))
        path = _write_yaml(tmp_path, {
            "version": 1,
            "databases": [{
                "name": "enc_db",
                "type": "postgres",
                "dbname": "db",
                "username": "u",
                "password": token,
            }],
        })
        reg = load_databases_config(path, strict=True, strict_passwords=True)
        assert reg["enc_db"]["password"] == "my_secret_pw"

    def test_enc_password_wrong_key_raises(self, tmp_path, monkeypatch):
        key1 = generate_key()
        key2 = generate_key()
        token = encrypt("pw", key1)
        monkeypatch.setenv("ZABBIG_DB_KEY", key_to_str(key2))
        path = _write_yaml(tmp_path, {
            "version": 1,
            "databases": [{
                "name": "bad_key",
                "type": "postgres",
                "dbname": "db",
                "username": "u",
                "password": token,
            }],
        })
        with pytest.raises(DatabaseConfigError, match="decrypt"):
            load_databases_config(path, strict=True, strict_passwords=True)

    def test_enc_without_key_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ZABBIG_DB_KEY", raising=False)
        path = _write_yaml(tmp_path, {
            "version": 1,
            "databases": [{
                "name": "no_key",
                "type": "postgres",
                "dbname": "db",
                "username": "u",
                "password": "ENC:sometoken",
            }],
        })
        # Patch _try_load_key to return None so the real secret.key file on disk
        # does not interfere with this test.
        from unittest.mock import patch
        with patch("zabbig_client.db_loader._try_load_key", return_value=None):
            with pytest.raises(DatabaseConfigError, match="no decryption key"):
                load_databases_config(path, strict=True, strict_passwords=True)


# ---------------------------------------------------------------------------
# load_databases_config — validation errors (strict mode)
# ---------------------------------------------------------------------------

class TestValidationErrors:
    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            load_databases_config("/nonexistent/databases.yaml")

    def test_missing_name_raises(self, tmp_path):
        path = _write_yaml(tmp_path, {
            "version": 1,
            "databases": [{
                "type": "postgres",
                "dbname": "db",
                "username": "u",
                "password": "p",
            }],
        })
        with pytest.raises(DatabaseConfigError, match="missing required field 'name'"):
            load_databases_config(path, strict=True, strict_passwords=False)

    def test_missing_dbname_raises(self, tmp_path):
        path = _write_yaml(tmp_path, {
            "version": 1,
            "databases": [{
                "name": "mydb",
                "type": "postgres",
                "username": "u",
                "password": "p",
            }],
        })
        with pytest.raises(DatabaseConfigError, match="missing required field 'dbname'"):
            load_databases_config(path, strict=True, strict_passwords=False)

    def test_unknown_type_raises(self, tmp_path):
        path = _write_yaml(tmp_path, {
            "version": 1,
            "databases": [{
                "name": "mydb",
                "type": "oracle",
                "dbname": "db",
                "username": "u",
                "password": "p",
            }],
        })
        with pytest.raises(DatabaseConfigError, match="unsupported type 'oracle'"):
            load_databases_config(path, strict=True, strict_passwords=False)

    def test_duplicate_name_raises(self, tmp_path):
        entry = {"name": "dup", "type": "postgres", "dbname": "db",
                 "username": "u", "password": "p"}
        path = _write_yaml(tmp_path, {
            "version": 1,
            "databases": [entry, entry],
        })
        with pytest.raises(DatabaseConfigError, match="Duplicate database name: 'dup'"):
            load_databases_config(path, strict=True, strict_passwords=False)

    def test_invalid_port_strict(self, tmp_path):
        path = _write_yaml(tmp_path, {
            "version": 1,
            "databases": [{
                "name": "mydb",
                "type": "postgres",
                "dbname": "db",
                "username": "u",
                "password": "p",
                "port": "not_a_number",
            }],
        })
        with pytest.raises(DatabaseConfigError, match="'port' must be an integer"):
            load_databases_config(path, strict=True, strict_passwords=False)

    def test_unsupported_version_strict(self, tmp_path):
        path = _write_yaml(tmp_path, {"version": 99, "databases": []})
        with pytest.raises(DatabaseConfigError, match="Unsupported databases.yaml version: 99"):
            load_databases_config(path, strict=True, strict_passwords=False)


# ---------------------------------------------------------------------------
# load_databases_config — non-strict mode (warnings, not errors)
# ---------------------------------------------------------------------------

class TestNonStrictMode:
    def test_unknown_type_warns_not_errors(self, tmp_path):
        path = _write_yaml(tmp_path, {
            "version": 1,
            "databases": [{
                "name": "mydb",
                "type": "oracle",
                "dbname": "db",
                "username": "u",
                "password": "p",
            }],
        })
        # Should not raise, entry is skipped
        reg = load_databases_config(path, strict=False, strict_passwords=False)
        assert "mydb" not in reg

    def test_plaintext_password_warns_not_errors(self, tmp_path, caplog):
        import logging
        path = _write_yaml(tmp_path, {
            "version": 1,
            "databases": [{
                "name": "mydb",
                "type": "postgres",
                "dbname": "db",
                "username": "u",
                "password": "plainpass",
            }],
        })
        with caplog.at_level(logging.WARNING):
            reg = load_databases_config(path, strict=False, strict_passwords=True)
        assert "mydb" in reg
        assert "plain text" in caplog.text


# ---------------------------------------------------------------------------
# _resolve_password
# ---------------------------------------------------------------------------

class TestResolvePassword:
    def test_plaintext_passthrough_no_strict(self):
        result = _resolve_password("mypass", "db", None, False, False)
        assert result == "mypass"

    def test_empty_password_no_warning(self):
        result = _resolve_password("", "db", None, True, False)
        assert result == ""

    def test_enc_requires_key(self):
        with pytest.raises(DatabaseConfigError, match="no decryption key"):
            _resolve_password("ENC:something", "testdb", None, True, True)

    def test_enc_decrypts_correctly(self, monkeypatch):
        key = generate_key()
        token = encrypt("supersecret", key)
        result = _resolve_password(token, "testdb", key, True, True)
        assert result == "supersecret"

    def test_enc_bad_token_raises(self, monkeypatch):
        key = generate_key()
        with pytest.raises(DatabaseConfigError, match="decrypt"):
            _resolve_password("ENC:notbase64!!", "testdb", key, True, True)
