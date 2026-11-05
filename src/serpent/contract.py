"""A live, readable description of how to call *this* router.

An application (or an AI assistant building one) can read ``/v1/contract`` and learn what
routes exist, how to authenticate, what each provider expects and what comes back.  It is
generated from the current setup, so it never drifts from what is actually configured.

The per-provider operation tables below are written from each provider's public docs and
are starting points: providers change their APIs, so every entry carries a "verify" note.
"""

from __future__ import annotations

from .config import Settings
from .providers import Provider

VERIFY = "Written from the provider's public docs; confirm details against their current docs."


def _op(id_, title, method, path, params, example, results, fields, **extra):
    return {
        "id": id_, "title": title, "method": method, "path": path,
        "params": params, "example": example, "results_key": results,
        "result_fields": fields, **extra,
    }


def _serpapi_ops() -> list[dict]:
    def get(id_, title, engine, q="q", extra=None, results="organic_results", fields=None, params=None):
        query = {"engine": engine, **(extra or {}), q: "<your search>"}
        qs = "&".join(f"{k}={v}" for k, v in query.items())
        return _op(
            id_, title, "GET", "search",
            params or [{"name": "engine", "value": engine, "required": True},
                       {"name": q, "required": True, "about": "the search words"}],
            f"search?{qs.replace(' ', '+')}", results,
            fields or ["title", "link", "snippet"],
        )

    google = get("google", "Google web search", "google", fields=["position", "title", "link", "snippet"])
    google["params"] += [
        {"name": "location", "about": "e.g. Austin, Texas, United States"},
        {"name": "hl", "about": "interface language, e.g. en"},
        {"name": "gl", "about": "country code, e.g. us"},
        {"name": "num", "about": "results per page"},
        {"name": "start", "about": "result offset, for paging"},
    ]
    amazon = get("amazon", "Amazon product search", "amazon", q="k",
                 fields=["asin", "title", "link", "price", "rating", "reviews", "thumbnail"])
    amazon["params"] += [
        {"name": "amazon_domain", "about": "e.g. amazon.com, amazon.co.uk"},
        {"name": "page", "about": "page number"},
    ]
    amazon["notes"] = "Amazon searches use `k` for the search words, not `q`."
    return [
        google,
        amazon,
        get("google_shopping", "Google Shopping", "google_shopping", results="shopping_results",
            fields=["title", "product_link", "price", "source", "rating", "reviews"]),
        get("google_news", "Google News", "google_news", results="news_results",
            fields=["title", "link", "source", "date"]),
        get("google_images", "Google Images", "google_images", results="images_results",
            fields=["title", "link", "original", "thumbnail", "source"]),
        get("google_maps", "Google Maps places", "google_maps", extra={"type": "search"},
            results="local_results", fields=["title", "place_id", "address", "rating", "reviews", "phone", "website"],
            params=[{"name": "engine", "value": "google_maps", "required": True},
                    {"name": "type", "value": "search", "required": True},
                    {"name": "q", "required": True, "about": "the search words"}]),
    ]


def _serper_ops() -> list[dict]:
    def post(id_, title, path, results, fields):
        return _op(
            id_, title, "POST", path,
            [{"name": "q", "required": True, "about": "the search words (JSON body)"},
             {"name": "gl", "about": "country code, e.g. us"},
             {"name": "hl", "about": "language, e.g. en"},
             {"name": "num", "about": "results per page"},
             {"name": "page", "about": "page number"}],
            f'POST {path}  {{"q": "<your search>"}}', results, fields,
        )

    return [
        post("search", "Google web search", "search", "organic", ["position", "title", "link", "snippet"]),
        post("images", "Google Images", "images", "images", ["title", "imageUrl", "link", "source"]),
        post("news", "Google News", "news", "news", ["title", "link", "snippet", "date", "source"]),
        post("maps", "Google Maps places", "maps", "places", ["title", "address", "rating", "website"]),
        post("shopping", "Google Shopping", "shopping", "shopping", ["title", "price", "link", "source", "rating"]),
    ]


def _brave_ops() -> list[dict]:
    return [_op(
        "web", "Web search", "GET", "web/search",
        [{"name": "q", "required": True, "about": "the search words"},
         {"name": "count", "about": "results per page"},
         {"name": "country", "about": "country code, e.g. US"}],
        "web/search?q=<your+search>", "web.results", ["title", "url", "description"],
    )]


OPERATIONS = {"serpapi": _serpapi_ops, "serper": _serper_ops, "brave": _brave_ops}


def operations_for(provider: Provider) -> list[dict]:
    maker = OPERATIONS.get(provider.preset or "")
    if maker is None and "serpapi.com" in provider.base_url:
        maker = OPERATIONS["serpapi"]
    return maker() if maker else []


def _provider_entry(p: Provider) -> dict:
    ops = operations_for(p)
    return {
        "slug": p.slug,
        "kind": "provider",
        "name": p.name,
        "enabled": p.enabled,
        "path_prefix": f"/p/{p.slug}/",
        "upstream_base": p.base_url,
        "preset": p.preset,
        "operations": ops,
        "notes": VERIFY if ops else (
            "No ready-made examples for this provider. Send the request exactly as the provider's "
            f"own docs describe it, with the path after /p/{p.slug}/ appended to {p.base_url}."),
    }


def build(settings: Settings, providers: list[Provider], chains: list[dict],
          default_route: str, base_url: str) -> dict:
    by_slug = {p.slug: p for p in providers}
    routes = [_provider_entry(p) for p in providers]
    for c in chains:
        steps = [by_slug[s] for s in c["steps"] if s in by_slug]
        kinds = {p.preset or p.base_url for p in steps}
        entry = {
            "slug": c["slug"], "kind": "chain", "name": c.get("name") or c["slug"],
            "enabled": bool(c.get("enabled", True)), "path_prefix": f"/p/{c['slug']}/",
            "steps": c["steps"], "operations": [], "notes": "",
        }
        if len(kinds) == 1 and steps:
            entry["operations"] = operations_for(steps[0])
            entry["notes"] = ("Tries each step in order and falls through when one is out of credits "
                              "or failing. All steps speak the same API, so one request shape works.")
        else:
            entry["notes"] = ("WARNING: the steps are different provider types. The same request is "
                              "sent to each step unchanged (nothing is translated), so a step that "
                              "does not understand it will fail. Prefer chains of one provider type.")
        routes.append(entry)
    target = next((r for r in routes if r["slug"] == default_route), None)
    key_header = settings.router_key_header
    return {
        "service": "Serpent",
        "about": ("A pass-through router for search APIs. It adds the provider key, shares credits "
                  "across accounts and falls back on failure. It does not translate between "
                  "providers: send each route the request its provider documents."),
        "base_url": base_url,
        "contract_url": f"{base_url}/v1/contract",
        "auth": {
            "send_one_of": [f"{key_header}: <router key>", "Authorization: Bearer <router key>"],
            "key_to_use": "a client key. Never send a provider's own API key; the router adds it.",
        },
        "default_route": {
            "path_prefix": "/v1/", "target": default_route,
            "same_as": f"/p/{default_route}/" if target else None,
        },
        "routes": routes,
        "other_endpoints": [
            {"method": "GET", "path": "/v1/quota", "about": "credits left across all accounts (read key or higher)"},
            {"method": "POST", "path": "/v1/quota/check", "about": 'check capacity first: {"count": 3}'},
            {"method": "GET", "path": "/v1/contract", "about": "this document (add ?format=json for JSON)"},
        ],
        "response_headers": {
            "x-router-provider": "which provider answered",
            "x-router-account": "label of the account that answered (never the key)",
            "x-router-attempts": "how many accounts were tried",
            "x-quota-remaining": "credits left this period, all accounts",
            "x-quota-reset-in": "seconds until credits reset",
            "x-cache": "HIT when served from the router's cache (costs no credit)",
        },
        "errors": [
            {"status": 401, "meaning": "missing or invalid router key"},
            {"status": 403, "meaning": "this key's role cannot do that"},
            {"status": 404, "meaning": "no such route (see routes above)"},
            {"status": 429, "meaning": "no credits left, or the router rate limit was hit; "
                                       "honour the Retry-After header"},
            {"status": 502, "meaning": "the provider could not be reached"},
            {"status": 503, "meaning": "no provider configured, or the route has none enabled"},
            {"status": "other", "meaning": "provider errors pass through unchanged; "
                                           "x-router-error: all_accounts_failed means every account failed"},
        ],
        "rules": [
            "Every call to a provider route spends one credit, even if the result is empty.",
            "Failed calls that never reached a result are refunded where possible.",
            "On 429, wait for Retry-After instead of retrying in a loop.",
            f"Retries across accounts happen inside the router (up to {settings.max_retries}); don't add your own.",
            "Responses are the provider's own JSON, unchanged.",
        ],
    }


def _bullet(items) -> str:
    return "\n".join(f"- {i}" for i in items)


def render_markdown(c: dict) -> str:
    base = c["base_url"]
    out = [
        "# Serpent API contract",
        "",
        c["about"],
        "",
        f"Base URL: `{base}`",
        "",
        "## Authentication",
        "",
        "Send a **client key** (not a provider key) with every request, as one of:",
        "",
        _bullet(f"`{h}`" for h in c["auth"]["send_one_of"]),
        "",
        "```bash",
        f'curl -H "{c["auth"]["send_one_of"][0].split(":")[0]}: $ROUTER_KEY" "{base}/v1/quota"',
        "```",
        "",
        "## Routes",
        "",
        f"`/v1/…` is the default route and currently points to **{c['default_route']['target']}**"
        + (f" (identical to `{c['default_route']['same_as']}…`)." if c["default_route"]["same_as"] else "."),
        "Prefer the explicit `/p/<slug>/…` form: it does not change if the default is changed.",
        "",
    ]
    if not c["routes"]:
        out += ["**No provider is configured yet**, so there is nothing to call. "
                "Add one in Snake Charmer (`/ui/`) or with `serpent providers add`.", ""]
    for r in c["routes"]:
        title = f"### `{r['path_prefix']}`  {r['name']}"
        title += "  (chain)" if r["kind"] == "chain" else ""
        out += [title, ""]
        if not r["enabled"]:
            out += ["_Disabled: requests to this route fail until it is enabled._", ""]
        if r["kind"] == "chain":
            out += [f"Steps, in order: {', '.join(f'`{s}`' for s in r['steps'])}.", ""]
        else:
            out += [f"Forwards to `{r['upstream_base']}`. The path after `{r['path_prefix']}` is appended to it.", ""]
        if r["notes"]:
            out += [r["notes"], ""]
        for op in r["operations"]:
            out += [f"#### {op['title']}", "", f"`{op['method']} {r['path_prefix']}{op['path']}`", ""]
            req = [f"`{p['name']}`" + (f" = `{p['value']}`" if p.get("value") else "")
                   + (" (required)" if p.get("required") else "")
                   + (f": {p['about']}" if p.get("about") else "") for p in op["params"]]
            out += ["Parameters:", "", _bullet(req), ""]
            ex = op["example"]
            out += ["```bash"]
            if op["method"] == "GET":
                out += [f'curl -H "X-Router-Key: $ROUTER_KEY" "{base}{r["path_prefix"]}{ex}"']
            else:
                body = ex.split("  ", 1)[1]
                out += ["curl -X POST -H \"X-Router-Key: $ROUTER_KEY\" -H 'Content-Type: application/json' \\",
                        f"  -d '{body}' \"{base}{r['path_prefix']}{op['path']}\""]
            out += ["```", ""]
            out += [f"Results are in `{op['results_key']}`; each item has: "
                    + ", ".join(f"`{f}`" for f in op["result_fields"]) + ".", ""]
            if op.get("notes"):
                out += [op["notes"], ""]
    out += ["## Other endpoints", "", _bullet(f"`{e['method']} {e['path']}`: {e['about']}" for e in c["other_endpoints"]), ""]
    out += ["## Response headers", "", _bullet(f"`{k}`: {v}" for k, v in c["response_headers"].items()), ""]
    out += ["## Errors", "", _bullet(f"**{e['status']}**: {e['meaning']}" for e in c["errors"]), ""]
    out += ["## Rules for clients", "", _bullet(c["rules"]), ""]
    return "\n".join(out)


def render_llms_txt(base_url: str) -> str:
    return (
        "# Serpent\n\n"
        "> A router in front of search APIs. Read the contract first; it is generated from the "
        "live setup and lists every route, how to authenticate, and what each provider expects.\n\n"
        f"- [API contract]({base_url}/v1/contract): routes, auth, request and response shapes "
        "(needs a client key; add ?format=json for JSON)\n"
        f"- [Quota]({base_url}/v1/quota): credits left\n"
    )

