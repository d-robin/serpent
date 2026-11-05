"""FastAPI application: quota-aware SERP proxy + management API + dashboard."""

from __future__ import annotations

import asyncio
import functools
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from . import (
    __version__,
    accounts,
    cache,
    contract,
    dashboard,
    db,
    metrics,
    provider_usage,
    providers,
    quota,
    requestlog,
    security,
    tunables,
    upstream,
)
from .config import VALID_STRATEGIES, Settings, get_settings, load_settings, set_settings
from .ratelimit import TokenBucket

log = logging.getLogger("serpent")

PROXY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _json(status_code: int, message: str, **extra) -> JSONResponse:
    payload = {"error": message, "status": status_code}
    payload.update(extra)
    return JSONResponse(payload, status_code=status_code)


def _add_quota_headers(headers: dict, agg: dict, settings: Settings) -> None:
    headers["x-quota-period"] = agg["period"]
    headers["x-quota-limit"] = str(agg["quota_limit_total"])
    headers["x-quota-used"] = str(agg["quota_used_total"])
    # "remaining" = credits not consumed this period.
    headers["x-quota-remaining"] = str(agg["quota_remaining_total"])
    # "available" = credits you can spend right now (excludes accounts that
    # are disabled, invalid, cooling down, or inside the reserve floor).
    headers["x-quota-available"] = str(agg["quota_available_total"])
    headers["x-quota-accounts"] = str(agg["accounts_usable"])
    headers["x-quota-reset"] = agg["resets_at"]
    headers["x-quota-reset-in"] = str(agg["resets_in_seconds"])


def _period(settings: Settings) -> str:
    return quota.current_period(reset_day=settings.quota_reset_day)


async def _db(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


def _cooldown_args(settings: Settings, multiplier: float = 1.0) -> dict:
    return {
        "base_seconds": settings.cooldown_base_seconds,
        "max_seconds": settings.cooldown_max_seconds,
        "multiplier": multiplier,
    }


# --------------------------------------------------------------------------
# app factory
# --------------------------------------------------------------------------


def create_app(
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    set_settings(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        metrics.setup_logging(settings.log_level)
        db.init_db(settings.db_path)
        await _db(providers.ensure_default, settings)
        await _db(tunables.load, settings)
        seeded = await _db(accounts.seed_accounts, settings.account_seed, settings.default_quota_limit)
        if seeded:
            log.info("seeded %s account(s)", seeded)
        if not settings.auth_enabled:
            log.warning(
                "ROUTER_KEYS is empty - the proxy is UNAUTHENTICATED. "
                "Set ROUTER_KEYS before exposing this host."
            )
        await _db(quota.purge_old_periods, 6)
        app.state.client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.upstream_timeout),
            verify=settings.upstream_verify_tls,
            follow_redirects=False,
            transport=transport,
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
        )
        app.state.started = datetime.now(timezone.utc)
        log.info(
            "serpent %s ready: providers=%s strategy=%s accounts=%s",
            __version__,
            len(await _db(providers.list_providers)) or "none yet",
            settings.strategy,
            (await _db(accounts.count_by_status)),
        )
        try:
            yield
        finally:
            await app.state.client.aclose()

    app = FastAPI(
        title="Serpent",
        version=__version__,
        docs_url="/docs" if not settings.auth_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if not settings.auth_enabled else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.counters = metrics.Counters()
    app.state.cache = cache.ResponseCache(
        settings.cache_ttl_seconds, settings.cache_max_entries
    )
    app.state.bucket = TokenBucket(
        settings.rate_limit_per_minute, settings.rate_limit_burst or None
    )
    prefix = settings.normalized_prefix()

    # ---- error handling --------------------------------------------------
    @app.exception_handler(security.AuthError)
    async def _auth_error(request: Request, exc: security.AuthError):
        headers = {"WWW-Authenticate": "RouterKey"} if exc.status_code == 401 else None
        return JSONResponse(
            {"error": exc.detail, "status": exc.status_code},
            status_code=exc.status_code,
            headers=headers,
        )

    # ---- health ----------------------------------------------------------
    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"status": "ok", "version": __version__}

    @app.get("/readyz", include_in_schema=False)
    async def readyz():
        agg = await _db(
            quota.aggregate,
            _period(settings),
            reset_day=settings.quota_reset_day,
            reserve_floor=settings.quota_reserve,
        )
        ready = agg["accounts_usable"] > 0
        return JSONResponse(
            {"ready": ready, **agg},
            status_code=200 if ready else 503,
        )

    # ---- status payload --------------------------------------------------
    def _status_payload() -> dict:
        period = _period(settings)
        snap = quota.snapshot(
            period, reset_day=settings.quota_reset_day, reserve_floor=settings.quota_reserve
        )
        counters = app.state.counters.snapshot()
        snap.update(
            {
                "version": __version__,
                "now": db.now_iso(),
                "upstream": providers.primary_upstream(),
                "auth_style": settings.auth_style,
                "strategy": settings.strategy,
                "max_retries": settings.max_retries,
                "refund_on": list(settings.refund_on),
                "quota_reserve": settings.quota_reserve,
                "auth_enabled": settings.auth_enabled,
                "dashboard_public": settings.dashboard_public,
                "uptime_seconds": app.state.counters.uptime_seconds,
                "cache": app.state.cache.stats(),
                "ratelimit": app.state.bucket.stats(),
                "counters": counters,
                "recent": requestlog.recent(40),
                "providers": [p.public() for p in providers.list_providers()],
                "chains": providers.list_chains(),
                "default_route": providers.get_default_route(),
                "tunables": tunables.current(settings),
                "routes": [prefix + "/*", "/v1/quota", "/api/status", "/healthz", "/readyz", "/metrics"],
            }
        )
        return snap

    @app.get("/api/status")
    async def api_status(request: Request):
        if not settings.dashboard_public:
            security.require(request, "read")
        return await _db(_status_payload)

    @app.get("/v1/status", include_in_schema=False)
    async def v1_status(request: Request):
        security.require(request, "read")
        return await _db(_status_payload)

    @app.get("/metrics", include_in_schema=False)
    async def prometheus(request: Request):
        if settings.auth_enabled:
            security.require(request, "read")
        period = _period(settings)
        snap = await _db(
            quota.snapshot,
            period,
            reset_day=settings.quota_reset_day,
            reserve_floor=settings.quota_reserve,
        )
        counters = app.state.counters.snapshot()
        lines: list[str] = []

        def metric(name: str, kind: str, help_text: str, samples: list[tuple[str, float]]):
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} {kind}")
            for label, value in samples:
                lines.append(f"{name}{label} {value}")

        metric(
            "serpent_quota_remaining",
            "gauge",
            "Credits available per account in the current period.",
            [
                (
                    f'{{account="{a["id"]}:{a["label"]}",status="{a["status"]}"}}',
                    a["available"],
                )
                for a in snap["accounts"]
            ],
        )
        metric(
            "serpent_quota_used",
            "gauge",
            "Credits consumed per account in the current period.",
            [
                (
                    f'{{account="{a["id"]}:{a["label"]}",status="{a["status"]}"}}',
                    a["used"],
                )
                for a in snap["accounts"]
            ],
        )
        metric(
            "serpent_accounts",
            "gauge",
            "Accounts by state.",
            [
                ('{state="total"}', snap["accounts_total"]),
                ('{state="active"}', snap["accounts_active"]),
                ('{state="usable"}', snap["accounts_usable"]),
                ('{state="invalid"}', snap["accounts_invalid"]),
                ('{state="cooldown"}', snap["accounts_on_cooldown"]),
            ],
        )
        metric(
            "serpent_requests_total",
            "counter",
            "Requests handled since process start.",
            [
                (f'{{result="{name}"}}', value)
                for name, value in sorted(counters.items())
                if name.startswith("proxy_")
            ]
            or [('{result="none"}', 0)],
        )
        metric(
            "serpent_quota_capacity",
            "gauge",
            "Aggregate capacity for the current period.",
            [
                ('{kind="limit"}', snap["quota_limit_total"]),
                ('{kind="used"}', snap["quota_used_total"]),
                ('{kind="available"}', snap["quota_available_total"]),
            ],
        )
        metric(
            "serpent_uptime_seconds",
            "gauge",
            "Process uptime.",
            [("", app.state.counters.uptime_seconds)],
        )
        return PlainTextResponse("\n".join(lines) + "\n")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def home(request: Request):
        if not settings.dashboard_public:
            security.require(request, "read")
        return HTMLResponse(dashboard.PAGE)

    # ---- contract: how to call this router (for apps and AI assistants) -------
    @app.get("/llms.txt", response_class=PlainTextResponse, include_in_schema=False)
    async def llms_txt(request: Request):
        return PlainTextResponse(contract.render_llms_txt(str(request.base_url).rstrip("/")))

    @app.get(prefix + "/contract", include_in_schema=False)
    async def get_contract(request: Request, format: str = "markdown"):
        security.require(request, "client")

        def gather():
            return (providers.list_providers(), providers.list_chains(),
                    providers.get_default_route())

        provs, chains, default = await _db(gather)
        doc = contract.build(settings, provs, chains, default, str(request.base_url).rstrip("/"))
        if format == "json":
            return JSONResponse(doc)
        return PlainTextResponse(contract.render_markdown(doc), media_type="text/markdown; charset=utf-8")

    # ---- quota read API --------------------------------------------------
    @app.get(prefix + "/quota")
    async def get_quota(request: Request, need: int | None = None):
        security.require(request, "read")
        period = _period(settings)
        agg = await _db(
            quota.aggregate,
            period,
            reset_day=settings.quota_reset_day,
            reserve_floor=settings.quota_reserve,
        )
        payload = {**agg, "can_serve": agg["accounts_usable"] > 0}
        if need is not None:
            allowed = agg["quota_available_total"] >= max(0, need)
            payload.update({"requested": need, "allowed": allowed})
            return JSONResponse(payload, status_code=200 if allowed else 409)
        return payload

    @app.post(prefix + "/quota/check")
    async def check_quota(request: Request):
        security.require(request, "read")
        count = 1
        try:
            body = await request.json()
            if isinstance(body, dict) and "count" in body:
                count = int(body["count"])
        except Exception:
            need = request.query_params.get("count") or request.query_params.get("need")
            if need is not None:
                count = int(need)
        count = max(0, count)
        period = _period(settings)
        agg = await _db(
            quota.aggregate,
            period,
            reset_day=settings.quota_reset_day,
            reserve_floor=settings.quota_reserve,
        )
        allowed = agg["quota_available_total"] >= count
        return JSONResponse(
            {"requested": count, "allowed": allowed, **agg},
            status_code=200 if allowed else 409,
        )

    @app.get(prefix + "/quota/accounts")
    async def quota_accounts(request: Request):
        security.require(request, "read")
        period = _period(settings)
        rows = await _db(
            quota.accounts_snapshot,
            period,
            reset_day=settings.quota_reset_day,
            reserve_floor=settings.quota_reserve,
        )
        hints = {a["id"]: a["key_hint"] for a in await _db(accounts.list_accounts)}
        for row in rows:
            row["key_hint"] = hints.get(row["id"], "****")
        return {"period": period, "accounts": rows}

    # ---- admin API -------------------------------------------------------
    @app.get("/admin/requests")
    async def admin_requests(
        request: Request,
        limit: int = 50,
        offset: int = 0,
        outcome: str = "",
        provider: str = "",
        q: str = "",
    ):
        security.require(request, "read")
        page = await _db(
            lambda: requestlog.search(
                limit=limit, offset=offset, outcome=outcome, provider=provider, text=q[:100]
            )
        )
        return {**page, "limit": max(1, min(limit, 200)), "offset": max(0, offset),
                "kept": settings.request_log_size}

    @app.get("/admin/accounts")
    async def admin_list(request: Request):
        security.require(request, "admin")
        period = _period(settings)
        rows = await _db(
            quota.accounts_snapshot,
            period,
            reset_day=settings.quota_reset_day,
            reserve_floor=settings.quota_reserve,
        )
        meta = {a["id"]: a for a in await _db(accounts.list_accounts)}
        for row in rows:
            row["key_hint"] = meta.get(row["id"], {}).get("key_hint", "****")
        return {"period": period, "accounts": rows}

    @app.post("/admin/accounts", status_code=201)
    async def admin_add(request: Request):
        security.require(request, "admin")
        try:
            body = await request.json()
        except Exception:
            return _json(400, "JSON body required")
        try:
            account = await _db(
                accounts.add_account,
                str(body.get("api_key", "")),
                label=str(body.get("label", "")),
                quota_limit=int(body.get("quota_limit", settings.default_quota_limit)),
                notes=body.get("notes"),
                provider_id=int(body["provider_id"]) if body.get("provider_id") else None,
            )
        except accounts.DuplicateKey as exc:
            return _json(409, str(exc))
        except (accounts.AccountError, TypeError, ValueError) as exc:
            return _json(400, str(exc))
        log.info("account added id=%s label=%s", account["id"], account["label"])
        return account

    @app.get("/admin/accounts/{account_id}/provider-usage")
    async def admin_provider_usage(account_id: int, request: Request):
        """What the provider says this key's plan allows (free call, not counted by Serpent)."""
        security.require(request, "admin")

        def lookup():
            row = db.connection().execute(
                "SELECT api_key, provider_id FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
            if row is None:
                raise accounts.NotFound(f"account {account_id} not found")
            provider = providers.get_provider(row["provider_id"]) if row["provider_id"] else None
            return row["api_key"], provider

        try:
            api_key, provider = await _db(lookup)
        except accounts.NotFound as exc:
            return _json(404, str(exc))
        if provider is None:
            return {"supported": False, "error": None, "note": "this account has no provider"}
        return await provider_usage.fetch(app.state.client, provider, api_key)

    @app.patch("/admin/accounts/{account_id}")
    async def admin_update(account_id: int, request: Request):
        security.require(request, "admin")
        try:
            body = await request.json()
        except Exception:
            return _json(400, "JSON body required")
        try:
            account = await _db(accounts.update_account, account_id, **body)
        except accounts.NotFound as exc:
            return _json(404, str(exc))
        except accounts.DuplicateKey as exc:
            return _json(409, str(exc))
        except accounts.AccountError as exc:
            return _json(400, str(exc))
        return account

    @app.delete("/admin/accounts/{account_id}", status_code=204)
    async def admin_delete(account_id: int, request: Request):
        security.require(request, "admin")
        try:
            await _db(accounts.delete_account, account_id)
        except accounts.NotFound as exc:
            return _json(404, str(exc))
        log.info("account deleted id=%s", account_id)
        return Response(status_code=204)

    @app.post("/admin/accounts/{account_id}/reset")
    async def admin_reset_account(account_id: int, request: Request):
        security.require(request, "admin")
        period = _period(settings)
        try:
            await _db(accounts.get_account, account_id)
        except accounts.NotFound as exc:
            return _json(404, str(exc))
        await _db(quota.reset_account, account_id, period)
        return {"ok": True, "account_id": account_id, "period": period}

    @app.post("/admin/reset")
    async def admin_reset_all(request: Request):
        security.require(request, "admin")
        period = _period(settings)
        count = await _db(quota.reset_all, period)
        return {"ok": True, "accounts": count, "period": period}

    @app.post("/admin/cache/clear")
    async def admin_cache_clear(request: Request):
        security.require(request, "admin")
        removed = app.state.cache.clear()
        return {"ok": True, "entries_cleared": removed}

    @app.get("/admin/health-check")
    async def admin_health(request: Request):
        """Non-charging liveness of the upstream host (no account credit used)."""
        security.require(request, "admin")
        started = time.perf_counter()
        url = await _db(providers.primary_upstream)
        if not url:
            return {"reachable": False, "status": None, "latency_ms": 0.0, "url": "",
                    "detail": "no provider configured yet"}
        try:
            resp = await app.state.client.get(url + "/", timeout=5.0)
            reachable = True
            status = resp.status_code
        except httpx.HTTPError as exc:
            reachable = False
            status = None
            log.warning("upstream unreachable: %s", exc)
        return {
            "reachable": reachable,
            "status": status,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "url": url,
        }

    @app.get("/admin/config")
    async def admin_config(request: Request):
        security.require(request, "admin")
        return {
            "upstream_base_url": await _db(providers.primary_upstream),
            "route_prefix": prefix,
            "auth_style": settings.auth_style,
            "auth_header_name": settings.auth_header_name
            if settings.auth_style == "header"
            else None,
            "auth_param_name": settings.auth_param_name
            if settings.auth_style == "query"
            else None,
            "strategy": settings.strategy,
            "max_retries": settings.max_retries,
            "refund_on": list(settings.refund_on),
            "default_quota_limit": settings.default_quota_limit,
            "quota_reset_day": settings.quota_reset_day,
            "quota_reserve": settings.quota_reserve,
            "request_log_size": settings.request_log_size,
            "cache": app.state.cache.stats(),
            "ratelimit": app.state.bucket.stats(),
            "auth_enabled": settings.auth_enabled,
            "router_keys_configured": len(settings.router_keys),
            "db_path": settings.db_path,
        }

    # ---- providers, chains, routing, tunables ----------------------------
    def _guard(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except providers.NotFound as exc:
                return _json(404, str(exc))
            except providers.Conflict as exc:
                return _json(409, str(exc))
            except (providers.ProviderError, tunables.TunableError, TypeError, ValueError) as exc:
                return _json(400, str(exc))

        return wrapper

    async def _body(request: Request) -> dict:
        try:
            data = await request.json()
        except Exception:
            raise providers.ProviderError("JSON body required") from None
        if not isinstance(data, dict):
            raise providers.ProviderError("JSON object required")
        return data

    @app.get("/admin/presets")
    async def admin_presets(request: Request):
        security.require(request, "admin")
        return {"presets": providers.PRESETS, "strategies": list(VALID_STRATEGIES)}

    @app.get("/admin/providers")
    async def admin_providers(request: Request):
        security.require(request, "admin")
        return {
            "providers": [p.public() for p in await _db(providers.list_providers)],
            "chains": await _db(providers.list_chains),
            "default_route": await _db(providers.get_default_route),
        }

    @app.post("/admin/providers", status_code=201)
    @_guard
    async def admin_provider_add(request: Request):
        security.require(request, "admin")
        b = await _body(request)
        prov = await _db(
            lambda: providers.add_provider(
                str(b.get("slug", "")),
                name=str(b.get("name", "")),
                preset=b.get("preset") or None,
                base_url=str(b.get("base_url", "")),
                auth_style=str(b.get("auth_style", "")),
                auth_header_name=str(b.get("auth_header_name", "")),
                auth_param_name=str(b.get("auth_param_name", "")),
            )
        )
        return prov.public()

    @app.patch("/admin/providers/{ref}")
    @_guard
    async def admin_provider_update(ref: str, request: Request):
        security.require(request, "admin")
        b = await _body(request)
        prov = await _db(lambda: providers.update_provider(ref, **b))
        return prov.public()

    @app.delete("/admin/providers/{ref}", status_code=204)
    @_guard
    async def admin_provider_delete(ref: str, request: Request):
        security.require(request, "admin")
        await _db(providers.delete_provider, ref)
        return Response(status_code=204)

    @app.post("/admin/chains", status_code=201)
    @_guard
    async def admin_chain_add(request: Request):
        security.require(request, "admin")
        b = await _body(request)
        return await _db(
            lambda: providers.add_chain(
                str(b.get("slug", "")), b.get("steps") or [], name=str(b.get("name", ""))
            )
        )

    @app.patch("/admin/chains/{ref}")
    @_guard
    async def admin_chain_update(ref: str, request: Request):
        security.require(request, "admin")
        b = await _body(request)
        return await _db(lambda: providers.update_chain(ref, **b))

    @app.delete("/admin/chains/{ref}", status_code=204)
    @_guard
    async def admin_chain_delete(ref: str, request: Request):
        security.require(request, "admin")
        await _db(providers.delete_chain, ref)
        return Response(status_code=204)

    @app.put("/admin/default-route")
    @_guard
    async def admin_default_route(request: Request):
        security.require(request, "admin")
        b = await _body(request)
        slug = await _db(providers.set_default_route, str(b.get("route", "")))
        app.state.cache.clear()
        return {"default_route": slug}

    @app.get("/admin/tunables")
    async def admin_tunables_get(request: Request):
        security.require(request, "admin")
        return tunables.current(settings)

    @app.patch("/admin/tunables")
    @_guard
    async def admin_tunables_patch(request: Request):
        security.require(request, "admin")
        b = await _body(request)
        return await _db(tunables.apply, settings, b)

    # ---- the proxy itself ------------------------------------------------
    @app.api_route("/p/{slug}/{tail:path}", methods=PROXY_METHODS, include_in_schema=False)
    async def proxy_named(request: Request, slug: str, tail: str):
        return await _handle_proxy(request, tail, "/p/" + slug, settings, route=slug)

    @app.api_route(prefix + "/{tail:path}", methods=PROXY_METHODS, include_in_schema=False)
    async def proxy(request: Request, tail: str):
        return await _handle_proxy(request, tail, prefix, settings)

    def _route_providers(slug: str) -> list[providers.Provider]:
        if slug == "default" and not providers.route_exists("default"):
            providers.ensure_default(settings)
        return providers.resolve(slug)

    async def _handle_proxy(
        request: Request,
        tail: str,
        prefix: str,
        settings: Settings,
        route: str | None = None,
    ) -> Response:
        security.require(request, "client")
        state = app.state
        counters: metrics.Counters = state.counters
        request_id = (request.headers.get("x-request-id") or uuid.uuid4().hex[:12]).strip()
        client_id = security.key_fingerprint(security.present_key(request, settings))

        ok, retry_after = state.bucket.take()
        if not ok:
            counters.inc("proxy_rate_limited")
            return _json(
                429,
                "router rate limit exceeded",
                retry_after_seconds=retry_after,
            )

        try:
            tail = upstream.normalize_tail(tail)
        except upstream.BadTarget as exc:
            return _json(400, str(exc))

        if request.method in ("POST", "PUT", "PATCH") and request.headers.get(
            "content-length"
        ):
            try:
                declared = int(request.headers["content-length"])
            except ValueError:
                declared = 0
            if declared > settings.max_body_bytes:
                return _json(413, f"body larger than {settings.max_body_bytes} bytes")
        body = await request.body()
        if len(body) > settings.max_body_bytes:
            return _json(413, f"body larger than {settings.max_body_bytes} bytes")

        query_items = list(request.query_params.multi_items())
        params = upstream.build_params(settings, query_items)
        period = _period(settings)
        base_settings = settings

        route_slug = route or await _db(providers.get_default_route)
        try:
            chain = await _db(_route_providers, route_slug)
        except providers.NotFound as exc:
            if route is None and not await _db(providers.list_providers):
                return _json(503, "no provider configured yet - open /ui (Snake Charmer) "
                                  "or run `serpent providers add` to add one")
            return _json(404, str(exc))
        if not chain:
            return _json(503, f"route {route_slug!r} has no enabled providers")

        # ---- cache lookup (costs no quota) --------------------------------
        cache_key = None
        if state.cache.enabled and request.method in ("GET", "POST"):
            cache_key = state.cache.make_key(
                request.method, f"{route_slug}:{tail}", sorted(params), body
            )
            hit = state.cache.get(cache_key)
            if hit is not None:
                agg = await _db(
                    quota.aggregate,
                    period,
                    reset_day=settings.quota_reset_day,
                    reserve_floor=settings.quota_reserve,
                )
                headers = dict(hit.headers)
                _add_quota_headers(headers, agg, settings)
                headers["x-cache"] = "HIT"
                headers["x-request-id"] = request_id
                counters.inc("proxy_cached")
                await _db(
                    requestlog.record,
                    account_id=None,
                    account="cache",
                    client=client_id,
                    method=request.method,
                    path=requestlog.logged_path(prefix + tail, query_items),
                    status=hit.status_code,
                    latency_ms=0.0,
                    cached=True,
                    keep=settings.request_log_size,
                )
                return Response(
                    content=hit.body, status_code=hit.status_code, headers=headers
                )

        # ---- one provider: reserve -> forward -> retry -> settle ------------
        outcome = {"final": False}

        async def _attempt(provider: providers.Provider) -> Response:
            settings = provider.apply(base_settings)
            params = upstream.build_params(settings, query_items)
            max_attempts = max(0, settings.max_retries) + 1
            tried: set[int] = set()
            attempts = 0
            last_upstream: httpx.Response | None = None
            last_error: str | None = None
            pending: quota.Reservation | None = None
            request_started = time.perf_counter()

            try:
                for attempt in range(1, max_attempts + 1):
                    reservation = await _db(
                        quota.reserve,
                        period=period,
                        strategy=settings.strategy,
                        exclude=tried,
                        provider_id=provider.id,
                        reserve_floor=settings.quota_reserve,
                        now=db.now_iso(),
                    )
                    if reservation is None:
                        break
                    pending = reservation
                    attempts = attempt
                    attempt_started = time.perf_counter()
                    url = upstream.build_url(settings, tail)
                    query = upstream.merge_query(params, settings, reservation.api_key)
                    headers = upstream.build_headers(
                        settings, list(request.headers.items()), reservation.api_key
                    )

                    try:
                        call_kwargs: dict = {
                            "headers": headers,
                            "content": body if body else None,
                        }
                        if query:
                            call_kwargs["params"] = httpx.QueryParams(query)
                        response = await state.client.request(
                            request.method, url, **call_kwargs
                        )
                    except httpx.HTTPError as exc:
                        latency = (time.perf_counter() - attempt_started) * 1000
                        pending = None
                        refund = settings.refund("connect")
                        await _db(
                            quota.settle_failed,
                            reservation.account_id,
                            period,
                            latency,
                            refund=refund,
                        )
                        await _db(
                            accounts.mark_failure,
                            reservation.account_id,
                            error=f"{type(exc).__name__}: {exc}",
                            **_cooldown_args(settings),
                        )
                        tried.add(reservation.account_id)
                        last_error = f"{type(exc).__name__}: {exc}"
                        counters.inc("proxy_connect_error")
                        log.warning(
                            "upstream connect error account=%s attempt=%s: %s",
                            reservation.label,
                            attempt,
                            exc,
                            extra={"request_id": request_id, "attempt": attempt},
                        )
                        continue

                    latency = (time.perf_counter() - attempt_started) * 1000
                    pending = None
                    kind = upstream.classify(response.status_code)
                    log.info(
                        "upstream %s account=%s status=%s ms=%.1f",
                        request.method,
                        reservation.label,
                        response.status_code,
                        latency,
                        extra={
                            "request_id": request_id,
                            "path": prefix + tail,
                            "status": response.status_code,
                            "account": reservation.label,
                            "latency_ms": round(latency, 1),
                            "attempt": attempt,
                            "client": client_id,
                        },
                    )

                    if kind == "ok":
                        await _db(
                            quota.settle_ok, reservation.account_id, period, latency
                        )
                        await _db(accounts.mark_success, reservation.account_id)
                        counters.inc("proxy_ok")
                        agg = await _db(
                            quota.aggregate,
                            period,
                            reset_day=settings.quota_reset_day,
                            reserve_floor=settings.quota_reserve,
                        )
                        out_headers = {
                            name: value
                            for name, value in response.headers.items()
                            if name.lower() not in upstream.RESPONSE_DROP
                        }
                        _add_quota_headers(out_headers, agg, settings)
                        out_headers["x-request-id"] = request_id
                        out_headers["x-router-attempts"] = str(attempt)
                        if settings.expose_account_label:
                            out_headers["x-router-account"] = reservation.label
                        if cache_key is not None:
                            state.cache.put(
                                cache_key, response.status_code, response.content, out_headers
                            )
                        await _db(
                            requestlog.record,
                            account_id=reservation.account_id,
                            account=reservation.label,
                            client=client_id,
                            method=request.method,
                            path=requestlog.logged_path(prefix + tail, query_items),
                            status=response.status_code,
                            latency_ms=latency,
                            keep=settings.request_log_size,
                provider=provider.slug,
                        )
                        outcome["final"] = True
                        return Response(
                            content=b"" if request.method == "HEAD" else response.content,
                            status_code=response.status_code,
                            headers=out_headers,
                        )

                    if kind in ("401", "429", "5xx"):
                        refund = settings.refund(kind)
                        await _db(
                            quota.settle_failed,
                            reservation.account_id,
                            period,
                            latency,
                            refund=refund,
                        )
                        if kind == "401":
                            await _db(
                                accounts.mark_invalid,
                                reservation.account_id,
                                f"HTTP {response.status_code}: key rejected",
                            )
                            counters.inc("proxy_key_invalid")
                        else:
                            await _db(
                                accounts.mark_failure,
                                reservation.account_id,
                                error=f"HTTP {response.status_code}",
                                **_cooldown_args(
                                    settings, 2.0 if kind == "429" else 1.0
                                ),
                            )
                            counters.inc(f"proxy_upstream_{kind}")
                        tried.add(reservation.account_id)
                        last_upstream = response
                        continue

                    # Remaining 4xx: the caller's request is at fault.  Providers
                    # bill these, so the credit stays consumed and we do not retry.
                    await _db(
                        quota.settle_failed,
                        reservation.account_id,
                        period,
                        latency,
                        refund=False,
                    )
                    counters.inc("proxy_client_error")
                    agg = await _db(
                        quota.aggregate,
                        period,
                        reset_day=settings.quota_reset_day,
                        reserve_floor=settings.quota_reserve,
                    )
                    out_headers = {
                        name: value
                        for name, value in response.headers.items()
                        if name.lower() not in upstream.RESPONSE_DROP
                    }
                    _add_quota_headers(out_headers, agg, settings)
                    out_headers["x-request-id"] = request_id
                    out_headers["x-router-attempts"] = str(attempt)
                    await _db(
                        requestlog.record,
                        account_id=reservation.account_id,
                        account=reservation.label,
                        client=client_id,
                        method=request.method,
                        path=requestlog.logged_path(prefix + tail, query_items),
                        status=response.status_code,
                        latency_ms=latency,
                        error="client error passed through",
                        keep=settings.request_log_size,
                provider=provider.slug,
                    )
                    outcome["final"] = True
                    return Response(
                        content=b"" if request.method == "HEAD" else response.content,
                        status_code=response.status_code,
                        headers=out_headers,
                    )
            finally:
                if pending is not None:
                    await _db(quota.release_in_flight, pending.account_id, period)

            total_latency = (time.perf_counter() - request_started) * 1000

            # Every account we tried failed for a reason that is not the caller's.
            if last_upstream is not None:
                counters.inc("proxy_exhausted")
                agg = await _db(
                    quota.aggregate,
                    period,
                    reset_day=settings.quota_reset_day,
                    reserve_floor=settings.quota_reserve,
                )
                out_headers = {
                    name: value
                    for name, value in last_upstream.headers.items()
                    if name.lower() not in upstream.RESPONSE_DROP
                }
                _add_quota_headers(out_headers, agg, settings)
                out_headers["x-request-id"] = request_id
                out_headers["x-router-attempts"] = str(attempts)
                out_headers["x-router-error"] = "all_accounts_failed"
                await _db(
                    requestlog.record,
                    account_id=None,
                    account=None,
                    client=client_id,
                    method=request.method,
                    path=requestlog.logged_path(prefix + tail, query_items),
                    status=last_upstream.status_code,
                    latency_ms=total_latency,
                    error=last_error or "all accounts failed",
                    keep=settings.request_log_size,
                provider=provider.slug,
                )
                return Response(
                    content=b"" if request.method == "HEAD" else last_upstream.content,
                    status_code=last_upstream.status_code,
                    headers=out_headers,
                )

            if last_error is not None:
                counters.inc("proxy_exhausted")
                await _db(
                    requestlog.record,
                    account_id=None,
                    account=None,
                    client=client_id,
                    method=request.method,
                    path=requestlog.logged_path(prefix + tail, query_items),
                    status=502,
                    latency_ms=total_latency,
                    error=last_error,
                    keep=settings.request_log_size,
                provider=provider.slug,
                )
                return _json(
                    502,
                    "upstream unreachable on every available account",
                    attempts=attempts,
                    detail=last_error,
                )

            # Nothing left: out of quota (or no accounts configured at all).
            counters.inc("proxy_out_of_quota")
            agg = await _db(
                quota.aggregate,
                period,
                reset_day=settings.quota_reset_day,
                reserve_floor=settings.quota_reserve,
            )
            await _db(
                requestlog.record,
                account_id=None,
                account=None,
                client=client_id,
                method=request.method,
                path=requestlog.logged_path(prefix + tail, query_items),
                status=429,
                latency_ms=total_latency,
                error="quota exhausted",
                keep=settings.request_log_size,
                provider=provider.slug,
            )
            return JSONResponse(
                {
                    "error": "quota exhausted",
                    "status": 429,
                    "detail": "no account has a usable credit left in this period",
                    "accounts_total": agg["accounts_total"],
                    "accounts_usable": agg["accounts_usable"],
                    "period": agg["period"],
                    "resets_at": agg["resets_at"],
                    "resets_in_seconds": agg["resets_in_seconds"],
                },
                status_code=429,
                headers={"Retry-After": str(max(1, agg["resets_in_seconds"]))},
            )

        last: Response | None = None
        for position, provider in enumerate(chain):
            response = await _attempt(provider)
            response.headers["x-router-provider"] = provider.slug
            if outcome["final"]:
                if position:
                    counters.inc("proxy_fell_back")
                return response
            last = response
        assert last is not None
        return last

    # ---- Snake Charmer (admin UI) ---------------------------------------
    ui_dir = Path(__file__).parent / "ui_dist"
    if (ui_dir / "index.html").is_file():
        app.mount("/ui", StaticFiles(directory=ui_dir, html=True), name="ui")
    else:

        @app.get("/ui", include_in_schema=False)
        @app.get("/ui/{rest:path}", include_in_schema=False)
        async def ui_missing(rest: str = ""):
            return HTMLResponse(UI_MISSING_PAGE)

    return app


UI_MISSING_PAGE = """<!doctype html><meta charset="utf-8"><title>Snake Charmer</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<body style="font:16px/1.5 system-ui;background:#0b0f14;color:#e6edf3;max-width:36rem;margin:12vh auto;padding:0 1rem">
<h1>Snake Charmer isn&rsquo;t built yet</h1>
<p>The admin UI is a static bundle that is not part of this checkout. Build it once:</p>
<pre style="background:#121a23;padding:1rem;border-radius:8px">cd ui &amp;&amp; npm ci &amp;&amp; npm run build</pre>
<p>Then reload this page. The API and the <a style="color:#7c9cff" href="/">basic dashboard</a> work without it.</p>
</body>"""


app = create_app()


def _serve() -> None:  # pragma: no cover - exercised via the uvicorn CLI
    import uvicorn

    settings = load_settings()
    uvicorn.run(
        "serpent.main:app",
        host=settings.bind_host,
        port=settings.bind_port,
        log_level=settings.log_level,
        access_log=False,
        proxy_headers=settings.trust_proxy,
        forwarded_allow_ips="*" if settings.trust_proxy else None,
    )


if __name__ == "__main__":  # pragma: no cover
    _serve()
