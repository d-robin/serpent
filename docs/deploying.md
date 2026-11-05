# Deploying

## Raspberry Pi and systemd

### systemd (recommended)

```bash
./install.sh
sudo cp deploy/serpent.local.service /etc/systemd/system/serpent.service
sudo systemctl daemon-reload
sudo systemctl enable --now serpent
journalctl -u serpent -f
```

`install.sh` writes `deploy/serpent.local.service` with the real
`User=`, `WorkingDirectory=` and paths of wherever the project sits, so there
is nothing to hand-edit. The shipped `deploy/serpent.service` is the
`/home/pi/serpent` template. The unit caps `MemoryMax=320M` and restricts
write access to `data/`.

Use either systemd or `serpent start`, not both — they would fight over the
port. systemd is the right choice for boot-time; `serpent start` is for manual runs and
gives you `status`, `health`, `log` and `fault`. After changing `.env`:

```bash
sudo systemctl restart serpent      # systemd
# or
serpent restart                        # or: serpent restart
serpent health
```

Tune `STRATEGY`, `MAX_RETRIES` etc. in `.env`, then `sudo systemctl restart
serpent`.

### Docker

```bash
docker build -t serpent .
docker run -d --name serpent -p 8971:8971 \
  -v serpent-data:/data \
  -e ROUTER_KEYS='admin-key:admin,client-key:client' \
  --restart unless-stopped serpent
```

Then open `http://<host>:8971/ui/`, sign in with the admin key and add your provider.

### Sizing

- Idle RSS is roughly 60–70 MB; the systemd unit caps it at 320 MB.
- One worker handles hundreds of req/min comfortably — the work is I/O bound.
  `--workers 2` is safe: quota atomicity is enforced by SQLite, not by process
  memory. See `scripts/concurrency_check.py`.
- Disk: usage rows are 2 per account per period; the request log is capped at
  `REQUEST_LOG_SIZE`. Old usage periods are pruned to the last 6.

### Backups

Everything lives in one SQLite file.

```bash
sqlite3 data/serpent.db ".backup 'backup-$(date +%F).db'"
```

Copying the `.db` while the service runs is not safe (WAL); use `.backup` or
stop the service first.

---

## Security notes

- Provider keys live in the SQLite file and are **never** returned by any
  endpoint or the dashboard; only a `****last4` hint is exposed. Keep `.env` at
  mode 600 (install.sh does) and the data directory off any sync folder.
- If `ROUTER_KEYS` is empty the router logs a warning at startup and accepts
  everything. That is fine on a trusted LAN, unacceptable on the internet.
- TLS is not handled here. Put nginx/Caddy in front for HTTPS and set
  `TRUST_PROXY=true` if you want `X-Forwarded-*` honoured.
- Path traversal and absolute URLs in the proxied path are rejected, so a caller
  cannot redirect the router at an arbitrary host.
- Hop-by-hop headers, the caller's `Authorization`, `Cookie` and router key are
  stripped before forwarding.
- `GET /docs` and `/openapi.json` are disabled whenever auth is enabled.

---

## Removing an install

`serpent uninstall` lists what the install created, asks whether to keep `data/` and
`.env`, removes the rest and verifies it (see the README). Keep them when you are only
changing how Serpent is deployed.

## Moving an install

`serpent move <dir|user@host:/path> [--with-env] [--with-data] [--move] [--dry-run]` copies the project, installs it at the destination, verifies it boots, and only then (with `--move`) removes the original. The virtualenv is rebuilt per machine, `.env` and `data/` are only carried with the flags above. Stop the service before `--with-data`.
