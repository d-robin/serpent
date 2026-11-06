# Connect apps and agents

Everything an application, script or AI agent needs to call Serpent safely. The short
version: send a **client key** to `/p/<provider>/…` and handle `429`.

> Serpent writes this down for *your* setup too. `GET /v1/contract` (client key) returns the
> exact routes, parameters and examples for the providers you configured, and the **Integrate**
> tab in Snake Charmer turns it into a prompt for an AI assistant.

## What you need

| Thing | Where it comes from |
| --- | --- |
| **Base URL** | `http://127.0.0.1:<port>` on the same machine. `serpent status` prints it. |
| **A client key** | `serpent keys --reveal` (the `client` row), or `.env`. Not the admin key, and never a provider key. |
| **A route** | `/p/<slug>/…` for a provider or chain you created. `serpent providers list` shows the slugs. |

Give the key to your app through an **environment variable**, never in source code or chat:

```bash
export SERPENT_URL=http://127.0.0.1:8971
export SERPENT_KEY=<your client key>
```

## Routes

| Address | Goes to |
| --- | --- |
| `/p/<slug>/<path>` | that provider or chain. **Prefer this**: it never changes behind your back. |
| `/v1/<path>` | the *default route*, which you can switch later. Convenient for one-provider setups. |

The path after the route is appended to the provider's base URL, so you send the request that
provider documents. **Serpent does not translate between providers.**

## Authenticate

Either header works:

```
X-Router-Key: <client key>
Authorization: Bearer <client key>
```

## Examples

### curl

```bash
# SerpApi: GET, everything in the query string
curl -H "X-Router-Key: $SERPENT_KEY" \
  "$SERPENT_URL/p/serpapi/search?engine=google&q=coffee+shops+austin"

# SerpApi, Amazon: the search words go in `k`, not `q`
curl -H "X-Router-Key: $SERPENT_KEY" \
  "$SERPENT_URL/p/serpapi/search?engine=amazon&k=air+fryer"

# Serper: POST with a JSON body
curl -X POST -H "X-Router-Key: $SERPENT_KEY" -H 'Content-Type: application/json' \
  -d '{"q":"coffee shops austin"}' "$SERPENT_URL/p/serper/search"
```

### Python

```python
import os
import requests

BASE, KEY = os.environ["SERPENT_URL"], os.environ["SERPENT_KEY"]
HEADERS = {"X-Router-Key": KEY}


class OutOfCredits(Exception):
    pass


def google(query: str) -> list[dict]:
    r = requests.get(f"{BASE}/p/serpapi/search",
                     params={"engine": "google", "q": query}, headers=HEADERS, timeout=40)
    if r.status_code == 429:                       # nothing left to spend, or rate limited
        raise OutOfCredits(f"retry after {r.headers.get('Retry-After', '?')} s")
    r.raise_for_status()
    return r.json().get("organic_results", [])
```

### Node.js (18+)

```js
const BASE = process.env.SERPENT_URL, KEY = process.env.SERPENT_KEY;

export async function google(q) {
  const url = `${BASE}/p/serpapi/search?` + new URLSearchParams({ engine: "google", q });
  const res = await fetch(url, { headers: { "X-Router-Key": KEY } });
  if (res.status === 429) throw new Error(`out of credits, retry after ${res.headers.get("retry-after")} s`);
  if (!res.ok) throw new Error(`search failed: HTTP ${res.status}`);
  return (await res.json()).organic_results ?? [];
}
```

The provider-specific parts (parameter names, result keys such as `organic_results` or
`organic`) come from the **provider's** documentation; the contract page lists the ones for the
providers Serpent knows. Always check them against the provider's current docs.

## What comes back

The provider's own response, unchanged, plus headers from Serpent:

| Header | Meaning |
| --- | --- |
| `X-Router-Provider` | which provider answered |
| `X-Router-Account` | label of the account that answered (never the key) |
| `X-Router-Attempts` | how many accounts were tried |
| `X-Quota-Remaining`, `X-Quota-Available` | credits left, and credits spendable right now |
| `X-Quota-Reset-In` | seconds until the credits reset |
| `X-Cache: HIT` | served from the optional cache; cost no credit |
| `X-Request-Id` | echoed if you send one, otherwise generated; quote it when asking for help |

## Errors and what to do

| Status | Meaning | Do this |
| --- | --- | --- |
| `401` | missing or wrong router key | check the header and the key |
| `403` | the key's role cannot do that | use a client or admin key |
| `404` | no such route, or the provider rejected the path | check the slug and the provider's docs |
| `429` | no credits left, **or** the router's rate limit | stop, wait for `Retry-After`; do not loop |
| `502` | the provider could not be reached | retry later with backoff |
| `503` | no provider configured, or the route has no enabled provider | fix the setup |
| other | the provider's own error, passed through | read the body; `X-Router-Error: all_accounts_failed` means every account failed |

A `429` with `"error": "quota exhausted"` carries `resets_at` and `resets_in_seconds` in the body.

## Good habits

- **Check before a batch:** `POST /v1/quota/check {"count": 50}` (or `GET /v1/quota?need=50`)
  returns `409` if you cannot afford it.
- **Don't retry blindly.** Serpent already retries other accounts (up to `MAX_RETRIES`).
  Retrying a `429` in a loop only burns time.
- **De-duplicate.** The same query twice costs two credits. Cache on your side, or set
  `CACHE_TTL_SECONDS` to let Serpent do it (identical requests then cost nothing).
- **Send an `X-Request-Id`** so a call can be found in the log and in the Requests tab.
- **Use a client key, one per app** if you can: the keys are in `.env`; extra ones are just more
  `key:client` entries in `ROUTER_KEYS`.

## AI agents (LLM tool use)

An agent should call Serpent as an ordinary HTTP tool, with a budget.

1. **Hand it the contract, not guesses.** Paste the Integrate tab's prompt, or point the agent
   at `GET /v1/contract` (needs the client key; `?format=json` for JSON). `GET /llms.txt` is an
   open pointer for tools that look for it.
2. **Define one small tool.** For example, in the JSON-schema style most agent frameworks use:

   ```json
   {
     "name": "web_search",
     "description": "Search the web through the Serpent router. Each call costs one credit.",
     "input_schema": {
       "type": "object",
       "properties": {
         "query": {"type": "string"},
         "engine": {"type": "string", "enum": ["google", "amazon"], "default": "google"}
       },
       "required": ["query"]
     }
   }
   ```

   and implement it with the Python above (`engine=amazon` must send the words as `k`).
3. **Put limits in the tool, not in the prompt:** a maximum number of calls per task, stop on
   `429`, return the error text to the model instead of retrying.
4. **Keep secrets out of the model's context.** The tool reads `SERPENT_KEY` from the
   environment; the model never sees it.
5. **Remember reachability.** A router on `127.0.0.1` can only be reached by software running on
   that machine. A cloud-hosted agent cannot call it. Either run the agent locally, or expose
   Serpent deliberately (see below), or paste the contract text into the agent instead of a URL.

Serpent does not ship an MCP server; wrap the HTTP tool above if your agent framework wants one.

## Calling from another machine

By default Serpent listens on `127.0.0.1` only.

- **LAN:** start it with `--host 0.0.0.0` (or `BIND_HOST=0.0.0.0`), and use the machine's address.
  Keep authentication on and the firewall tight.
- **Internet:** put a reverse proxy (Caddy, nginx) with HTTPS in front, set `TRUST_PROXY=true`,
  and never expose the admin key beyond people who manage Serpent. Router keys travel in
  headers, so plain HTTP over the internet is not acceptable.

## Check the connection

```bash
curl -s $SERPENT_URL/healthz                                   # {"status":"ok",...}  the process is up
curl -s -o /dev/null -w '%{http_code}\n' $SERPENT_URL/readyz   # 200 = at least one credit spendable
curl -s -H "X-Router-Key: $SERPENT_KEY" $SERPENT_URL/v1/quota  # totals and reset time
```

If something fails, see [Troubleshooting](troubleshooting.md).
