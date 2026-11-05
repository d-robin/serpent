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
your app ──► /v1/search ──►  Serpent  ──► chain "web":  serper account 1 (250/mo)
            (one key)        rotation +                  serper account 2 (250/mo)
                             quota ledger   ──fallback──► serpapi account 1 (100/mo)
                                  │
                                  └──► Snake Charmer UI · quota API · Prometheus metrics
```

- **Pool free tiers.** Spread traffic over many accounts and never exceed a limit,
  even across workers (credits are reserved in SQLite transactions).
- **Providers and fallback chains.** Mix providers; when one is dry or failing,
  the next takes over.
- **Snake Charmer.** A web UI to add providers and accounts, build chains, tune
  rotation and try requests. Bundled, offline, no CDN.
- **Boring to run.** Three Python dependencies, one SQLite file, about 60 MB RSS.
  Runs on a Raspberry Pi, in Docker, or under systemd.
- **Safe by default.** Provider keys never leave the server, loopback bind, role
  based router keys, path-traversal and header hygiene on the proxy.

## Get started in one command

```bash
git clone https://github.com/d-robin/serpent && cd serpent && ./install.sh
```

That's it. `install.sh` sets everything up, starts Serpent, and **opens Snake Charmer
(the web UI) in your browser, already signed in**. Then, in the UI:

1. **Providers**: no provider is built in. Pick yours from a preset (Serper, SerpApi,
   ScrapingDog, VALUE SERP, Brave) or enter its URL.
2. **Accounts**: paste your provider API key(s).
3. **Try it**: send a test search and watch the quota drop.
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
| **One command** (recommended) | `git clone https://github.com/d-robin/serpent && cd serpent && ./install.sh` | Trying it, a laptop, a Raspberry Pi |
| **By hand** | `python3 -m venv .venv && .venv/bin/pip install -e . && .venv/bin/serpent up` | You want to see every step |
| **Docker** | `docker build -t serpent . && docker run -d --restart unless-stopped -p 8971:8971 -v serpent-data:/data serpent` | Servers, no Python on the host |
| **systemd service** | `serpent systemd --out serpent.service`, then copy it to `/etc/systemd/system/` | Starting at boot (see [Deploying](docs/deploying.md)) |
| **Move to another machine** | `serpent move user@host:/path` | Redeploying with your data |
| `pip install serpent-router` | not published yet | coming once it is on PyPI |

All of them end the same way: open Snake Charmer at `/ui/` and add your provider.
`serpent uninstall` reverses the first two (see below).

## After a reboot

`./install.sh` and `serpent up` start Serpent as a background process. It **does not
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
| [Reference](docs/reference.md) | request lifecycle, quota model, rotation, failure policy, API, every setting |
| [Architecture](docs/architecture.md) | modules, data model, design decisions |
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
