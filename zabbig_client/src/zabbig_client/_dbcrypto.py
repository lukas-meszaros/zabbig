"""
_dbcrypto.py — Shared cryptographic primitives for database password management.

Used by both db_loader.py (runtime decryption) and scripts/encrypt_password.py
(CLI encryption tool).

Encryption scheme
-----------------
  Key:         32 bytes (AES-256), loaded from ZABBIG_DB_KEY env var or secret.key file.
  Cipher:      AES-256-CBC with random 16-byte IV (via vendored pyaes).
  Padding:     PKCS7.
  Authenticity: HMAC-SHA256 over IV || ciphertext (stdlib hmac + hashlib).
  Wire format: ENC:<base64url(hmac[32] || iv[16] || ciphertext)>  (no padding chars)

This format is intentionally simple and self-contained — no third-party crypto
library with C extensions is required.
"""
from __future__ import annotations

import base64
import hmac
import hashlib
import os
import sys

# Ensure src/ is on the path so pyaes can be imported when this module is
# loaded from an arbitrary working directory (e.g. scripts/encrypt_password.py).
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.dirname(_HERE)          # src/
_CLIENT_ROOT = os.path.dirname(_SRC)   # zabbig_client/
_PROJECT_ROOT = os.path.dirname(_CLIENT_ROOT)

for _p in (_SRC,):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pyaes  # vendored in src/pyaes/

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENC_PREFIX = "ENC:"
_IV_LEN = 16       # AES block size = IV length
_KEY_LEN = 32      # AES-256 requires a 32-byte key
_HMAC_LEN = 32     # HMAC-SHA256 output length

# Default key file: secret.key alongside run.py (project root)
_DEFAULT_KEY_FILE = os.path.join(_PROJECT_ROOT, "secret.key")


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------

def generate_key() -> bytes:
    """Return a fresh cryptographically random 32-byte key."""
    return os.urandom(_KEY_LEN)


def key_to_str(key: bytes) -> str:
    """Encode a raw key as a base64url string (no padding) for storage."""
    return base64.urlsafe_b64encode(key).rstrip(b"=").decode("ascii")


def key_from_str(s: str) -> bytes:
    """Decode a base64url key string back to raw bytes."""
    s = s.strip()
    padding = (-len(s)) % 4
    raw = base64.urlsafe_b64decode(s + "=" * padding)
    if len(raw) != _KEY_LEN:
        raise ValueError(
            f"Invalid key length: expected {_KEY_LEN} bytes, got {len(raw)}"
        )
    return raw


def load_key(key_file: str = _DEFAULT_KEY_FILE) -> bytes:
    """
    Load the encryption key.

    Priority:
      1. ZABBIG_DB_KEY environment variable (base64url-encoded 32-byte key)
      2. secret.key file at *key_file* path

    Raises RuntimeError if neither source is available.
    """
    env_val = os.environ.get("ZABBIG_DB_KEY", "").strip()
    if env_val:
        return key_from_str(env_val)

    if os.path.isfile(key_file):
        with open(key_file, "r", encoding="utf-8") as fh:
            return key_from_str(fh.read().strip())

    raise RuntimeError(
        "No encryption key found.\n"
        "Set ZABBIG_DB_KEY environment variable, or create a secret.key file.\n"
        "Run:  python3 scripts/encrypt_password.py --generate-key  to create one."
    )


def load_or_create_key(key_file: str = _DEFAULT_KEY_FILE) -> bytes:
    """Load the key, generating and saving a new secret.key if neither source exists."""
    try:
        return load_key(key_file)
    except RuntimeError:
        key = generate_key()
        os.makedirs(os.path.dirname(os.path.abspath(key_file)), exist_ok=True)
        with open(key_file, "w", encoding="utf-8") as fh:
            fh.write(key_to_str(key) + "\n")
        os.chmod(key_file, 0o600)
        import sys as _sys
        print(
            f"Generated new key → saved to {key_file}\n"
            "Protect this file — losing it means losing access to encrypted passwords.",
            file=_sys.stderr,
        )
        return key


# ---------------------------------------------------------------------------
# PKCS7 padding
# ---------------------------------------------------------------------------

def _pad(data: bytes) -> bytes:
    pad_len = _IV_LEN - (len(data) % _IV_LEN)
    return data + bytes([pad_len] * pad_len)


def _unpad(data: bytes) -> bytes:
    if not data:
        raise ValueError("Empty data after decryption")
    pad_len = data[-1]
    if pad_len < 1 or pad_len > _IV_LEN:
        raise ValueError(f"Invalid PKCS7 padding byte: {pad_len}")
    if data[-pad_len:] != bytes([pad_len] * pad_len):
        raise ValueError("PKCS7 padding verification failed")
    return data[:-pad_len]


# ---------------------------------------------------------------------------
# Encrypt / Decrypt
# ---------------------------------------------------------------------------

def encrypt(plaintext: str, key: bytes) -> str:
    """
    Encrypt *plaintext* with AES-256-CBC and return an ``ENC:...`` token.

    Format: ENC:<base64url(hmac[32] || iv[16] || ciphertext)>
    """
    iv = os.urandom(_IV_LEN)
    padded = _pad(plaintext.encode("utf-8"))
    aes = pyaes.AESModeOfOperationCBC(key, iv=iv)
    ciphertext = b""
    for i in range(0, len(padded), _IV_LEN):
        ciphertext += aes.encrypt(padded[i : i + _IV_LEN])
    mac = hmac.new(key, iv + ciphertext, hashlib.sha256).digest()
    payload = mac + iv + ciphertext
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
    return f"{ENC_PREFIX}{encoded}"


def decrypt(token: str, key: bytes) -> str:
    """
    Decrypt an ``ENC:...`` token and return the original plaintext.

    Raises ValueError on bad format, HMAC mismatch, or padding error.
    """
    if not token.startswith(ENC_PREFIX):
        raise ValueError(f"Token does not start with '{ENC_PREFIX}'")
    b64 = token[len(ENC_PREFIX):]
    padding = (-len(b64)) % 4
    try:
        payload = base64.urlsafe_b64decode(b64 + "=" * padding)
    except Exception as exc:
        raise ValueError(f"Invalid base64 in token: {exc}") from exc

    min_len = _HMAC_LEN + _IV_LEN + _IV_LEN  # 1 block minimum ciphertext
    if len(payload) < min_len:
        raise ValueError(
            f"Token too short: {len(payload)} bytes (need at least {min_len})"
        )

    stored_mac = payload[:_HMAC_LEN]
    iv = payload[_HMAC_LEN : _HMAC_LEN + _IV_LEN]
    ciphertext = payload[_HMAC_LEN + _IV_LEN :]

    expected_mac = hmac.new(key, iv + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(stored_mac, expected_mac):
        raise ValueError("HMAC verification failed — wrong key or tampered data")

    aes = pyaes.AESModeOfOperationCBC(key, iv=iv)
    padded = b""
    for i in range(0, len(ciphertext), _IV_LEN):
        padded += aes.decrypt(ciphertext[i : i + _IV_LEN])

    return _unpad(padded).decode("utf-8")


def is_encrypted(value: str) -> bool:
    """Return True when *value* carries the ENC: prefix."""
    return value.startswith(ENC_PREFIX)


def decrypt_if_encrypted(value: str, key: bytes) -> str:
    """Decrypt *value* only if it has an ENC: prefix; otherwise return as-is."""
    if is_encrypted(value):
        return decrypt(value, key)
    return value
