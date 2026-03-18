# Troubleshooting

## Container not healthy / not starting

**Symptom:** `docker compose ps` shows a container in `unhealthy` or `restarting` state.

**Check logs:**
```bash
docker compose logs postgres
docker compose logs zabbix-server
docker compose logs zabbix-web
```

**Common causes:**

- **Database not ready in time:** Zabbix server starts before PostgreSQL has finished initialising. The `depends_on: condition: service_healthy` directive handles this, but if the DB is slow, the server may time out. Solution: wait a minute and run `docker compose restart zabbix-server`.
- **Wrong password:** The `POSTGRES_PASSWORD` in `.env` doesn't match what's stored in the volume. After changing passwords, run `bash scripts/reset.sh` to wipe the volume.
- **Port already in use:** Another service is using port `8080` or `10051`. Change `ZABBIX_WEB_PORT` or `ZABBIX_TRAPPER_PORT` in `.env` and run `docker compose up -d` again.

---

## DB startup timing issues

**Symptom:** Zabbix server logs show:
```
Cannot connect to the database. Reconnecting in 10 seconds.
```

**Cause:** PostgreSQL initialisation takes longer on first boot.

**Solution:** Wait 30–60 seconds and check again:
```bash
docker compose ps
```

Once `postgres` shows `healthy`, Zabbix server should connect. If it doesn't restart automatically:
```bash
docker compose restart zabbix-server
```

---

## Zabbix web UI unavailable

**Symptom:** Browser shows "Connection refused" or a 502 Bad Gateway at http://localhost:8080.

**Check:**
```bash
docker compose ps
docker compose logs zabbix-web
```

**Common causes:**

1. **Stack not started:** Run `bash scripts/start.sh`.
2. **Web container still initialising:** The first startup can take 1–2 minutes. Wait and refresh.
3. **Port conflict:** Something else is using port 8080. Change `ZABBIX_WEB_PORT` in `.env`.
4. **Zabbix server unhealthy:** The web frontend waits for the server. Check `docker compose logs zabbix-server`.

---

## Sender cannot connect (TCP refused)

**Symptom:** `zabbix_sender` or Python client shows:
```
Connection refused  /  [Errno 111] Connection refused
```

**Check:**
```bash
docker compose ps        # is zabbix-server healthy?
nc -zv 127.0.0.1 10051  # can macOS reach the port?
```

**Common causes:**

1. **Zabbix server not running:** Start the stack first.
2. **Wrong port:** Check `ZABBIX_TRAPPER_PORT` in `.env`.
3. **Docker Desktop network issue:** Restart Docker Desktop.
4. **Firewall:** macOS firewall blocking outbound connection. Usually not an issue for localhost.

---

## Host or item not found (sent: 0 / failed: 1)

**Symptom:** `zabbix_sender` output shows:
```
1 (0 sent, 1 skipped, 0 not sent)
```
or Python client shows `failed: 1`.

**Causes and checks:**

1. **Bootstrap not run:** Run `python3 scripts/bootstrap.py`.
2. **Host name mismatch:** The `--host` argument (or `host` field in Python) must exactly match the host name in Zabbix (case-sensitive). Check in **Configuration → Hosts**.
3. **Item key mismatch:** The `--key` argument must exactly match the item key in Zabbix. Check in **Configuration → Hosts → Items**.
4. **Host disabled:** Go to **Configuration → Hosts** and ensure the host is enabled (Status = Enabled).

---

## Allowed hosts mismatch

**Symptom:** Zabbix server logs show:
```
failed to accept an incoming connection: connection from "x.x.x.x" rejected, allowed hosts: "..."
```

**Cause:** The `ZBX_ALLOWEDIPRANGE` setting is restricting the sender's IP.

**Solution:** Set `ZBX_ALLOWEDIPRANGE=0.0.0.0/0` in `.env` (the default for this lab), then restart:
```bash
docker compose up -d zabbix-server
```

---

## Trigger not firing

**Symptom:** You sent a problem-triggering value but no problem appears in **Monitoring → Problems**.

**Checks:**

1. **Was the value received?** Go to **Monitoring → Latest data** and check if the item has a recent value.
2. **Is the trigger enabled?** Go to **Configuration → Hosts → Triggers**, check that the trigger is enabled and the expression is correct.
3. **Zabbix trigger evaluation delay:** Trigger evaluation is near real-time but may take up to 30 seconds. Wait and refresh.
4. **Trigger expression issue:** In Zabbix, go to **Configuration → Hosts → Triggers**, click the trigger name, and click **Test** to manually evaluate the expression.

For the heartbeat trigger specifically: the `nodata()` function triggers only after 5 minutes of silence. This is intentional.

---

## macOS Docker networking gotchas

**Issue: Containers can't resolve each other's names from macOS host.**

Containers use the internal `zabbix-lab-net` network. From your macOS terminal, always use `127.0.0.1` (not the container name) as the Zabbix server address.

**Issue: `host.docker.internal` not resolving.**

This is a Docker Desktop hostname for the macOS host (useful if containers need to reach the host). For this lab, it is not needed.

**Issue: Port binding only on 127.0.0.1.**

Docker Desktop on macOS binds ports to `127.0.0.1` by default, so `localhost:8080` and `localhost:10051` work from the macOS host but are not accessible from other machines on your network. This is the desired behaviour for a local lab.

**Issue: Docker Desktop stopped / sleeping.**

Docker Desktop must be running before `docker compose up`. Check the Docker Desktop icon in the macOS menu bar.

---

## Resetting the environment

If everything is broken and you want a clean slate:

```bash
bash scripts/reset.sh   # wipes all volumes
bash scripts/start.sh   # fresh start
python3 scripts/bootstrap.py  # re-provision
```
