# Snake Charmer

The admin UI for [Serpent](../README.md): providers, accounts, fallback chains, runtime
settings and a "Try it" console. Svelte 5 + Vite + TypeScript, plain CSS, no CDN and no web
fonts, so it works on an offline LAN.

The router serves the built bundle at **`/ui/`** (e.g. `http://127.0.0.1:8971/ui/`).

## Build

```bash
cd ui
npm ci
npm run build      # writes ../src/serpent/ui_dist (git-ignored, shipped in the wheel)
```

## Develop

```bash
./serve.sh --dev   # from the repo root: router on a free port + Vite with hot reload
```

or run the router yourself and point Vite at it:

```bash
SERPENT_API=http://127.0.0.1:8971 npm run dev   # http://localhost:5173/ui/
```

## Checks

```bash
npm run check      # svelte-check / TypeScript
npm test           # vitest (API client, helpers, components)
```

## How it talks to the router

Everything uses the public HTTP API; there is no UI-only backend.

| Screen | Endpoints |
| --- | --- |
| Overview | `GET /api/status` (polled every 5 s) |
| Providers | `/admin/providers`, `/admin/presets` |
| Accounts | `/admin/accounts[/{id}[/reset]]`, `POST /admin/reset` |
| Chains | `/admin/chains`, `PUT /admin/default-route` |
| Settings | `/admin/tunables`, `GET /admin/config` |
| Try it | `/v1/*` and `/p/{provider-or-chain}/*` (spends a real credit) |

The key you sign in with is kept in `sessionStorage` for that tab only and sent as
`X-Router-Key`. An `admin` key gets the full UI, a `read` key gets a read-only view, and when
`ROUTER_KEYS` is empty the UI warns that authentication is off.

Logos come from `../branding/` (`public/logo.svg`, `public/favicon.svg` are copies).
