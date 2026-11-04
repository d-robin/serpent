"""Caller authentication and role checks.

Router keys never touch the accounts table: callers present a router key and
the router swaps it for a provider key at the edge, so a leaked caller key
cannot be used against the SERP provider directly.
"""

from __future__ import annotations

import hmac

from fastapi import Request

from .config import ROLE_RANK, Settings

OPEN_ROLE = "admin"


def present_key(request: Request, settings: Settings) -> str:
    """Extract the router key from the header or an Authorization bearer."""
    key = request.headers.get(settings.router_key_header, "").strip()
    if key:
        return key
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return ""


def role_for(settings: Settings, presented: str) -> str | None:
    """Constant-time role lookup.  None = rejected."""
    if not settings.auth_enabled:
        return OPEN_ROLE
    if not presented:
        return None
    for key, role in settings.router_keys.items():
        if hmac.compare_digest(key, presented):
            return role
    return None


def has_role(role: str | None, minimum: str) -> bool:
    if role is None:
        return False
    return ROLE_RANK.get(role, 0) >= ROLE_RANK.get(minimum, 99)


def key_fingerprint(presented: str) -> str:
    """Short, non-reversible id used in logs instead of the raw key."""
    import hashlib

    if not presented:
        return "anon"
    return hashlib.sha256(presented.encode()).hexdigest()[:8]


class AuthError(Exception):
    def __init__(self, status_code: int, detail: str, *, role: str | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.role = role


def require(request: Request, minimum: str) -> str:
    settings: Settings = request.app.state.settings
    presented = present_key(request, settings)
    role = role_for(settings, presented)
    if role is None:
        raise AuthError(401, "missing or invalid router key")
    if not has_role(role, minimum):
        raise AuthError(403, f"role '{role}' cannot perform this action")
    return role
