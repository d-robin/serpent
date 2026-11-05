"""Ask a provider how much allowance an API key has left, on the provider's side.

This is separate from Serpent's own per-account limit and count: the limit is what *you*
chose to allow through the router, while this is what the provider says the plan gives.
Only providers with a documented, free usage endpoint are supported; anything else
reports ``supported: false`` rather than guessing.  Calls here are never counted against
an account's quota, and the key never appears in what is returned.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from .providers import Provider

TIMEOUT = 8.0


def adapter_for(provider: Provider) -> str | None:
    host = (urlparse(provider.base_url).hostname or "").lower()
    if provider.preset == "serpapi" or host.endswith("serpapi.com"):
        return "serpapi"
    return None


def _int(value) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _serpapi(provider: Provider, api_key: str) -> tuple[str, dict]:
    param = provider.auth_param_name or "api_key"
    return provider.base_url.rstrip("/") + "/account", {param: api_key}


def parse_serpapi(data: dict) -> dict:
    """SerpApi Account API: monthly plan allowance plus any extra credits."""
    allowance = _int(data.get("searches_per_month"))
    used = _int(data.get("this_month_usage"))
    plan_left = _int(data.get("plan_searches_left"))
    total_left = _int(data.get("total_searches_left"))
    extra = _int(data.get("extra_credits"))
    remaining = total_left if total_left is not None else plan_left
    if used is None and allowance is not None and plan_left is not None:
        used = max(0, allowance - plan_left)
    return {
        "supported": True,
        "plan": data.get("plan_name") if isinstance(data.get("plan_name"), str) else None,
        "allowance": allowance,
        "used": used,
        "remaining": remaining,
        "extra_credits": extra,
        "rate_limit_per_hour": _int(data.get("account_rate_limit_per_hour")),
        "error": None,
    }


async def fetch(client: httpx.AsyncClient, provider: Provider, api_key: str) -> dict:
    which = adapter_for(provider)
    if which is None:
        return {
            "supported": False,
            "error": None,
            "note": f"{provider.name} does not offer a usage lookup that Serpent knows about; "
                    "check its own dashboard for the plan allowance.",
        }
    url, params = _serpapi(provider, api_key)
    try:
        resp = await client.get(url, params=params, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        # Never include str(exc): it can contain the request URL, and so the key.
        return {"supported": True, "error": f"could not reach {provider.name} ({type(exc).__name__})"}
    if resp.status_code in (401, 403):
        return {"supported": True, "error": f"{provider.name} rejected this key (HTTP {resp.status_code})"}
    if resp.status_code != 200:
        return {"supported": True, "error": f"{provider.name} answered HTTP {resp.status_code}"}
    try:
        data = resp.json()
    except ValueError:
        return {"supported": True, "error": f"{provider.name} sent a reply that is not JSON"}
    if not isinstance(data, dict):
        return {"supported": True, "error": f"{provider.name} sent an unexpected reply"}
    return parse_serpapi(data)
