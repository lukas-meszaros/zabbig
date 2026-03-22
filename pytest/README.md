# pytest — automated test suite

This directory contains the automated test suite for the `zabbig_client` and `zabbix_update` modules.

For full documentation — setup, running, patterns, and how to write new tests — see:

→ **[docs/testing-pytest.md](../docs/testing-pytest.md)**

## Quick start

```bash
# 1. Create the virtual environment (first time only)
bash pytest/setup-pytest-venv.sh

# 2. Run all tests
pytest-venv/bin/pytest pytest/ -v
```
