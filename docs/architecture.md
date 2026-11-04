# Architecture

```
src/serpent/
  main.py        app factory, routes, the per-provider reserve -> forward -> retry -> settle loop
  providers.py   providers, chains, presets, route resolution
  quota.py       periods, atomic reserve/settle, aggregates, snapshots
  accounts.py    account CRUD and upstream-health bookkeeping
  tunables.py    settings editable at runtime, persisted in SQLite
  upstream.py    URL/auth translation, path validation, header hygiene
  security.py    router keys, roles, constant-time compares
  config.py      environment settings, .env loader
  db.py          SQLite connection, WAL, transactions, schema + migrations
  cache.py, ratelimit.py, requestlog.py, metrics.py, dashboard.py
  cli.py         the `serpent` command (service control, accounts, providers, chains)
ui/              Snake Charmer (Vite + Svelte), built into src/serpent/ui_dist
```

## Request path

1. Authenticate (`client` role), rate-limit, validate the path and body size.
2. Resolve the route: `/p/{slug}` or the default route -> an ordered list of
   enabled providers (a provider is a one-element list, a chain has many).
3. Cache lookup (optional, keyed by route + path + query + body).
4. For each provider in order: reserve one credit from one of *its* accounts
   inside a `BEGIN IMMEDIATE` transaction, forward with that account's key,
   then settle. Failures refund per `REFUND_ON`, cool the account down and retry
   on another account of the same provider (up to `MAX_RETRIES`). When a provider
   is exhausted the next one in the chain is tried; the last failure is returned
   if all fail.
5. Responses carry `X-Quota-*`, `X-Router-Provider`, `X-Router-Account`,
   `X-Router-Attempts`.

## Data model (SQLite, WAL)

| Table | Purpose |
| --- | --- |
| `providers` | slug, base URL, auth style/name, enabled |
| `chains` | slug, ordered `steps` (provider slugs), enabled |
| `accounts` | provider, label, key, limit, status, cooldown, failure streak |
| `usage` | per account and period: used, in-flight, ok/failed/refunded, latency |
| `request_log` | capped ring of recent requests for the UI |
| `state` | small key/values: default route, round-robin cursor, tunables |

Migrations are additive and idempotent (`db._migrate`). Periods are keyed rows
(`account_id`, `YYYY-MM`), so rollover needs no scheduler.

## Decisions worth knowing

- **SQLite is the lock.** Atomicity of quota lives in the database, not process
  memory, so multiple workers/processes can share one file.
- **Providers are data, not code.** Anything that authenticates with a header,
  query parameter or bearer token works without a plugin.
- **Runtime vs environment config.** Operational knobs (strategy, retries, reserve)
  are editable live; deployment facts (bind address, DB path, router keys) stay in
  the environment so an install is reproducible.
- **No external UI assets.** Snake Charmer works on an offline LAN.
