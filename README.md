<p align="center">
  <img src="branding/banner.svg" alt="SerpEnt - one key, many SERP accounts" width="720">
</p>

<p align="center">
  <a href="https://github.com/d-robin/serpent/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/d-robin/serpent/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue.svg"></a>
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue.svg">
</p>

# SerpEnt

**One key in front, many SERP accounts behind.** Serpent is a small, quota-aware
gateway for search-results APIs (Serper, SerpApi, ScrapingDog, VALUE SERP, Brave,
or any HTTP API with a key). Your apps hold a single Serpent key; Serpent picks an
account, injects that account's key, retries elsewhere on failure and keeps a
durable ledger of every credit spent.

```
your app ──► /p/serpapi/… ──►            ──► SerpApi  (account 1, account 2, …)
            one router key    Serpent
your app ──► /p/serper/…  ──►  rotation  ──► Serper   (account 1, …)
                               + ledger
                                  │
                                  └──► Snake Charmer UI · quota API · contract · metrics
```

- **Pool free tiers.** Spread traffic over many accounts and never exceed a limit,
  even across workers (credits are reserved in SQLite transactions).
- **Providers and fallback chains.** Several providers side by side, each with its own
  accounts; a chain falls through to the next step when one is dry or failing. Serpent
  passes requests through unchanged (it does not translate between providers), so each route
  speaks one provider's API.
- **Built for AI-assisted development.** `GET /v1/contract` describes how to call your
  router, generated from your live setup; the Integrate tab hands it to an AI assistant.
- **Snake Charmer.** A designed, keyboard-friendly web UI (light and dark, command palette)
  to search, watch traffic, manage providers, accounts and chains, and tune rotation.
  Bundled, offline, no CDN.
- **Boring to run.** Three Python dependencies, one SQLite file, about 60 MB RSS.
  Runs on a Raspberry Pi, in Docker, or under systemd.
- **Safe by default.** Provider keys never leave the server, loopback bind, role
  based router keys, path-traversal and header hygiene on the proxy.

## Get started in one command

```bash
git clone https://github.com/d-robin/serpent && cd serpent && ./serpent
```

That's it. `./serpent` is the one entry point: the first run sets everything up, starts
Serpent, and **opens Snake Charmer
(the web UI) in your browser, already signed in**. Then, in the UI:

1. **Providers**: no provider is built in. Pick yours from a preset (Serper, SerpApi,
   ScrapingDog, VALUE SERP, Brave) or enter its URL.
2. **Accounts**: paste your provider API key(s).
3. **Search**: type a query in the Search tab and watch the quota drop.
4. **Use it**: point your app at `http://127.0.0.1:8971/v1/search` with your *client*
   key (it was printed once and lives in `.env`).

```bash
curl -X POST http://127.0.0.1:8971/v1/search \
  -H "X-Router-Key: $CLIENT_KEY" -H 'Content-Type: application/json' \
  -d '{"q":"coffee shops austin","num":10}'
```

Prefer the terminal? Every step has a command, and `serpent up` prints the same
instructions as this section:

```bash
.venv/bin/serpent up                    # start (or resume) and open the UI; safe to repeat
.venv/bin/serpent providers add serper --preset serper
.venv/bin/serpent accounts add --provider serper --label serper-1 --limit 2500
.venv/bin/serpent status | stop | log -f | health
.venv/bin/serpent --help
```

Docker: `docker build -t serpent . && docker run -d --restart unless-stopped -p 8971:8971 -v serpent-data:/data serpent`.
No provider key yet? `scripts/demo.sh` runs a throwaway instance with a fake provider.

> Serpent listens on `127.0.0.1` only, so nothing is exposed until you choose
> (`serpent up --host 0.0.0.0`). Before you do, read [SECURITY.md](SECURITY.md).

## Install options

| Way | Command | Good for |
| --- | --- | --- |
| **One command** (recommended) | `git clone https://github.com/d-robin/serpent && cd serpent && ./serpent` | Trying it, a laptop, a Raspberry Pi |
| **By hand** | `python3 -m venv .venv && .venv/bin/pip install -e . && .venv/bin/serpent up` | You want to see every step |
| **Docker** | `docker build -t serpent . && docker run -d --restart unless-stopped -p 8971:8971 -v serpent-data:/data serpent` | Servers, no Python on the host |
| **systemd service** | `serpent systemd --out serpent.service`, then copy it to `/etc/systemd/system/` | Starting at boot (see [Deploying](docs/deploying.md)) |
| **Move to another machine** | `serpent move user@host:/path` | Redeploying with your data |
| `pip install serpent-router` | not published yet | coming once it is on PyPI |

All of them end the same way: open Snake Charmer at `/ui/` and add your provider.
`serpent uninstall` reverses the first two (see below).

## One install, one port

Each install (folder) remembers its own port, starting from 8971. Starting the same
install twice does not launch a second copy: it says so and prints that install's URL,
pid, folder and log. Start Serpent from another folder and it takes the next free port,
telling you who holds the one it skipped. Stopping and restarting never swaps ports.

## Terminal UI and recovering keys

```bash
./serpent            # in a terminal: opens the full-screen UI (same as `serpent tui`)
```

A tabbed dashboard: a live Overview (server, credits gauge, traffic sparkline), Providers,
Accounts (with usage gauges), Chains, Keys, Requests, Logs, and **Manage** (diagnostics,
settings, backups, systemd, move, and uninstall). Jump with `1`-`8` or `Tab`, move with the
arrow keys, `Enter` to act, `/` to filter as you type, `:` for a command palette, `?` for all
keys; the mouse works too. It changes the same data as Snake Charmer. Needs `curses`
(macOS, Linux, Raspberry Pi; not Windows). Details: [docs/tui.md](docs/tui.md).

Lost a key? Router keys are in `.env`, provider keys in the database. You can read them back:

```bash
serpent keys                 # masked list of every key
serpent keys --reveal        # full values (asks first in a terminal)
serpent keys link            # Snake Charmer URL that signs you in as admin
serpent keys rotate admin    # make a new router key (admin, client or read), then restart
```

## After a reboot

`./serpent` and `serpent up` start Serpent as a background process. It **does not
come back by itself** after a reboot or logout. Your data is safe; start it again with:

```bash
cd serpent && .venv/bin/serpent up
```

Want it running at boot?

| Where | How |
| --- | --- |
| **Linux / Raspberry Pi** | systemd: `serpent systemd --out serpent.service`, then the three `sudo` lines in [Deploying](docs/deploying.md) |
| **Docker** | already covered: the install table command uses `--restart unless-stopped` |
| **macOS** | no built-in helper yet: run `serpent up` after login, or add it as a Login Item / launchd job pointing at `.venv/bin/serpent up --no-open` |

## Uninstall, or change how it is deployed

```bash
.venv/bin/serpent uninstall            # shows what it found, asks before changing anything
```

It looks at what is actually on disk (the running server, `.venv`, logs, runtime files,
your data), shows a plan, then **asks whether to keep your data** (the database with
accounts and provider keys, plus `.env`). Keeping it is the default, so you can redeploy
another way (another folder, Docker, systemd) and pick up where you left off. When it
finishes it checks each item again and reports what was removed, kept, or still needs you.
It never deletes the source folder and never runs `sudo`; for a systemd service or a
`pip`/`pipx` install it prints the exact command to run. Options: `--dry-run`, `--yes`,
`--keep-data`, `--delete-data`.

## Documentation

| | |
| --- | --- |
| [Getting started](docs/getting-started.md) | zero to your first search |
| [Connect apps and agents](docs/connecting.md) | routes, keys, curl/Python/Node examples, errors, AI agent tool use |
| [Run and operate](docs/operations.md) | start, stop, ports, logs, health, backups, upgrades |
| [Troubleshooting](docs/troubleshooting.md) | symptom to fix, and what to collect for a bug report |
| [Command reference](docs/cli.md) | every `serpent` command |
| [Architecture](docs/architecture.md) | the pieces, what happens to a request, data and security model |
| [Terminal UI](docs/tui.md) | launching it, every key, every screen, what Manage can do |
| [Workflows](docs/workflows.md) | add accounts, build an app (or have an AI), survive reboots, move, back up, uninstall |
| [Things to know](docs/important-things.md) | credits, key storage, no translation, exposure, limits |
| [Reference](docs/reference.md) | request lifecycle, quota model, rotation, failure policy, API, every setting |
| [Responsible use](docs/responsible-use.md) | read before pooling accounts with one provider |
| [Deploying](docs/deploying.md) | systemd, Docker, Raspberry Pi, TLS, backups, moving an install |
| [Snake Charmer](ui/README.md) | the UI: development and build |
| [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Changelog](CHANGELOG.md) | |

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/ruff check src tests
cd ui && npm ci && npm run build      # builds into src/serpent/ui_dist
```

## Responsible use

Pooling **several accounts with the same provider** may break that provider's terms,
and can get the accounts suspended. Serpent warns you in the UI and CLI but cannot
check for you. Read [docs/responsible-use.md](docs/responsible-use.md) before you add a
second account to a provider. Fallback chains across *different* providers carry no
such risk.

## Status and limits

Serpent is young. Honest edges: provider keys are stored in plain text in SQLite
(protect the file; encryption at rest is on the roadmap), there are no per-client
budgets yet, the response cache is per process, and TLS is left to your reverse
proxy. See [SECURITY.md](SECURITY.md) before exposing it to the internet.

## License

[Apache-2.0](LICENSE). You may use, modify and redistribute Serpent for personal
or commercial work; redistributions must keep the license text and the
[NOTICE](NOTICE) attribution to the original project.
