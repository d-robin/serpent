# Workflows

Task-oriented recipes. Each shows the Snake Charmer way and the terminal way (the TUI offers
the same operations: run `./serpent` in a terminal).

- [Add a provider and an account](#add-a-provider-and-an-account)
- [Search from the UI](#search-from-the-ui)
- [Build an app on it, or have an AI build one](#build-an-app-on-it-or-have-an-ai-build-one)
- [See what calls were made](#see-what-calls-were-made)
- [Keep an eye on credits](#keep-an-eye-on-credits)
- [Add a second account, or a fallback](#add-a-second-account-or-a-fallback)
- [Recover or rotate keys](#recover-or-rotate-keys)
- [Survive a reboot](#survive-a-reboot)
- [Run it on another machine (move)](#run-it-on-another-machine-move)
- [Back up and restore](#back-up-and-restore)
- [Uninstall or redeploy differently](#uninstall-or-redeploy-differently)

## Add a provider and an account

1. **Providers → Add provider.** Pick a preset or enter a base URL and the auth style (key in
   a header, in a query parameter, or as a bearer token).
2. **Accounts → Add account.** Choose the provider, label it, paste its API key, set a credit
   limit per month.

```bash
serpent providers add serpapi --preset serpapi
serpent accounts add --provider serpapi --label main --limit 250
```

The key is stored once and shown only as a short hint afterwards.

## Search from the UI

**Search** tab: choose a kind (for SerpApi: Google, Amazon, Shopping, News, Images, Maps),
type, Enter. Results show title, site, snippet and, for shops, price and rating. **Options**
holds the route, the client key and, for providers without ready-made kinds, the method, path
and a body template where `{query}` is replaced by your words. **Raw response** is always one
click away. Each search is a real call and uses a credit.

## Build an app on it, or have an AI build one

An app needs the router address, a **client key**, and to know each provider's request format.
Serpent writes that last part down for you.

1. Open **Integrate** (or fetch `GET /v1/contract` with your client key). It describes every
   route that exists *now*: authentication, each provider's operations with example requests
   and result fields, response headers, error codes and rules (for example "wait for
   `Retry-After` on 429").
2. Copy the prompt from the Integrate tab into your AI assistant, or paste the contract text
   if the assistant cannot reach your machine (a router on `127.0.0.1` is invisible to cloud
   tools).
3. Give the finished app the client key through an environment variable, never through the
   chat or source code.

`GET /llms.txt` is a short open pointer that tells AI tools to read the contract first.
`?format=json` returns the same contract as JSON.

## See what calls were made

**Requests** tab: every call through the router, newest first, with method, path (including
the query so Google and Amazon calls are distinguishable), provider, account, result and
milliseconds. Filter by result, provider or text. It refreshes by itself while you watch.
The newest 500 calls are kept (`REQUEST_LOG_SIZE`). Bodies and responses are not recorded.

Terminal: `serpent log` for the server log (`-f` to follow).

## Keep an eye on credits

The **Accounts** page shows three things per account: **your limit** (what you allow through
Serpent), **used** (what Serpent has counted), and, for SerpApi, the **provider allowance**
(what the provider says the plan gives, fetched with a free call). If your remaining limit is
higher than what the provider has left, the row warns you. **Overview** shows the totals and
the reset date. Programmatic: `GET /v1/quota` and `POST /v1/quota/check {"count": 20}`.

## Add a second account, or a fallback

- **More accounts on the same provider:** add them in Accounts. Serpent spreads calls across
  them (strategy in Settings; the default sends to the account with most headroom). Read
  [Responsible use](responsible-use.md) first.
- **A different provider as backup:** add the provider, then **Chains → New chain** with the
  providers in order. Remember there is no translation: the same request goes to each step,
  so use providers with the same API shape, or call each provider's route yourself.
- **Make a route the default:** Chains page, or `serpent route set <slug>`. Apps using
  `/v1/…` follow it; apps using `/p/<slug>/…` do not move.

## Recover or rotate keys

```bash
serpent keys                     # router keys (masked) and provider keys (masked)
serpent keys --reveal            # full values; asks first in a terminal
serpent keys link                # the sign-in URL for Snake Charmer
serpent keys rotate admin        # new admin key (also: client, read); restart afterwards
```

Lost the admin key but have the machine? `serpent keys --reveal` reads it from `.env`. In the
terminal UI it is the **Keys & sign-in** screen. Provider keys can be recovered the same way
because they are stored in the database.

## Survive a reboot

`serpent up` runs a background process that does **not** come back after a reboot.

| Setup | What to do |
| --- | --- |
| Docker | `--restart unless-stopped`, which the `docker run` command in [Deploying](deploying.md#docker) already uses |
| Linux, systemd | `serpent systemd --out serpent.service`, then install it with the commands printed |
| macOS / other | run `./serpent up` after logging in (a launchd helper is not built yet) |

Your data and settings are untouched by a reboot; only the process needs restarting.

## Run it on another machine (move)

```bash
serpent move user@host:/opt/serpent --with-data --with-env --dry-run   # preview first; then drop --dry-run
```

Or by hand: copy the folder (or just `data/` and `.env`) to the new machine and run
`./serpent`. The new home picks its own port unless you set `BIND_PORT`.

## Back up and restore

Stop the server (or use SQLite's online backup, see [Deploying](deploying.md#backups)), then
copy `data/serpent.db` and `.env`. Restore by putting them back in a home folder and starting
it. Treat the backup like a password file: it contains your provider keys.

## Uninstall or redeploy differently

```bash
serpent uninstall            # shows exactly what it found, asks, removes, then verifies
```

It lists the server, logs, runtime files, the virtual environment it created, the generated
service file and the install record, and **asks whether to keep your data** (the default).
Keeping data lets you redeploy elsewhere (another folder, Docker, systemd) without re-entering
anything. Deleting needs `--delete-data` or typing `delete`. It never deletes the source
folder and never runs `sudo`; for system-level pieces it prints the command for you to run.
Use `--dry-run` to preview.
