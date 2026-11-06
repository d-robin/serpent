# Troubleshooting

Start here, then find your symptom below.

## First, four commands

```bash
serpent status     # is it running, where, how long, last fault
serpent doctor     # checks Python, packages, .env, keys, folders, database, the server
serpent fault      # the last start/stop problem, with a hint
serpent log -n 80  # the end of the server log
```

`serpent doctor` marks each line `ok`, `warn` or `fail` and says what to run next. Most problems
are answered by one of these four.

## Starting and stopping

| Symptom | Cause | Fix |
| --- | --- | --- |
| `already running` | One folder runs one server. It is up. | `serpent status` shows the address; `serpent up` prints the sign-in link. Use `serpent restart` to restart it. |
| `port 8971 is busy` / it started on another port | Something else holds the port; Serpent moves up to the next free one and names the holder. | Use the printed address. To pin a port: `serpent start --port 9100`. The install then remembers it. |
| `python3 not found`, or "Python 3.10 or newer is needed" | Python is missing or old. | Install Python 3.10+ (Raspberry Pi OS: `sudo apt install -y python3 python3-venv`). `PYTHON=python3.12 ./serpent` picks a specific one. |
| `could not create .venv` | The `venv` module is missing (Debian, Ubuntu). | `sudo apt install python3-venv`, then run `./serpent` again. |
| `permission denied: ./serpent` | The launcher lost its executable bit (some zip extractors do this). | `chmod +x serpent` |
| Started, but `/healthz` never answers | The server crashed on start. | `serpent fault`, then `serpent log -n 100`; run `serpent run` in a terminal to see the error live. |
| It stopped after a reboot | `serpent up` is a background process. | Start it again, or use systemd or Docker ([Workflows](workflows.md#survive-a-reboot)). |
| `serpent stop` says the process ignored SIGTERM | It was busy; it was then stopped forcefully and a fault was recorded. | `serpent fault`; check `serpent status` shows stopped. |

## Snake Charmer (the web UI)

| Symptom | Cause | Fix |
| --- | --- | --- |
| "Snake Charmer isn't built yet" | A checkout without the UI bundle. | `cd ui && npm ci && npm run build` (the packaged and Docker builds include it). |
| Blank or old-looking page after an upgrade | The browser cached the old bundle. | Hard-reload (Shift-Reload). |
| "Public view" in the sidebar | You are not signed in; the dashboard is readable by default. | Click the key icon and enter an admin key, or use `serpent keys link`. |
| "That key was not accepted" | Wrong key, or the keys were rotated. | `serpent keys --reveal` shows the current ones. |
| Lost the admin key | Keys live in `.env`. | `serpent keys --reveal`, or make a new one: `serpent keys rotate admin` and restart. |
| Sign-in link opens but you are not admin | The link was for an earlier key. | Run `serpent keys link` again. |
| The sign-in link was shared | It contains the admin key. | `serpent keys rotate admin`, restart. |
| "No capacity" in the sidebar | No account can serve right now (none added, all disabled/invalid/cooling, or all used up). | Open **Accounts**: the status column says why. |
| A dialog or panel is cut off | An old cached bundle. | Hard-reload. |

## Calls through the router

| You get | Usual cause | Fix |
| --- | --- | --- |
| **401** | Missing or wrong router key. | Send `X-Router-Key: <client key>`. Check for a stray space or a rotated key. |
| **403** | The key's role is too low. | Use a client or admin key. |
| **404** | The route slug is wrong, **or** the request shape does not match the provider. | `serpent providers list`. SerpApi is `GET` with the query in the URL; Serper is `POST` with a JSON body. Compare with the provider's docs; the Search tab's **Raw response** shows what it said. |
| **429**, body says `quota exhausted` | No credit left this period. | Add an account, raise a limit, or wait for `resets_at`. `serpent accounts list` shows usage. |
| **429**, body says `router rate limit exceeded` | `RATE_LIMIT_PER_MINUTE` is set and you exceeded it. | Slow down, or raise/clear the limit in `.env`. |
| **429** straight away although credits remain | Accounts are cooling down or invalid; the reserve (`QUOTA_RESERVE`) holds credits back. | **Accounts** tab: look for `cooling down` or `invalid`. |
| **502** | The provider could not be reached. | Check the machine's network; try the provider's URL directly; retry later. |
| **503** | No provider yet, or the route has none enabled. | Add or enable a provider. |
| Provider error passed through (400, 402, 5xx…) | The provider rejected it. | Read the body. `X-Router-Error: all_accounts_failed` means every account failed. |
| It is slow | The provider is slow, or retries happened. | The Requests tab shows time per call and `X-Router-Attempts` shows retries. Raise `UPSTREAM_TIMEOUT` only if the provider is genuinely slow. |

## Accounts and credits

| Symptom | Explanation |
| --- | --- |
| Account shows **invalid** | The provider answered 401/403 for that key. Fix the key (`PATCH /admin/accounts/<id>` with a new `api_key`, or remove and re-add it) and enable it again. |
| Account shows **cooling down** | It failed recently (rate limit, 5xx, network). It retries automatically after an exponentially growing pause (`COOLDOWN_BASE_SECONDS` up to `COOLDOWN_MAX_SECONDS`). |
| Serpent's count differs from the provider's | Serpent counts what it sent. The provider may bill differently, and its period may reset on another day. Failures that never produced a result are refunded by default. Compare the **Provider allowance** column with **Your limit** (SerpApi). |
| A limit above the real plan | The provider will refuse before Serpent does. Keep your limit at or below the plan. |
| Usage looks wrong after testing | Reset it: Accounts → Reset, or `serpent accounts reset <id>`. |
| "Several accounts" warning | Pooling accounts at one provider may break its terms. Read [Responsible use](responsible-use.md). |

## Search tab

- **Results empty but the call worked:** the reply did not look like a list of links. Open
  **Raw response**; for an unusual provider set the method, path and body under *Request options*.
- **Amazon returns nothing:** SerpApi's Amazon engine takes the words in `k`, not `q`; the Search
  tab does this for you when you pick Amazon.
- **"The router needs a key":** sign in, or paste a client key under *Request options*.

## Logs, files and data

| Symptom | Fix |
| --- | --- |
| Where is the log? | `<home>/logs/router.log`; `serpent log -f`. systemd: `journalctl -u serpent -f`. Docker: `docker logs -f serpent`. |
| The log shows no search words | By design: bodies are never logged, and credential-like query parameters are removed. |
| `serpent doctor` warns the `.env` mode | `chmod 600 .env` (the install does this itself). |
| Database errors after a copy | Copy `data/serpent.db` only while stopped, or use `serpent backup`; remove stale `-wal`/`-shm` files after restoring. |
| Disk filling | The log rotates at 2 MB; the request history is capped; old usage periods are pruned. Look for large files in `backups/`. |

## Docker and systemd

- **Container restarts or is unhealthy:** `docker logs serpent`. The health check polls
  `/healthz` on port 8971.
- **Accounts vanished after recreating the container:** the data volume was not mounted. Mount
  `-v serpent-data:/data` and keep it.
- **Cannot sign in to a container:** keys come from `-e ROUTER_KEYS='admin-key:admin,client-key:client'`.
- **systemd unit fails:** `journalctl -u serpent -e`. Make sure the background copy is stopped
  (`serpent stop`); both would want the port. Re-generate the unit with `serpent systemd --out`
  if you moved the folder.

## Terminal UI

| Symptom | Fix |
| --- | --- |
| "needs an interactive terminal" | Run it in a real terminal, not a pipe or script. Use the plain commands there. |
| "terminal too small" | Enlarge the window to at least 64×16. |
| Garbled borders | Your terminal is not UTF-8; Serpent switches to ASCII automatically. Set `LANG=en_US.UTF-8` for the nicer look. |
| Cannot select text | Press `m` to turn the mouse off, select, press `m` again. |
| Plain colours | Set `TERM=xterm-256color`; `NO_COLOR=1` turns colour off on purpose. |

## Moving and removing

- **`serpent move` refuses a remote path:** use `user@host:/absolute/path` with letters, digits and `. _ / @ ~ + -` only; try `--dry-run` first.
- **After a move the new copy has new keys:** `.env` is carried only with `--with-env`, and data only with `--with-data`.
- **Uninstall left something:** the result table marks each item OK or FAIL. Items marked
  *MANUAL* (a systemd service, a pip/pipx package) need the printed command run by you.
- **Want a clean slate:** `serpent uninstall --delete-data`, then `./serpent` again.

## Still stuck? Collect this

```bash
serpent version
serpent doctor --json
serpent fault --all
serpent log -n 100      # remove anything private before sharing
```

Add the `X-Request-Id` of a failing call and what you expected. Never paste router keys,
provider keys or the sign-in link. Open an issue at
[github.com/d-robin/serpent/issues](https://github.com/d-robin/serpent/issues); report security
problems privately as described in [SECURITY.md](../SECURITY.md).
