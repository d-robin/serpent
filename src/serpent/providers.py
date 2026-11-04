"""Providers (upstream SERP APIs) and fallback chains.

A *provider* is one upstream API plus how its key is attached.  Accounts belong
to a provider.  A *chain* is an ordered list of provider slugs; the proxy tries
each in turn and moves on when one is exhausted or failing.

Routes:  ``/v1/*`` -> the default route (a provider or chain),
         ``/p/{slug}/*`` -> that provider or chain explicitly.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass

from . import db
from .config import Settings

AUTH_STYLES = ("header", "query", "bearer")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")

# Starting points for the UI and CLI.  Verify against the provider's docs: APIs change.
PRESETS: dict[str, dict] = {
    "serper": {
        "name": "Serper",
        "base_url": "https://google.serper.dev",
        "auth_style": "header",
        "auth_header_name": "X-API-KEY",
    },
    "serpapi": {
        "name": "SerpApi",
        "base_url": "https://serpapi.com",
        "auth_style": "query",
        "auth_param_name": "api_key",
    },
    "scrapingdog": {
        "name": "ScrapingDog",
        "base_url": "https://api.scrapingdog.com",
        "auth_style": "query",
        "auth_param_name": "api_key",
    },
    "valueserp": {
        "name": "VALUE SERP",
        "base_url": "https://api.valueserp.com",
        "auth_style": "query",
        "auth_param_name": "api_key",
    },
    "brave": {
        "name": "Brave Search",
        "base_url": "https://api.search.brave.com/res/v1",
        "auth_style": "header",
        "auth_header_name": "X-Subscription-Token",
    },
}


class ProviderError(Exception):
    pass


class NotFound(ProviderError):
    pass


class Conflict(ProviderError):
    pass


@dataclass(frozen=True)
class Provider:
    id: int
    slug: str
    name: str
    preset: str | None
    base_url: str
    auth_style: str
    auth_header_name: str
    auth_param_name: str
    enabled: bool

    def apply(self, settings: Settings) -> Settings:
        """Settings view for this provider, consumed by the upstream helpers."""
        from .config import with_overrides

        return with_overrides(
            settings,
            upstream_base_url=self.base_url,
            auth_style=self.auth_style,
            auth_header_name=self.auth_header_name,
            auth_param_name=self.auth_param_name,
        )

    def public(self) -> dict:
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "preset": self.preset,
            "base_url": self.base_url,
            "auth_style": self.auth_style,
            "auth_header_name": self.auth_header_name,
            "auth_param_name": self.auth_param_name,
            "enabled": self.enabled,
        }


def _provider(row: sqlite3.Row) -> Provider:
    return Provider(
        id=int(row["id"]),
        slug=row["slug"],
        name=row["name"],
        preset=row["preset"],
        base_url=row["base_url"],
        auth_style=row["auth_style"],
        auth_header_name=row["auth_header_name"],
        auth_param_name=row["auth_param_name"],
        enabled=bool(row["enabled"]),
    )


def _clean_slug(slug: str) -> str:
    slug = (slug or "").strip().lower()
    if not SLUG_RE.match(slug):
        raise ProviderError("slug must be 1-32 chars of a-z, 0-9, '-' or '_'")
    return slug


def _validate_provider(fields: dict) -> None:
    url = fields.get("base_url", "")
    if not re.match(r"^https?://[^\s/]+", url):
        raise ProviderError("base_url must start with http:// or https://")
    if fields.get("auth_style") not in AUTH_STYLES:
        raise ProviderError(f"auth_style must be one of {', '.join(AUTH_STYLES)}")


# ---- providers ------------------------------------------------------------


def list_providers() -> list[Provider]:
    rows = db.connection().execute("SELECT * FROM providers ORDER BY id").fetchall()
    return [_provider(r) for r in rows]


def get_provider(ref: int | str) -> Provider:
    col = "id" if isinstance(ref, int) else "slug"
    row = db.connection().execute(f"SELECT * FROM providers WHERE {col} = ?", (ref,)).fetchone()
    if row is None:
        raise NotFound(f"provider {ref!r} not found")
    return _provider(row)


def add_provider(
    slug: str,
    *,
    name: str = "",
    preset: str | None = None,
    base_url: str = "",
    auth_style: str = "",
    auth_header_name: str = "",
    auth_param_name: str = "",
) -> Provider:
    slug = _clean_slug(slug)
    base: dict = dict(PRESETS.get(preset or "", {}))
    if preset and preset not in PRESETS:
        raise ProviderError(f"unknown preset {preset!r}")
    fields = {
        "name": name or base.get("name") or slug,
        "base_url": (base_url or base.get("base_url", "")).rstrip("/"),
        "auth_style": auth_style or base.get("auth_style", "header"),
        "auth_header_name": auth_header_name or base.get("auth_header_name", "X-API-KEY"),
        "auth_param_name": auth_param_name or base.get("auth_param_name", "api_key"),
    }
    _validate_provider(fields)
    try:
        with db.write_tx() as conn:
            cur = conn.execute(
                """INSERT INTO providers (slug, name, preset, base_url, auth_style,
                       auth_header_name, auth_param_name, enabled, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (slug, fields["name"], preset, fields["base_url"], fields["auth_style"],
                 fields["auth_header_name"], fields["auth_param_name"], db.now_iso()),
            )
            pid = int(cur.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise Conflict(f"slug {slug!r} is already used") from exc
    return get_provider(pid)


def update_provider(ref: int | str, **changes) -> Provider:
    current = get_provider(ref)
    allowed = {"name", "base_url", "auth_style", "auth_header_name", "auth_param_name", "enabled"}
    updates = {k: v for k, v in changes.items() if k in allowed and v is not None}
    if not updates:
        raise ProviderError("nothing to update")
    if "base_url" in updates:
        updates["base_url"] = str(updates["base_url"]).rstrip("/")
    merged = {**current.public(), **updates}
    _validate_provider(merged)
    if "enabled" in updates:
        updates["enabled"] = 1 if updates["enabled"] else 0
    sets = ", ".join(f"{k} = ?" for k in updates)
    with db.write_tx() as conn:
        conn.execute(f"UPDATE providers SET {sets} WHERE id = ?", [*updates.values(), current.id])
    return get_provider(current.id)


def delete_provider(ref: int | str) -> None:
    prov = get_provider(ref)
    with db.write_tx() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM accounts WHERE provider_id = ?", (prov.id,)
        ).fetchone()[0]
        if n:
            raise Conflict(f"provider {prov.slug!r} still has {n} account(s); move or remove them")
        for chain in list_chains():
            if prov.slug in chain["steps"]:
                raise Conflict(f"provider {prov.slug!r} is used by chain {chain['slug']!r}")
        conn.execute("DELETE FROM providers WHERE id = ?", (prov.id,))


def ensure_default(settings: Settings) -> Provider:
    """Create the 'default' provider from env settings and adopt orphan accounts."""
    with db.write_tx() as conn:
        row = conn.execute("SELECT * FROM providers WHERE slug = 'default'").fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO providers (slug, name, preset, base_url, auth_style,
                       auth_header_name, auth_param_name, enabled, created_at)
                   VALUES ('default', 'Default', NULL, ?, ?, ?, ?, 1, ?)""",
                (settings.upstream_base_url.rstrip("/"), settings.auth_style,
                 settings.auth_header_name, settings.auth_param_name, db.now_iso()),
            )
            row = conn.execute("SELECT * FROM providers WHERE slug = 'default'").fetchone()
        conn.execute("UPDATE accounts SET provider_id = ? WHERE provider_id IS NULL", (row["id"],))
    return _provider(row)


# ---- chains ---------------------------------------------------------------


def _chain(row: sqlite3.Row) -> dict:
    return {
        "id": int(row["id"]),
        "slug": row["slug"],
        "name": row["name"],
        "steps": json.loads(row["steps"]),
        "enabled": bool(row["enabled"]),
        "kind": "chain",
    }


def _validate_steps(steps: list) -> list[str]:
    if not isinstance(steps, list) or not steps:
        raise ProviderError("a chain needs at least one provider step")
    known = {p.slug for p in list_providers()}
    out: list[str] = []
    for step in steps:
        step = str(step).strip().lower()
        if step not in known:
            raise ProviderError(f"unknown provider {step!r} in chain")
        if step in out:
            raise ProviderError(f"provider {step!r} appears twice in the chain")
        out.append(step)
    return out


def list_chains() -> list[dict]:
    return [_chain(r) for r in db.connection().execute("SELECT * FROM chains ORDER BY id")]


def get_chain(ref: int | str) -> dict:
    col = "id" if isinstance(ref, int) else "slug"
    row = db.connection().execute(f"SELECT * FROM chains WHERE {col} = ?", (ref,)).fetchone()
    if row is None:
        raise NotFound(f"chain {ref!r} not found")
    return _chain(row)


def add_chain(slug: str, steps: list, *, name: str = "") -> dict:
    slug = _clean_slug(slug)
    steps = _validate_steps(steps)
    if db.connection().execute("SELECT 1 FROM providers WHERE slug = ?", (slug,)).fetchone():
        raise Conflict(f"slug {slug!r} is already a provider")
    try:
        with db.write_tx() as conn:
            cur = conn.execute(
                "INSERT INTO chains (slug, name, steps, enabled, created_at) VALUES (?,?,?,1,?)",
                (slug, name or slug, json.dumps(steps), db.now_iso()),
            )
            cid = int(cur.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise Conflict(f"slug {slug!r} is already used") from exc
    return get_chain(cid)


def update_chain(ref: int | str, **changes) -> dict:
    current = get_chain(ref)
    updates: dict = {}
    if changes.get("name") is not None:
        updates["name"] = changes["name"]
    if changes.get("steps") is not None:
        updates["steps"] = json.dumps(_validate_steps(changes["steps"]))
    if changes.get("enabled") is not None:
        updates["enabled"] = 1 if changes["enabled"] else 0
    if not updates:
        raise ProviderError("nothing to update")
    sets = ", ".join(f"{k} = ?" for k in updates)
    with db.write_tx() as conn:
        conn.execute(f"UPDATE chains SET {sets} WHERE id = ?", [*updates.values(), current["id"]])
    return get_chain(current["id"])


def delete_chain(ref: int | str) -> None:
    chain = get_chain(ref)
    if get_default_route() == chain["slug"]:
        raise Conflict("this chain is the default route; pick another default first")
    with db.write_tx() as conn:
        conn.execute("DELETE FROM chains WHERE id = ?", (chain["id"],))


# ---- routing --------------------------------------------------------------


def get_default_route() -> str:
    return db.get_state("default_route", "default")


def set_default_route(slug: str) -> str:
    slug = slug.strip().lower()
    resolve(slug)  # raises NotFound
    db.set_state("default_route", slug)
    return slug


def resolve(slug: str) -> list[Provider]:
    """Ordered providers to try for a provider or chain slug (enabled ones only)."""
    conn = db.connection()
    row = conn.execute("SELECT * FROM providers WHERE slug = ?", (slug,)).fetchone()
    if row is not None:
        return [_provider(row)] if row["enabled"] else []
    chain = conn.execute("SELECT * FROM chains WHERE slug = ?", (slug,)).fetchone()
    if chain is None:
        raise NotFound(f"no provider or chain named {slug!r}")
    if not chain["enabled"]:
        return []
    out: list[Provider] = []
    for step in json.loads(chain["steps"]):
        prow = conn.execute("SELECT * FROM providers WHERE slug = ?", (step,)).fetchone()
        if prow is not None and prow["enabled"]:
            out.append(_provider(prow))
    return out


def route_exists(slug: str) -> bool:
    try:
        resolve(slug)
        return True
    except NotFound:
        return False
