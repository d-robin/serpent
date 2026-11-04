"""Settings that can be changed at runtime (from Snake Charmer) and persist in SQLite.

Everything else stays environment-driven so a deployment remains reproducible.
Values are applied in place on the frozen ``Settings`` instance, so every
request handler sees them immediately.
"""

from __future__ import annotations

import json

from . import db
from .config import VALID_STRATEGIES, Settings

STATE_KEY = "tunables"


class TunableError(ValueError):
    pass


def _int(lo: int, hi: int):
    def conv(v):
        n = int(v)
        if not lo <= n <= hi:
            raise TunableError(f"must be between {lo} and {hi}")
        return n

    return conv


def _float(lo: float, hi: float):
    def conv(v):
        n = float(v)
        if not lo <= n <= hi:
            raise TunableError(f"must be between {lo} and {hi}")
        return n

    return conv


def _strategy(v):
    v = str(v).lower()
    if v not in VALID_STRATEGIES:
        raise TunableError(f"must be one of {', '.join(VALID_STRATEGIES)}")
    return v


def _refund(v):
    parts = [p.strip().lower() for p in (v if isinstance(v, list) else str(v).split(",")) if p]
    bad = [p for p in parts if p not in {"connect", "5xx", "429", "401"}]
    if bad:
        raise TunableError(f"unknown refund kinds: {', '.join(bad)}")
    return tuple(parts)


SPEC = {
    "strategy": _strategy,
    "max_retries": _int(0, 10),
    "quota_reserve": _int(0, 100000),
    "default_quota_limit": _int(0, 10_000_000),
    "cooldown_base_seconds": _float(0, 3600),
    "cooldown_max_seconds": _float(0, 86400),
    "refund_on": _refund,
    "upstream_timeout": _float(1, 300),
}


def current(settings: Settings) -> dict:
    out = {k: getattr(settings, k) for k in SPEC}
    out["refund_on"] = list(out["refund_on"])
    return out


def apply(settings: Settings, changes: dict, *, persist: bool = True) -> dict:
    clean = {}
    for key, raw in changes.items():
        if key not in SPEC:
            raise TunableError(f"{key!r} cannot be changed at runtime")
        try:
            clean[key] = SPEC[key](raw)
        except TunableError as exc:
            raise TunableError(f"{key}: {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise TunableError(f"{key}: invalid value") from exc
    for key, value in clean.items():
        object.__setattr__(settings, key, value)
    if persist and clean:
        stored = json.loads(db.get_state(STATE_KEY, "{}") or "{}")
        stored.update({k: list(v) if isinstance(v, tuple) else v for k, v in clean.items()})
        db.set_state(STATE_KEY, json.dumps(stored))
    return current(settings)


def load(settings: Settings) -> None:
    stored = json.loads(db.get_state(STATE_KEY, "{}") or "{}")
    try:
        apply(settings, stored, persist=False)
    except TunableError:
        pass
