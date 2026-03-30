#!/usr/bin/env python3
"""
encrypt_password.py -- Encrypt or decrypt database passwords for databases.yaml.

Passwords stored with the ENC: prefix are transparently decrypted by the
database collector at runtime.  Plain-text passwords (no ENC: prefix) are
also accepted but produce a warning unless strict mode is disabled.

Key management
--------------
  1. ZABBIG_DB_KEY environment variable -- base64url-encoded 32-byte key.
  2. secret.key file alongside run.py  -- same format; auto-created on first use.

Usage
-----
  python3 scripts/encrypt_password.py "mysecretpassword"
  python3 scripts/encrypt_password.py --decrypt "ENC:..."
  python3 scripts/encrypt_password.py --generate-key
  python3 scripts/encrypt_password.py --show-key

Security notes
--------------
  - AES-256-CBC via vendored pyaes (pure Python, no C extensions needed).
  - HMAC-SHA256 over IV || ciphertext ensures authenticity.
  - PKCS7 padding applied before encryption.
  - Keep secret.key (and ZABBIG_DB_KEY) confidential -- chmod 600 recommended.
"""
from __future__ import annotations

import argparse
import os
import sys

# Add src/ to path so zabbig_client._dbcrypto (and vendored pyaes) are importable.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from zabbig_client._dbcrypto import (  # noqa: E402
    generate_key,
    key_to_str,
    load_key,
    load_or_create_key,
    encrypt,
    decrypt,
    _DEFAULT_KEY_FILE,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Encrypt or decrypt database passwords for databases.yaml",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--decrypt",
        action="store_true",
        help="Decrypt an ENC:... token instead of encrypting",
    )
    group.add_argument(
        "--generate-key",
        action="store_true",
        help="Generate a new random key and print it (does not save or encrypt)",
    )
    group.add_argument(
        "--show-key",
        action="store_true",
        help="Print the currently loaded key (for verification)",
    )
    parser.add_argument(
        "--key-file",
        default=_DEFAULT_KEY_FILE,
        metavar="PATH",
        help=f"Path to secret.key file (default: {_DEFAULT_KEY_FILE})",
    )
    parser.add_argument(
        "value",
        nargs="?",
        help="Password to encrypt, or ENC:... token to decrypt",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    if args.generate_key:
        key = generate_key()
        print(key_to_str(key))
        print("\nSet in environment:  export ZABBIG_DB_KEY=<above>", file=sys.stderr)
        print(
            f"Or save to file:     echo '<above>' > {args.key_file} && chmod 600 {args.key_file}",
            file=sys.stderr,
        )
        return 0

    if args.show_key:
        try:
            key = load_key(args.key_file)
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(key_to_str(key))
        return 0

    if not args.value:
        print("ERROR: provide a value to encrypt/decrypt", file=sys.stderr)
        return 1

    if args.decrypt:
        try:
            key = load_key(args.key_file)
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        try:
            plaintext = decrypt(args.value, key)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(plaintext)
        return 0

    # Default: encrypt
    key = load_or_create_key(args.key_file)
    print(encrypt(args.value, key))
    return 0


if __name__ == "__main__":
    sys.exit(main())
