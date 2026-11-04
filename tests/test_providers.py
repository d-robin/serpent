"""Providers, chains and fallback routing."""

from __future__ import annotations

import httpx

from tests.conftest import ADMIN, CLIENT


def _add_provider(client, slug, base, **extra):
    r = client.post("/admin/providers", headers=ADMIN, json={"slug": slug, "base_url": base, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _add_account(client, key, provider_id, limit=10):
    r = client.post(
        "/admin/accounts",
        headers=ADMIN,
        json={"api_key": key, "label": key, "quota_limit": limit, "provider_id": provider_id},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_provider_crud_and_validation(make_client):
    client = make_client(lambda req: httpx.Response(200, json={}))
    p = _add_provider(client, "serper", "", preset="serper")
    assert p["base_url"] == "https://google.serper.dev"
    assert client.post("/admin/providers", headers=ADMIN, json={"slug": "serper", "base_url": "https://x.test"}).status_code == 409
    assert client.post("/admin/providers", headers=ADMIN, json={"slug": "Bad Slug!", "base_url": "https://x.test"}).status_code == 400
    assert client.post("/admin/providers", headers=ADMIN, json={"slug": "n", "base_url": "ftp://x"}).status_code == 400
    r = client.patch("/admin/providers/serper", headers=ADMIN, json={"enabled": False})
    assert r.json()["enabled"] is False
    assert client.delete("/admin/providers/serper", headers=ADMIN).status_code == 204


def test_named_route_uses_that_providers_accounts_and_auth(make_client):
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.url.host, dict(req.headers), dict(req.url.params)))
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)
    a = _add_provider(client, "alpha", "https://alpha.test", auth_style="header", auth_header_name="X-A")
    b = _add_provider(client, "beta", "https://beta.test", auth_style="query", auth_param_name="k")
    _add_account(client, "alpha-key", a["id"])
    _add_account(client, "beta-key", b["id"])

    r = client.post("/p/alpha/search", headers=CLIENT, json={"q": "x"})
    assert r.status_code == 200 and r.headers["x-router-provider"] == "alpha"
    r = client.post("/p/beta/search", headers=CLIENT, json={"q": "x"})
    assert r.status_code == 200 and r.headers["x-router-provider"] == "beta"
    assert seen[0][0] == "alpha.test" and seen[0][1]["x-a"] == "alpha-key"
    assert seen[1][0] == "beta.test" and seen[1][2]["k"] == "beta-key"
    assert client.post("/p/nope/search", headers=CLIENT, json={}).status_code == 404


def test_chain_falls_through_when_first_provider_is_dry_or_failing(make_client):
    def handler(req: httpx.Request):
        if req.url.host == "bad.test":
            return httpx.Response(503, json={"e": 1})
        return httpx.Response(200, json={"host": req.url.host})

    client = make_client(handler)
    dry = _add_provider(client, "dry", "https://dry.test")
    bad = _add_provider(client, "bad", "https://bad.test")
    good = _add_provider(client, "good", "https://good.test")
    _add_account(client, "k-dry", dry["id"], limit=0)
    _add_account(client, "k-bad", bad["id"])
    _add_account(client, "k-good", good["id"])

    r = client.post("/admin/chains", headers=ADMIN, json={"slug": "web", "steps": ["dry", "bad", "good"]})
    assert r.status_code == 201
    r = client.post("/p/web/search", headers=CLIENT, json={"q": "x"})
    assert r.status_code == 200
    assert r.headers["x-router-provider"] == "good"
    assert r.json()["host"] == "good.test"
    # unknown provider in a chain is rejected
    assert client.post("/admin/chains", headers=ADMIN, json={"slug": "c2", "steps": ["ghost"]}).status_code == 400


def test_chain_exhausted_returns_last_failure(make_client):
    client = make_client(lambda req: httpx.Response(503, json={"e": 1}))
    a = _add_provider(client, "a", "https://a.test")
    _add_account(client, "ka", a["id"])
    client.post("/admin/chains", headers=ADMIN, json={"slug": "only", "steps": ["a"]})
    r = client.post("/p/only/search", headers=CLIENT, json={})
    assert r.status_code == 503 and r.headers["x-router-error"] == "all_accounts_failed"


def test_default_route_switch_and_legacy_v1(make_client):
    hosts = []
    client = make_client(lambda req: (hosts.append(req.url.host), httpx.Response(200, json={}))[1])
    a = _add_provider(client, "alt", "https://alt.test")
    _add_account(client, "alt-key", a["id"])
    # legacy default provider (from env settings) has no accounts yet
    assert client.post("/v1/search", headers=CLIENT, json={}).status_code == 429
    assert client.put("/admin/default-route", headers=ADMIN, json={"route": "alt"}).status_code == 200
    assert client.post("/v1/search", headers=CLIENT, json={}).status_code == 200
    assert hosts[-1] == "alt.test"
    assert client.put("/admin/default-route", headers=ADMIN, json={"route": "missing"}).status_code == 404


def test_tunables_apply_and_validate(make_client):
    client = make_client(lambda req: httpx.Response(200, json={}))
    r = client.patch("/admin/tunables", headers=ADMIN, json={"strategy": "round_robin", "max_retries": 4})
    assert r.status_code == 200 and r.json()["strategy"] == "round_robin"
    assert client.patch("/admin/tunables", headers=ADMIN, json={"strategy": "nope"}).status_code == 400
    assert client.patch("/admin/tunables", headers=ADMIN, json={"bind_port": 1}).status_code == 400
    assert client.get("/api/status").json()["tunables"]["max_retries"] == 4
