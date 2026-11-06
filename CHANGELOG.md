# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **A modern terminal UI**: tabs (`1`-`8`), a live Overview with a credits gauge and traffic
  sparkline, usage gauges on Accounts, live `/` filtering, a `:` command palette, mouse
  support, toasts and a 256-colour theme (ASCII fallback; honours `NO_COLOR`).
- **Manage** tab in the terminal UI: doctor, last fault, self-test, install details, rotation
  and retry settings, backup, reset usage, clear history, systemd unit, copy/move, and
  **uninstall** with the same plan, keep-data choice and verification as the CLI.
- `serpent backup`: online SQLite backup into `backups/` (private; uninstall treats it as data).
- **API contract**: `GET /v1/contract` (client key; Markdown or `?format=json`) is generated
  from the live setup and describes routes, auth, per-provider requests (SerpApi, Serper,
  Brave), response fields, headers, errors and rules; `GET /llms.txt` points AI tools to it.
  The **Integrate** tab copies a ready prompt or the contract text for an AI assistant.
- Documentation for people: an index, Getting started, a rewritten Architecture (diagrams),
  Workflows and Things to know.
- **Requests** tab: every call through the router, paged, with filters (result, provider,
  text), live refresh, and the query string (credential-like parameters are removed).
  API: `GET /admin/requests`.
- **Search types** for SerpApi (Google, Amazon, Shopping, News, Images, Maps) in the Search
  tab; Raw request starts as a GET for SerpApi. Shop results show price and rating.
- Accounts page shows the **provider's own allowance** next to your limit and usage, for
  SerpApi (`GET /admin/accounts/{id}/provider-usage`, free, never counted as usage).
- A **Search** tab in Snake Charmer: type a query, get readable results (title, site, snippet)
  from whatever the provider returns, with the raw response one click away. The request
  shape (method, path, body template) is under Options and remembered. The old Try it tab
  is now "Raw request".
- One entry point, `./serpent`: the first run sets up, starts and opens the web UI;
  afterwards it opens the terminal UI. It also serves `--help` before anything is installed,
  and `./serpent dev` for UI work. Replaces `install.sh`, `ctl.sh` and `serve.sh`.
- Providers and fallback chains: accounts belong to a provider, `/p/{slug}/*`
  routes to a provider or chain, `/v1/*` follows the configurable default route.
- Provider presets: Serper, SerpApi, ScrapingDog, VALUE SERP, Brave Search.
- Runtime tunables (strategy, retries, reserve, cooldowns, refund kinds, timeout).
- Snake Charmer web UI served at `/ui`.
- Unified `serpent` command line.
- Responsible-use guidance (`docs/responsible-use.md`) with warnings in Snake Charmer
  and the CLI when several accounts share a provider.

- `serpent uninstall`: inventories the install, asks whether to keep your data, removes
  what the installer created and verifies the result (`--dry-run`, `--yes`, `--keep-data`,
  `--delete-data`). The installer records what it created.

- `serpent tui`: full-screen terminal UI with arrow-key navigation for providers, accounts,
  chains, keys, requests, logs and server control; opens when you run `serpent` in a terminal.
- `serpent keys`: show or recover router keys (from `.env`) and provider keys (from the
  database), print the signed-in Snake Charmer link, and rotate a router key.

### Changed
- The database (which holds provider API keys) and its -wal/-shm files, and `data/`, are
  now created owner-only (0600/0700); existing installs are tightened on the next start.
- Each install remembers its port and reuses it; `serpent start` on a running install
  refuses (exit 1) and prints its URL, pid and folder, `serpent up` prints the same and
  exits 0; a busy port is reported with who holds it.
- No provider is preconfigured any more. A fresh install starts empty; the first provider
  you add becomes the default route, and `/v1/*` answers 503 with instructions until then.
  `UPSTREAM_BASE_URL` still works to adopt an older single-upstream setup.
- Project renamed from "SERP Router" to Serpent; Python package is `serpent`
  (`serpent-router` on PyPI); Prometheus metrics are prefixed `serpent_`.

## 1.0.0
- Initial private release as "SERP Router": quota ledger, rotation strategies,
  failover, dashboard.
