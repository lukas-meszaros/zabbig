# Zabbix Setup

## Provisioning strategy

This lab uses **automated provisioning via the Zabbix API** (`scripts/bootstrap.py`).

**Why API-based provisioning?**
- Fully repeatable after a reset — one command restores the entire configuration.
- Idempotent — running the script twice does not create duplicates.
- No need to manually navigate UI menus.
- Self-documenting — the script is readable Python that shows exactly what is created.

---

## Host group

| Field  | Value           |
|--------|-----------------|
| Name   | `MacOS Senders` |

---

## Host

| Field           | Value                |
|-----------------|----------------------|
| Host name       | `macos-local-sender` |
| Visible name    | `macos-local-sender` |
| Host group      | `MacOS Senders`      |
| Interface       | Agent (placeholder), IP `127.0.0.1`, port `10050` |

> **Note:** The agent interface is a placeholder required by the Zabbix API. No actual Zabbix agent runs on the macOS host. Trapper items do not use the interface for data collection.

---

## Trapper items

Trapper items receive values pushed by an external sender. No polling interval is needed (`delay = 0`).

| Name          | Key                  | Type    | Value type       | Description                                        |
|---------------|----------------------|---------|------------------|----------------------------------------------------|
| Heartbeat     | `macos.heartbeat`    | Trapper | Numeric (float)  | Send `1` to indicate alive. Missing = problem.     |
| Status        | `macos.status`       | Trapper | Numeric (uint)   | `0`=OK, `1`=WARNING, `2`=CRITICAL                  |
| Error Count   | `macos.error_count`  | Trapper | Numeric (uint)   | Cumulative error count. Alert when `> 10`.         |
| Message       | `macos.message`      | Trapper | Text             | Free-form text. Visible in Latest Data, no trigger. |

---

## Triggers

Triggers define the conditions that cause Zabbix to create a **problem**.

### Trigger 1 — Heartbeat missing

| Field       | Value                                              |
|-------------|----------------------------------------------------|
| Name        | `Heartbeat missing for 5 minutes`                  |
| Expression  | `nodata(/macos-local-sender/macos.heartbeat,5m)=1` |
| Severity    | **HIGH**                                           |
| Behaviour   | Opens a problem if no heartbeat is received for 5 consecutive minutes. Recovers automatically once a new value arrives. |

> **To test:** Simply stop sending heartbeats for 5+ minutes and watch the problem appear in **Monitoring → Problems**.

---

### Trigger 2 — Status is CRITICAL

| Field       | Value                                                     |
|-------------|-----------------------------------------------------------|
| Name        | `Status is CRITICAL (macos.status >= 2)`                  |
| Expression  | `last(/macos-local-sender/macos.status)>=2`               |
| Severity    | **HIGH**                                                  |
| Behaviour   | Opens a problem when `macos.status` is `2` or higher. Recovers when `macos.status` drops below `2`. Manual close allowed. |

> **To test:** `zabbix-sender --host macos-local-sender --key macos.status --value 2`

---

### Trigger 3 — Error count above threshold

| Field       | Value                                                          |
|-------------|----------------------------------------------------------------|
| Name        | `Error count above threshold (macos.error_count > 10)`         |
| Expression  | `last(/macos-local-sender/macos.error_count)>10`               |
| Severity    | **AVERAGE**                                                    |
| Behaviour   | Opens a problem when more than 10 errors are reported. Recovers when `macos.error_count` drops to 10 or below. Manual close allowed. |

> **To test:** `zabbix-sender --host macos-local-sender --key macos.error_count --value 15`

---

## Re-running the bootstrap

The bootstrap script is safe to run any number of times:

```bash
python3 scripts/bootstrap.py
```

After a full reset (`bash scripts/reset.sh`), re-running this script restores all configuration.

---

## Verifying in the UI

1. **Configuration → Hosts** — confirm `macos-local-sender` is listed and enabled.
2. Click the host → **Items** — confirm four trapper items are listed.
3. Click the host → **Triggers** — confirm three triggers are listed.
4. **Monitoring → Latest data** — filter by host, send a test value, confirm it appears.
5. **Monitoring → Problems** — send a problem-triggering value, confirm a problem is created.
