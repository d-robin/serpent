# Things to know

The points that most often surprise people. Short, with the reason and what to do.

## Serpent does not translate between providers

`/p/serpapi/search?engine=amazon&k=…` and Serper's `POST /search {"q": …}` are different APIs,
and Serpent forwards each exactly as sent. A request shaped for one provider will fail at
another. Consequences:

- Your app must send each route the format that provider documents. The **contract**
  (`/v1/contract`, Integrate tab) writes those formats down for the providers Serpent knows.
- A **chain** sends the same request to every step. Use chains of one provider type (several
  accounts of one provider are already pooled automatically, without a chain), or accept that
  a fallback step with a different API will fail.
- Responses are the provider's own JSON, unchanged. The Search tab's friendly results are a
  display convenience in the browser, not something the router does for your app.

## Every call spends a credit

Any request to a provider route counts as one credit, including searches with no results.
Failures that never produced a result (connection errors, 5xx, 429, 401) are refunded by
default (`REFUND_ON`); other 4xx errors are **not**, because providers usually bill for them
(you sent a bad request, but they still processed it). The Search and Raw request tabs spend
real credits too.

## Your limit is not the provider's limit

Each account has a limit **you** set (default 250 a month). The provider has its own
allowance. Serpent enforces yours and, for SerpApi, shows the provider's next to it. If you set
a higher limit than the plan has, the provider will start refusing before Serpent does. Keep
yours at or below the real one. Credits reset on the 1st of the month (UTC) unless you change
`QUOTA_RESET_DAY`; the provider's reset date may differ.

## Where your provider keys are stored

In the SQLite database, as **plain text**, in a file only your user can read
(`data/serpent.db` is mode 0600 in a 0700 folder). They are never returned by the API or shown
in full by the UI; you can recover them with `serpent keys --reveal` because the server must be
able to use them. Encryption at rest is not implemented. What this means in practice:

- Treat the database file, and any backup of it, like a password file.
- Keep the install on a machine and user account you trust; use full-disk encryption on laptops.
- Do not commit `.env` or `data/` anywhere (the repository's `.gitignore` already excludes them).
- To change a provider key, create the new one in the provider's dashboard, then either
  `PATCH /admin/accounts/<id>` with `{"api_key": "…"}` (keeps the account's counters) or remove
  the account and add it again.

## Router keys, roles and the sign-in link

- `serpent init` generates three router keys in `.env`: **admin**, **client** and **read**.
  Apps get the **client** key. Only people who manage Serpent need the admin key.
- If `ROUTER_KEYS` is empty there is **no authentication**. A normal install never has that;
  Snake Charmer shows a warning banner if it happens.
- The sign-in link from `serpent up` (`/ui/#key=…`) contains the admin key. The part after `#`
  is not sent to servers and the page removes it from the address bar, but anyone who sees the
  link (chat, screen share, shell history) has admin access. Rotate with `serpent keys rotate
  admin` if it leaks.
- The browser keeps your key in session storage only; closing the tab signs you out.

## Network exposure

A fresh install listens on `127.0.0.1`, reachable only from the same computer. To let other
machines use it, set `BIND_HOST` deliberately and put TLS (a reverse proxy) in front; the keys
travel in headers. The auto-generated `/docs` and `/openapi.json` pages are disabled whenever
authentication is on. A router on `127.0.0.1` cannot be reached by cloud AI tools; paste the
contract text instead.

## One install, one port, one process

Each home folder runs one server and remembers its port (starting at 8971, moving up if
busy). Starting it again says it is already running and prints where. A second folder gets
another port. Two installs sharing one database file is not supported.

## It does not start by itself after a reboot

`serpent up` is a background process. Docker (`--restart unless-stopped`) and systemd
(`serpent systemd`) restart it; on macOS run `./serpent up` after login for now. Your data
survives; only the process needs starting. See [Workflows → Survive a reboot](workflows.md#survive-a-reboot).

## History and logging

The request log keeps the newest 500 calls (method, path and query, provider, account label,
status, timing). Query parameters whose names look like credentials (`key`, `token`, `secret`,
`auth`, `pass`, `sig`) are dropped. Request bodies and responses are never stored. Search
words appear in the log when they are in the query string (SerpApi), not when they are in a
POST body (Serper).

## Caching is off by default

`CACHE_TTL_SECONDS` above zero makes identical requests return a stored answer for free
(marked `X-Cache: HIT`). It saves the most credits but means results can be that many seconds
old, so it is your choice.

## Several accounts with one provider

Pooling accounts to get around a provider's free-tier limits may break its terms and can get
accounts suspended. Serpent cannot check this for you and asks you to confirm when you add a
second account. Read [Responsible use](responsible-use.md).

## Provider details can change

The provider presets and the per-provider examples in the contract come from public
documentation and are starting points. Providers rename parameters and change plans. When a
call stops working, compare with the provider's current docs; the Search tab's **Raw
response** shows what the provider actually said.

## What it does not do (yet)

- Translate one provider's request or response format into another's.
- Encrypt provider keys at rest.
- Start at boot on macOS (a launchd helper is not built).
- Look up plan allowances for providers other than SerpApi.
- Provide an OpenAPI document for the provider routes (the Markdown/JSON contract exists).
