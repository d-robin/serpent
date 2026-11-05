# Getting started

From nothing to your first search in about five minutes. You need Python 3.10 or newer
(macOS and most Linux already have it) and **an API key from a search provider** such as
SerpApi or Serper. Serpent comes with no provider built in; you choose one.

## 1. Start it

```bash
git clone https://github.com/d-robin/serpent.git
cd serpent
./serpent
```

The first run creates a private virtual environment, installs Serpent, generates your router
keys, starts the server in the background and opens Snake Charmer in your browser, already
signed in as admin. Nothing is installed outside this folder.

Prefer another way (Docker, pipx, systemd, a Raspberry Pi)? See [Install options in the
README](../README.md#install-options) and [Deploying](deploying.md).

## 2. Add a provider

In Snake Charmer open **Providers → Add provider** and pick a preset (SerpApi, Serper,
ScrapingDog, VALUE SERP, Brave) or enter any base URL and how it expects its key. The first
provider you add becomes the default route.

Terminal equivalent:

```bash
./serpent providers add serpapi --preset serpapi
```

## 3. Add an account (your provider key)

Open **Accounts → Add account**, choose the provider, give it a label, paste the key and set
how many credits you want to allow per month. The limit is **your** safety cap; the provider
has its own allowance (Serpent shows both side by side for SerpApi).

```bash
./serpent accounts add --provider serpapi --label main --limit 250   # asks for the key privately
```

You can add more accounts to the same provider later; Serpent shares calls across them. Read
[Responsible use](responsible-use.md) before doing that with accounts you do not own.

## 4. Run a search

Open the **Search** tab, pick a kind (for SerpApi: Google, Amazon, Shopping, News, Images,
Maps), type, and press Enter. You get readable results; **Raw response** shows exactly what
the provider sent. Check **Requests** to see the call that was made and **Accounts** to watch
the credit count move.

The same search from a terminal:

```bash
curl -H "X-Router-Key: $CLIENT_KEY" \
  "http://127.0.0.1:8971/p/serpapi/search?engine=google&q=coffee+shops+austin"
```

Your client key is in `.env` (`./serpent keys` shows it masked, `./serpent keys --reveal` in
full). The port is printed when Serpent starts; yours may differ if 8971 was taken.

## 5. Use it from your app

Give the app the router address and a **client key**. Never give it a provider key; Serpent
adds that. Then either read [Workflows → Build an app on it](workflows.md#build-an-app-on-it-or-have-an-ai-build-one)
or open the **Integrate** tab, which produces a prompt and a contract page for an AI assistant
to read.

## Everyday commands

| | |
| --- | --- |
| `./serpent` | open the terminal UI (first run: set up and start) |
| `./serpent up` | start, or show that it is already running, and print the sign-in link |
| `./serpent stop` · `status` · `log` | control and inspect |
| `./serpent keys` | show or recover keys · `keys link` · `keys rotate admin` |
| `./serpent --help` | everything else, even before anything is installed |
| `./serpent uninstall` | remove what the install created (asks what to do with your data) |

## If something looks wrong

- **"already running"**: one folder runs one server. It prints where, and the sign-in link.
- **Search returns 404 or 401**: 404 usually means the request shape does not match the
  provider (SerpApi is GET with the query in the URL; Serper is POST with a JSON body); 401
  means a missing or wrong router key. The Search tab's Raw response shows the details.
- **429**: no credits left or a rate limit; wait for `Retry-After`.
- **After a reboot it is not running**: see [Workflows → Survive a reboot](workflows.md#survive-a-reboot).

Next: [Architecture](architecture.md) to see how it works, or [Things to know](important-things.md).
