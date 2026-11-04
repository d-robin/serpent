"""Configuration: environment variables with a tiny .env loader.

No third-party dependency, so a Raspberry Pi needs nothing but the three
packages in requirements.txt.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

ROOT = Path(os.environ.get("SERPENT_HOME") or Path.cwd())

VALID_STRATEGIES = (
    "most_remaining",
    "round_robin",
    "least_in_flight",
    "least_recently_used",
    "fill_first",
    "random",
)

VALID_ROLES = ("read", "client", "admin")
ROLE_RANK = {"read": 1, "client": 2, "admin": 3}


def _load_dotenv(path: Path) -> None:
    """Minimal .env parser: KEY=VALUE, # comments, optional quotes."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _env_csv(name: str, default: str = "") -> list[str]:
    raw = _env(name, default)
    return [part.strip() for part in raw.split(",") if part.strip()]


def parse_router_keys(raw: str) -> dict[str, str]:
    """Parse ``key:role,key2:role2`` into {key: role}.

    A bare key gets the ``client`` role.  A key containing colons is treated
    as literal unless its suffix is a known role.
    """
    keys: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        head, sep, tail = part.rpartition(":")
        if sep and tail.strip().lower() in VALID_ROLES:
            key, role = head.strip(), tail.strip().lower()
        else:
            key, role = part, "client"
        if key:
            keys[key] = role
    return keys


def parse_account_seed(raw: str) -> list[tuple[str, str]]:
    """Parse ``label:key,label:key`` (label optional) into pairs."""
    out: list[tuple[str, str]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        label, sep, key = part.partition(":")
        if not sep:
            label, key = "", part
        out.append((label.strip(), key.strip()))
    return [(label, key) for label, key in out if key]


@dataclass(frozen=True)
class Settings:
    # server
    bind_host: str = "0.0.0.0"
    bind_port: int = 8971
    log_level: str = "info"
    trust_proxy: bool = False

    # storage
    db_path: str = str(ROOT / "data" / "serpent.db")

    # upstream
    upstream_base_url: str = "https://google.serper.dev"
    upstream_timeout: float = 30.0
    upstream_verify_tls: bool = True
    max_body_bytes: int = 1_048_576
    auth_style: str = "header"  # header | query | bearer
    auth_header_name: str = "X-API-KEY"
    auth_param_name: str = "api_key"
    route_prefix: str = "/v1"

    # quota
    default_quota_limit: int = 250
    quota_reset_day: int = 1
    quota_reserve: int = 0

    # rotation
    strategy: str = "most_remaining"
    max_retries: int = 2
    refund_on: tuple[str, ...] = ("connect", "5xx", "429", "401")
    cooldown_base_seconds: float = 10.0
    cooldown_max_seconds: float = 300.0

    # auth
    router_keys: dict[str, str] = field(default_factory=dict)
    router_key_header: str = "X-Router-Key"

    # dashboard
    dashboard_public: bool = True
    expose_account_label: bool = True

    # extras
    cache_ttl_seconds: float = 0.0
    cache_max_entries: int = 512
    rate_limit_per_minute: float = 0.0
    rate_limit_burst: float = 0.0
    request_log_size: int = 500

    # seeding
    account_seed: str = ""

    @property
    def auth_enabled(self) -> bool:
        return bool(self.router_keys)

    def normalized_prefix(self) -> str:
        prefix = "/" + self.route_prefix.strip("/") if self.route_prefix.strip("/") else ""
        return prefix

    def refund(self, kind: str) -> bool:
        return kind in self.refund_on


def load_settings(env_file: Path | None = None) -> Settings:
    _load_dotenv(env_file or Path(os.environ.get("ENV_FILE", ROOT / ".env")))

    reset_day = min(max(_env_int("QUOTA_RESET_DAY", 1), 1), 28)
    prefix = _env("ROUTE_PREFIX", "/v1").strip()
    if prefix and not prefix.startswith("/"):
        prefix = "/" + prefix
    auth_style = _env("AUTH_STYLE", "header").strip().lower()
    if auth_style not in {"header", "query", "bearer"}:
        auth_style = "header"
    strategy = _env("STRATEGY", "most_remaining").strip().lower()
    if strategy not in VALID_STRATEGIES:
        strategy = "most_remaining"

    return Settings(
        bind_host=_env("BIND_HOST", "0.0.0.0"),
        bind_port=_env_int("BIND_PORT", 8971),
        log_level=_env("LOG_LEVEL", "info").lower(),
        trust_proxy=_env_bool("TRUST_PROXY", False),
        db_path=_env("DB_PATH", str(ROOT / "data" / "serpent.db")),
        upstream_base_url=_env("UPSTREAM_BASE_URL", "https://google.serper.dev").rstrip("/"),
        upstream_timeout=_env_float("UPSTREAM_TIMEOUT", 30.0),
        upstream_verify_tls=_env_bool("UPSTREAM_VERIFY_TLS", True),
        max_body_bytes=_env_int("MAX_BODY_BYTES", 1_048_576),
        auth_style=auth_style,
        auth_header_name=_env("AUTH_HEADER_NAME", "X-API-KEY"),
        auth_param_name=_env("AUTH_PARAM_NAME", "api_key"),
        route_prefix=prefix,
        default_quota_limit=_env_int("DEFAULT_QUOTA_LIMIT", 250),
        quota_reset_day=reset_day,
        quota_reserve=_env_int("QUOTA_RESERVE", 0),
        strategy=strategy,
        max_retries=max(_env_int("MAX_RETRIES", 2), 0),
        refund_on=tuple(
            part.lower()
            for part in _env_csv("REFUND_ON", "connect,5xx,429,401")
        ),
        cooldown_base_seconds=_env_float("COOLDOWN_BASE_SECONDS", 10.0),
        cooldown_max_seconds=_env_float("COOLDOWN_MAX_SECONDS", 300.0),
        router_keys=parse_router_keys(_env("ROUTER_KEYS", "")),
        router_key_header=_env("ROUTER_KEY_HEADER", "X-Router-Key"),
        dashboard_public=_env_bool("DASHBOARD_PUBLIC", True),
        expose_account_label=_env_bool("EXPOSE_ACCOUNT_LABEL", True),
        cache_ttl_seconds=_env_float("CACHE_TTL_SECONDS", 0.0),
        cache_max_entries=_env_int("CACHE_MAX_ENTRIES", 512),
        rate_limit_per_minute=_env_float("RATE_LIMIT_PER_MINUTE", 0.0),
        rate_limit_burst=_env_float("RATE_LIMIT_BURST", 0.0),
        request_log_size=_env_int("REQUEST_LOG_SIZE", 500),
        account_seed=_env("SERP_ACCOUNTS", ""),
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def set_settings(settings: Settings | None) -> None:
    """Override the process-wide settings (tests / app factory)."""
    global _settings
    _settings = settings


def with_overrides(settings: Settings, **kwargs) -> Settings:
    return replace(settings, **kwargs)
