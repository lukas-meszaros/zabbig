# Encrypting Database Passwords

Database passwords in `databases.yaml` can be stored as encrypted tokens rather than plain text. The `scripts/encrypt_password.py` tool manages the full key and token lifecycle.

---

## Why encrypt?

Plain-text passwords in `databases.yaml` are accepted, but they carry a startup warning and expose credentials to anyone who can read the file. Encrypted tokens are safe to commit to version control (assuming the key file remains separate) and safe to share in configuration management systems.

---

## How it works

Tokens use AES-256-CBC encryption with PKCS7 padding and an HMAC-SHA256 integrity check over the IV and ciphertext. The scheme is implemented entirely in the vendored `pyaes` library — no system OpenSSL or compiled extensions are required.

Token format: `ENC:<base64url(hmac[32] || iv[16] || ciphertext)>`

The decryption key is a random 32-byte value stored as a base64url string. It is loaded from (in priority order):

1. `ZABBIG_DB_KEY` environment variable
2. `secret.key` file at the project root (alongside `run.py`)

A `secret.key` file is created automatically the first time you encrypt a password if neither source is available.

---

## Quick Start

```bash
# 1. Encrypt a password (creates secret.key on first run)
python3 scripts/encrypt_password.py "mysecretpassword"
# ENC:AaBbCc...

# 2. Paste the ENC:... token into databases.yaml
#    password: "ENC:AaBbCc..."

# 3. Start the client as normal
python3 run.py
```

The client reads the same `secret.key` at runtime to decrypt the token.

---

## Commands

### Encrypt a password

```bash
python3 scripts/encrypt_password.py "mypassword"
```

Outputs an `ENC:…` token to stdout. If `secret.key` does not exist, it is created and the path is shown on stderr.

### Decrypt a token (verify it round-trips)

```bash
python3 scripts/encrypt_password.py --decrypt "ENC:AaBbCc..."
```

Outputs the original plain-text password.

### Generate a standalone key

```bash
python3 scripts/encrypt_password.py --generate-key
```

Prints a new random key to stdout without saving it anywhere. Use this when you want to store the key in an environment variable or a secrets manager instead of in a file.

```bash
export ZABBIG_DB_KEY=$(python3 scripts/encrypt_password.py --generate-key 2>/dev/null)
```

### Show the current key

```bash
python3 scripts/encrypt_password.py --show-key
```

Prints the base64url representation of whichever key is currently loaded (env var or file). Useful to verify that the client and the script are using the same key.

### Use a custom key file path

```bash
python3 scripts/encrypt_password.py --key-file /etc/zabbig/secret.key "mypassword"
```

The `--key-file` flag overrides the default path for all commands.

---

## Key Storage Options

### Option A — `secret.key` file (default)

`scripts/encrypt_password.py` and the client both look for `secret.key` at the project root. Restrict permissions:

```bash
chmod 600 secret.key
```

Add the file to `.gitignore` so it is never committed:

```
secret.key
```

### Option B — environment variable

Generate a key and set it in the environment:

```bash
export ZABBIG_DB_KEY=$(python3 scripts/encrypt_password.py --generate-key 2>/dev/null)
```

Or in a systemd unit file:

```ini
[Service]
EnvironmentFile=/etc/zabbig/env
```

Where `/etc/zabbig/env` contains:

```
ZABBIG_DB_KEY=<base64url key>
```

`ZABBIG_DB_KEY` takes priority over `secret.key` when both are present.

---

## All Options

| Flag | Description |
|---|---|
| `--decrypt` | Decrypt an `ENC:…` token instead of encrypting. |
| `--generate-key` | Generate and print a new random key (does not save). |
| `--show-key` | Print the currently loaded key. |
| `--key-file PATH` | Path to the `secret.key` file (default: project root). |
| `value` (positional) | Password to encrypt, or `ENC:…` token when `--decrypt` is used. |

---

## Security Notes

- Keep `secret.key` and `ZABBIG_DB_KEY` confidential. Anyone with the key can decrypt all passwords.
- Each `encrypt` call produces a different token even for the same password (random IV per encryption). Both tokens decrypt correctly.
- HMAC verification catches accidental corruption and deliberate tampering: a modified token raises a `ValueError` at startup before any connection is attempted.
- The `ENC:` prefix is checked at load time. A truncated or invalid base64 token fails fast with a clear error message rather than silently using an empty password.
