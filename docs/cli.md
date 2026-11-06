# Command reference

`./serpent` (the launcher in the repo root) runs `.venv/bin/serpent`. Everything below also works
as `serpent <command>` once it is on your PATH. `serpent <command> --help` shows the options of
one command, and `serpent --home /path …` (or `SERPENT_HOME`) operates another install.

## Start here

| Command | Does |
| --- | --- |
| `./serpent` | first run: set up, start, open the web UI; afterwards in a terminal: the [terminal UI](tui.md) |
| `./serpent --help` | every command (works before anything is installed) |
| `./serpent install` | set up only (virtual environment, package, keys) |
| `./serpent dev` | router plus Vite hot reload for UI work (needs Node.js) |

## Run it

| Command | Does |
| --- | --- |
| `up [--port N] [--host H] [--no-open]` | start (or report it is running) and print the sign-in link; opens the browser |
| `start [--port] [--host] [--workers] [--wait]` | start in the background; refuses if this install is already running |
| `stop` | stop the background server |
| `restart` | stop, then start |
| `run [--port] [--host]` | run in the foreground (log in your terminal) |
| `tui` | the full-screen terminal UI (also the default in a terminal) |

## Inspect and diagnose

| Command | Does |
| --- | --- |
| `status [--json]` | pid, URL, uptime, memory, accounts, log path, last fault |
| `health [-q] [--json] [--strict]` | liveness, readiness, database, disk, faults |
| `doctor [-q] [--json] [--strict]` | health plus environment checks |
| `log [-n N] [-f]` (alias `logs`) | tail `logs/router.log` |
| `fault [-a]` (alias `faults`) | the last start/stop problem, or all |
| `verify [-q]` | boot a scratch copy on a throwaway database and check the endpoints |
| `requests [-n N] [--json]` | recent proxied requests |
| `version [--json]` | version and paths |

## Configure

| Command | Does |
| --- | --- |
| `providers list \| presets \| add \| enable \| disable \| remove` | manage providers. `add <slug> --preset serpapi` or `--base-url URL --auth-style header\|query\|bearer [--auth-header-name H] [--auth-param-name P]` |
| `accounts list \| add \| enable \| disable \| remove \| reset \| move` | manage keys. `add --provider SLUG --label NAME --limit N [--key K]` (key is prompted for privately if omitted); `move ID --provider SLUG`; `reset ID` zeroes this period |
| `chains list \| add \| enable \| disable \| remove` | fallback chains. `add <slug> <provider> <provider> … [--name N]` |
| `route show \| set <slug>` | show or set the default route used by `/v1/*` |
| `seed` | import `SERP_ACCOUNTS` from the environment (a one-shot migration helper) |

## Keys

| Command | Does |
| --- | --- |
| `keys [--reveal] [--json]` | list router and provider keys (masked unless `--reveal`) |
| `keys link` | print the Snake Charmer sign-in URL for the admin |
| `keys rotate admin\|client\|read [--yes]` | make a new router key; restart afterwards |

## Data and deployment

| Command | Does |
| --- | --- |
| `init [--force] [--json]` | create `.env` with generated keys and the database (`--force` regenerates keys) |
| `backup` | online copy of the database into `backups/` |
| `systemd [--out FILE] [--install] [--user U] [--host H] [--port N]` | print or write a unit with this machine's real paths; `--install` prints the `sudo` steps |
| `move <dir \| user@host:/path> [--copy \| --move] [--with-env] [--with-data] [--dry-run] [--no-verify] [--force] [-y]` | copy or move this install; installs at the destination and verifies it boots |
| `uninstall [--keep-data \| --delete-data] [--yes] [--dry-run]` | remove what the install created, asking about your data, then verify |

## Exit codes and scripting

Commands exit `0` on success and non-zero on failure, so they work in scripts. `--json` (where
offered) prints machine-readable output; `health --strict` and `doctor --strict` also fail on
warnings, which suits a CI or cron check. `uninstall` needs `--yes` (and `--keep-data` or
`--delete-data`) outside a terminal, or `--dry-run` to preview.
