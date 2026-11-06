# Run and operate

Starting, stopping, watching, logging, backing up and upgrading Serpent. For first-time setup
see [Getting started](getting-started.md); for servers, systemd and Docker details see
[Deploying](deploying.md).

## Ways to run it

| How | Command | Survives a reboot? | Good for |
| --- | --- | --- | --- |
| Background daemon | `./serpent up` (or `serpent start`) | No | your laptop, trying it out |
| Foreground | `serpent run` | No | debugging; logs go to your terminal |
| systemd | `serpent systemd --out serpent.service` and install it | **Yes** | a Raspberry Pi or Linux server |
| Docker | `docker run … --restart unless-stopped` | **Yes** | containers, NAS, cloud |

Use one at a time per install: two would want the same port. Serpent refuses to start a second
copy from the same folder and tells you where the first one is.

## Everyday commands

```bash
./serpent up            # start (or show it is already running) and print the sign-in link
serpent status          # pid, url, uptime, memory, accounts, last fault
serpent health          # liveness, readiness, database, disk
serpent doctor          # health plus checks of the environment (Python, .env, keys, folders)
serpent log -f          # follow the server log (Ctrl-C to stop)
serpent restart         # stop then start (after editing .env)
serpent stop
./serpent               # in a terminal: the terminal UI, which does all of the above
```

`./serpent` runs `.venv/bin/serpent` for this folder. Add it to your PATH
(`ln -s "$PWD/serpent" ~/.local/bin/serpent`) to type `serpent` from anywhere; set
`SERPENT_HOME=/path` or use `--home /path` to operate a different install.

## Ports and binding

- The default port is `8971`. A home **remembers** its port in `.serpent-install.json`.
- Port order: `--port`, then `SERPENT_PORT`, then `BIND_PORT` in `.env`, then the remembered one,
  then `8971`. If the port is busy Serpent walks upward and tells you **who** holds the busy one
  (including another Serpent install and its folder).
- It listens on `127.0.0.1` unless you pass `--host 0.0.0.0` or set `BIND_HOST`.

## Where things are

```
<home>/
  .env                      settings and router keys (0600)
  data/serpent.db           accounts, provider keys, usage, history (0600)
  backups/                  database backups from `serpent backup` (0600)
  logs/router.log           the server log (rotated at 2 MB)
  logs/faults.log           one JSON line per start/stop problem, with a hint
  run/                      pid and port of the running server
  .venv/                    private Python environment (created by ./serpent)
  .serpent-install.json     what the installer made, and this install's port
```

## Logs

| Source | How to read it |
| --- | --- |
| Background daemon | `serpent log -n 100`, `serpent log -f`, or open `logs/router.log` |
| Foreground (`serpent run`) | your terminal |
| systemd | `journalctl -u serpent -f` |
| Docker | `docker logs -f serpent` |
| Terminal UI | the **Logs** tab (errors in red) |
| Snake Charmer | the **Requests** tab shows each call; **Overview** shows recent traffic |

**Format.** One JSON object per line, for example:

```json
{"ts":"2026-11-05T22:30:32","level":"info","logger":"serpent","msg":"upstream GET account=main status=200 ms=212.4",
 "request_id":"d85892cff841","path":"/p/serpapi/search","status":200,"account":"main","latency_ms":212.4,"attempt":1,"client":"d5fe8251"}
```

`client` is a short fingerprint of the router key, never the key. **Provider keys, request bodies
and responses are never logged.** Follow one call end to end with its `request_id`
(`grep d85892cff841 logs/router.log`). Set `LOG_LEVEL=debug` in `.env` for more detail and
restart.

**Size.** `router.log` is rotated when it exceeds 2 MB, checked each time the server starts.
Under systemd or Docker the platform's own log handling applies.

**Faults.** When a start or stop goes wrong Serpent records the reason and a hint:
`serpent fault` shows the latest, `serpent fault --all` the history.

**Request history.** The Requests tab (and `serpent requests -n 50`) keeps the newest
`REQUEST_LOG_SIZE` calls (500 by default) with method, path and query (credential-like
parameters removed), provider, account, status and time.

## Health and monitoring

| Endpoint | Meaning |
| --- | --- |
| `GET /healthz` | the process is up (always `200`) |
| `GET /readyz` | `200` when at least one credit is spendable, else `503` |
| `GET /metrics` | Prometheus text (needs a read key when authentication is on) |
| `GET /v1/quota` | totals and reset time (read key or higher) |

Prometheus metrics: `serpent_quota_remaining`, `serpent_quota_used`, `serpent_quota_capacity`,
`serpent_accounts`, `serpent_requests_total`, `serpent_uptime_seconds`.

Docker's `HEALTHCHECK` already polls `/healthz`. A simple external check is
`curl -fsS http://host:8971/readyz`.

## Resources

About 60 to 70 MB of memory idle; one worker handles hundreds of requests a minute because the
work is waiting on providers. `--workers 2` is safe: credits are reserved in SQLite, not in
process memory. Disk use is small: two usage rows per account per month (old months are
pruned), a capped request history and the log.

## Change settings

- **Tuning** (rotation strategy, retries, cooldowns, reserve, timeouts): Snake Charmer
  **Settings**, or the terminal UI **Manage → Settings**. Saved in the database and applied
  immediately from the web UI (after a restart if set from the terminal).
- **Deployment facts** (port, bind address, router keys, database path): `.env`, then
  `serpent restart`. Every setting is in the [Reference](reference.md#configuration).

## Keys

```bash
serpent keys                 # masked
serpent keys --reveal        # full values (asks first)
serpent keys link            # Snake Charmer sign-in URL for the admin
serpent keys rotate client   # new key for a role (admin, client, read); restart afterwards
```

After rotating the `client` key, update every app that uses it.

## Back up and restore

```bash
serpent backup               # online copy into backups/serpent-<date>.db, safe while running
```

Keep it as private as `.env`: it contains your provider keys. To restore, stop Serpent, put the
file at `data/serpent.db` (remove a stale `serpent.db-wal` and `serpent.db-shm`), restore `.env`
too if the router keys must stay the same, and start again.

## Upgrade

```bash
git pull
.venv/bin/pip install -e .   # only needed when dependencies changed
serpent restart
serpent doctor
```

The web UI is committed pre-built, so no Node.js is needed. Database changes are additive and
applied at start. Take a `serpent backup` first if you like.

## Reboots

`serpent up` does not come back after a reboot; Docker and systemd do. See
[Workflows → Survive a reboot](workflows.md#survive-a-reboot).

## Move or remove

[Workflows](workflows.md#run-it-on-another-machine-move) covers moving an install and
[uninstalling](workflows.md#uninstall-or-redeploy-differently) it, with the data choices
explained.
