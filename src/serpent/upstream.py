"""Translation between inbound requests and the configured SERP provider."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from .config import Settings

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
    "accept-encoding",
    "expect",
}

# Never forwarded back to the caller: Starlette recomputes the body length and
# httpx already decoded any content encoding.
RESPONSE_DROP = HOP_BY_HOP | {"content-encoding", "content-length", "transfer-encoding"}


class BadTarget(Exception):
    pass


def normalize_tail(tail: str) -> str:
    """Validate the proxied path so it cannot escape the configured base URL."""
    tail = (tail or "").strip()
    if not tail:
        return "/"
    if "://" in tail or tail.startswith("//"):
        raise BadTarget("absolute upstream URLs are not allowed")
    if ".." in tail.split("/"):
        raise BadTarget("path traversal is not allowed")
    if not tail.startswith("/"):
        tail = "/" + tail
    return tail


def build_url(settings: Settings, tail: str) -> str:
    return settings.upstream_base_url.rstrip("/") + "/" + tail.lstrip("/")


def blocked_query_params(settings: Settings) -> set[str]:
    blocked = {settings.router_key_header.lower(), "key", "router_key"}
    if settings.auth_style == "query":
        blocked.add(settings.auth_param_name.lower())
    return blocked


def build_params(
    settings: Settings, query_items: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    blocked = blocked_query_params(settings)
    params = [(k, v) for k, v in query_items if k.lower() not in blocked]
    if settings.auth_style == "query":
        params.append((settings.auth_param_name, ""))  # replaced per attempt
    return params


def build_headers(
    settings: Settings, incoming: list[tuple[str, str]], api_key: str
) -> dict[str, str]:
    drop = HOP_BY_HOP | {settings.router_key_header.lower(), "authorization", "cookie"}
    if settings.auth_style == "header":
        drop.add(settings.auth_header_name.lower())
    headers: dict[str, str] = {}
    for name, value in incoming:
        lowered = name.lower()
        if lowered in drop:
            continue
        headers[name] = value
    headers.setdefault("accept", "application/json")
    if settings.auth_style == "header":
        headers[settings.auth_header_name] = api_key
    elif settings.auth_style == "bearer":
        headers["authorization"] = f"Bearer {api_key}"
    return headers


def merge_query(params: list[tuple[str, str]], settings: Settings, api_key: str) -> str:
    clean = [(k, v) for k, v in params if not (k == settings.auth_param_name and v == "")]
    if settings.auth_style == "query":
        clean.append((settings.auth_param_name, api_key))
    return urlencode(clean)


@dataclass(frozen=True)
class Failure:
    kind: str  # connect | 5xx | 429 | 401 | client
    message: str


def classify(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "ok"
    if status_code in (401, 403):
        return "401"
    if status_code == 429:
        return "429"
    if status_code >= 500:
        return "5xx"
    return "client"
