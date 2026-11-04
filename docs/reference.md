# Reference

How Serpent works, its HTTP API and every setting. For setup see the
[README](../README.md).

## Providers, chains and routes

A **provider** is one upstream SERP API (base URL + how the key is attached). Every
account belongs to exactly one provider. A **chain** is an ordered list of
providers: Serpent tries the first, and when it is out of credits, failing or
cooling down it moves to the next.

| Route | Goes to |
| --- | --- |
| `/v1/*` | the **default route** (a provider or chain; `default` out of the box, built from `UPSTREAM_BASE_URL`) |
| `/p/{slug}/*` | the provider or chain called `slug` |

Responses carry `X-Router-Provider` (which provider answered) next to
`X-Router-Account`. Switch the default route from Snake Charmer, `serpent route set`
or `PUT /admin/default-route`.

Built-in presets (`GET /admin/presets`, `serpent providers presets`): Serper,
SerpApi, ScrapingDog, VALUE SERP, Brave Search. Presets are starting points; check
the provider's current docs.

## How it works

### Request lifecycle

Every proxied request goes through a reserve → forward → settle cycle:

1. **Reserve** — inside one `BEGIN IMMEDIATE` SQLite transaction, pick a
   healthy account with a credit left and increment its counter. Concurrent
   callers can therefore never overshoot a limit, even across multiple uvicorn
   workers or processes. (Verified: 300 racing requests against a 250-credit
   account produced exactly 250 × `200` and 50 × `429`, with `in_flight`
   returning to 0.)
2. **Forward** — the caller's method, path, query and body are replayed against
   `UPSTREAM_BASE_URL` with the account's key attached. Your provider keys are
   never visible to callers, and the caller's router key is never forwarded.
3. **Settle** — success consumes the credit; a failure releases it and applies a
   cooldown depending on the cause (see below).

If an account fails in a way that is not the caller's fault, the router retries
with a *different* account, up to `MAX_RETRIES` extra attempts. The response
tells you what happened in `X-Router-Attempts`.

### Quota model

Each account gets `quota_limit` credits (default 250) per **period**. The period
is a calendar month in UTC, or any day-of-month you like via `QUOTA_RESET_DAY`.
No cron job is involved: quota rows are keyed by `(account_id, YYYY-MM)`, so the
first request after a rollover simply creates a fresh row with `used = 0`.

Two different numbers are reported, and the difference matters:

| Field | Meaning |
| --- | --- |
| `quota_remaining_total` | credits not yet consumed — raw accounting |
| `quota_available_total` | credits you can **spend right now**: only active accounts, not cooling down, above the reserve floor |

`quota_available_total` is what gates requests and what `/v1/quota?need=N`
tests against, so a batch of 50 is never approved on the strength of credits
sitting on an invalid key.

Set `QUOTA_RESERVE=5` to keep 5 credits per account permanently unspent — handy
so you never hit zero while debugging.

### Rotation strategies

| `STRATEGY` | Behaviour | Use when |
| --- | --- | --- |
| `most_remaining` *(default)* | Picks the account with the most headroom, ties broken by in-flight count then least-recently-used | You want maximum total availability and even burn-down |
| `round_robin` | Strict rotation via a persisted cursor | Predictable, easy to reason about |
| `least_in_flight` | Fewest concurrent requests first | Spread latency under load |
| `least_recently_used` | Oldest `last_used_at` first | Avoid idling accounts |
| `fill_first` | Lowest account id until dry | Burn trial credits in order |
| `random` | Uniform choice | Quick and dirty spread |

`most_remaining` deliberately leaves smaller plans untouched until the big ones
are drained, which keeps them as a reserve.

### Failure policy

| Upstream result | Credit | Account state | Retry? |
| --- | --- | --- | --- |
| `2xx` | consumed | failures reset, cooldown cleared | — |
| `401` / `403` | refunded | `status=invalid` (needs an operator to re-enable) | yes, next account |
| `429` | refunded | cooldown, exponential from `COOLDOWN_BASE_SECONDS` | yes, next account |
| `5xx` | refunded | cooldown, exponential | yes, next account |
| connection error / timeout | refunded | cooldown, exponential | yes, next account |
| other `4xx` | **consumed** | untouched | no — the caller's request is at fault |

Refunds are controlled by `REFUND_ON` (default `connect,5xx,429,401`). The
distinction exists because most providers bill for some errors and not others;
this default is the conservative-but-recoverable choice.

If every attempt fails, the caller gets the last upstream response with
`X-Router-Error: all_accounts_failed`, or a `502` if the host was unreachable.
When there is simply nothing left to spend, the router returns `429` with a
`Retry-After` pointing at the period rollover.

### Optional cache

`CACHE_TTL_SECONDS=300` makes an identical `GET`/`POST` (same path, query and
body) return the stored answer without touching quota. This is the single
biggest quota saver in practice, and it is off by default so behaviour stays
predictable. Cached responses carry `X-Cache: HIT`.

---

## Calling the proxy

Anything under `/v1/` is forwarded; the prefix is stripped.

```
POST /v1/search   ->   https://google.serper.dev/search
GET  /v1/news     ->   https://google.serper.dev/news
```

Point it at another provider with two environment variables:

| Provider | `UPSTREAM_BASE_URL` | `AUTH_STYLE` |
| --- | --- | --- |
| Serper | `https://google.serper.dev` | `header`, `AUTH_HEADER_NAME=X-API-KEY` |
| SerpApi | `https://serpapi.com` | `query`, `AUTH_PARAM_NAME=api_key` |
| ScrapingDog | `https://api.scrapingdog.com` | `query`, `AUTH_PARAM_NAME=api_key` |
| Valueserp | `https://api.valueserp.com` | `query`, `AUTH_PARAM_NAME=api_key` |
| Anything with a bearer token | `https://…` | `bearer` |

Response headers added to every proxied reply:

```
X-Quota-Limit: 750          total credits this period
X-Quota-Used: 12
X-Quota-Remaining: 738      credits not consumed
X-Quota-Available: 738      credits spendable right now
X-Quota-Accounts: 3         usable accounts
X-Quota-Period: 2026-11
X-Quota-Reset: 2026-12-01T00:00:00+00:00
X-Quota-Reset-In: 2419200
X-Router-Attempts: 1
X-Router-Account: acme-1    (hide with EXPOSE_ACCOUNT_LABEL=false)
X-Request-Id: 4b2beb5655fc (echoed back if you send one)
```

---

## Quota API

All of these need at least a `read` key (a `client` key also works).

| Endpoint | Purpose |
| --- | --- |
| `GET /v1/quota` | Aggregate snapshot: totals, account counts, reset time |
| `GET /v1/quota?need=50` | Same, plus `allowed: true/false`; returns **409** if you cannot afford 50 |
| `POST /v1/quota/check` `{"count":50}` | Same check for POST-shaped clients |
| `GET /v1/quota/accounts` | Per-account breakdown with masked keys |
| `GET /v1/status` | Full status payload (dashboard data as JSON) |
| `GET /readyz` | `200` when at least one credit is spendable, else `503` |
| `GET /healthz` | Liveness only, always `200` |
| `GET /metrics` | Prometheus text exposition |

```jsonc
// GET /v1/quota
{
  "period": "2026-11",
  "accounts_total": 3,
  "accounts_active": 3,
  "accounts_usable": 3,
  "quota_limit_total": 750,
  "quota_used_total": 12,
  "quota_remaining_total": 738,
  "quota_available_total": 738,
  "in_flight": 0,
  "resets_at": "2026-12-01T00:00:00+00:00",
  "resets_in_seconds": 2419200,
  "can_serve": true
}
```

`/readyz` vs `/healthz` is a deliberate split: liveness stays `200` while the
process is up (so systemd does not restart it in a loop), readiness drops to
`503` when the pool is dry (so a load balancer or your own code can stop
sending work).

---

## Admin API and CLI

Mutations require an `admin` key.

| Endpoint | Purpose |
| --- | --- |
| `GET /admin/accounts` | Accounts with live quota |
| `POST /admin/accounts` | `{"label","api_key","quota_limit","notes"}` |
| `PATCH /admin/accounts/{id}` | `{"status":"active\|disabled","quota_limit","label","api_key","notes"}` |
| `DELETE /admin/accounts/{id}` | Remove (also drops its usage rows) |
| `POST /admin/accounts/{id}/reset` | Zero this period's counter |
| `POST /admin/reset` | Zero every account and clear all cooldowns |
| `POST /admin/cache/clear` | Drop the cached responses |
| `GET /admin/config` | Effective non-secret configuration |
| `GET /admin/health-check` | Is the upstream host reachable? (costs no credit) |

A `PATCH` to `status: active` re-enables an `invalid` account and clears its
cooldown and failure streak.

The CLI wraps the same operations without curl:

```bash
serpent accounts add --provider serper --label acme-3 --key sk-xxxx --limit 250
serpent accounts list
serpent accounts disable 2
serpent accounts reset 2
serpent status | jq .quota_available_total
serpent requests -n 20
serpent seed --from-env      # import SERP_ACCOUNTS=label:key,label:key
```

---

## Configuration

Everything is an environment variable; `.env` is read from the project root.
See `.env.example` for the annotated version.

| Variable | Default | Notes |
| --- | --- | --- |
| `BIND_HOST` / `BIND_PORT` | `0.0.0.0` / `8971` | `serpent start` begins here and walks upward until one is free |
| `LOG_LEVEL` | `info` | JSON lines to stdout |
| `DB_PATH` | `./data/serpent.db` | Single file + `-wal`/`-shm` |
| `UPSTREAM_BASE_URL` | `https://google.serper.dev` | No trailing slash |
| `UPSTREAM_TIMEOUT` | `30` | Seconds |
| `UPSTREAM_VERIFY_TLS` | `true` | |
| `AUTH_STYLE` | `header` | `header` \| `query` \| `bearer` |
| `AUTH_HEADER_NAME` | `X-API-KEY` | Used when style is `header` |
| `AUTH_PARAM_NAME` | `api_key` | Used when style is `query` |
| `ROUTE_PREFIX` | `/v1` | Stripped before forwarding |
| `MAX_BODY_BYTES` | `1048576` | Inbound body cap |
| `DEFAULT_QUOTA_LIMIT` | `250` | For newly added accounts |
| `QUOTA_RESET_DAY` | `1` | 1–28, UTC |
| `QUOTA_RESERVE` | `0` | Credits withheld per account |
| `STRATEGY` | `most_remaining` | See the table above |
| `MAX_RETRIES` | `2` | Extra accounts to try |
| `REFUND_ON` | `connect,5xx,429,401` | Failure kinds that give the credit back |
| `COOLDOWN_BASE_SECONDS` | `10` | Doubles per consecutive failure |
| `COOLDOWN_MAX_SECONDS` | `300` | Cap |
| `ROUTER_KEYS` | *(empty)* | `key:role,key:role`; empty = **no auth** |
| `ROUTER_KEY_HEADER` | `X-Router-Key` | `Authorization: Bearer` also accepted |
| `DASHBOARD_PUBLIC` | `true` | |
| `EXPOSE_ACCOUNT_LABEL` | `true` | Send `X-Router-Account` upstream-response-side |
| `CACHE_TTL_SECONDS` | `0` | `0` disables the cache |
| `CACHE_MAX_ENTRIES` | `512` | LRU bound |
| `RATE_LIMIT_PER_MINUTE` | `0` | Global token bucket; `0` disables |
| `RATE_LIMIT_BURST` | `0` | Defaults to one minute of budget |
| `REQUEST_LOG_SIZE` | `500` | Rows kept for the dashboard |
| `SERP_ACCOUNTS` | *(empty)* | One-shot seed, `label:key,label:key` |

Roles are `admin` > `client` > `read`. A key with no `:role` suffix is a
`client`.


### Admin endpoints added with providers

| Endpoint | Purpose |
| --- | --- |
| `GET /admin/presets` | provider presets and rotation strategies |
| `GET /admin/providers` | providers, chains, default route |
| `POST /admin/providers` | `{"slug","preset"}` or `{"slug","base_url","auth_style",...}` |
| `PATCH /admin/providers/{slug}` | edit / enable / disable |
| `DELETE /admin/providers/{slug}` | refused while accounts or chains use it |
| `POST /admin/chains`, `PATCH`, `DELETE /admin/chains/{slug}` | `{"slug","steps":["a","b"]}` |
| `PUT /admin/default-route` | `{"route":"slug"}` |
| `GET` / `PATCH /admin/tunables` | strategy, retries, reserve, cooldowns, refund kinds, timeout (persisted in SQLite) |
