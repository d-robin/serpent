"""Auth, admin endpoints, quota API, dashboard and metrics."""

from __future__ import annotations

from dataclasses import replace

from tests.conftest import ADMIN, CLIENT, READ


def _add(client, label="acct", key="key-1", limit=250):
    resp = client.post(
        "/admin/accounts",
        headers=ADMIN,
        json={"label": label, "api_key": key, "quota_limit": limit},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ------------------------------------------------------------------- auth


def test_missing_router_key_is_rejected(make_client):
    client = make_client()
    assert client.get("/v1/search?q=x").status_code == 401


def test_wrong_router_key_is_rejected(make_client):
    client = make_client()
    resp = client.get("/v1/search?q=x", headers={"X-Router-Key": "nope"})
    assert resp.status_code == 401


def test_read_role_cannot_use_the_proxy(make_client):
    client = make_client()
    resp = client.get("/v1/search?q=x", headers=READ)
    assert resp.status_code == 403


def test_read_role_can_read_quota(make_client):
    client = make_client()
    resp = client.get("/v1/quota", headers=READ)
    assert resp.status_code == 200
    assert resp.json()["quota_limit_total"] == 0


def test_bearer_token_is_accepted(make_client):
    client = make_client()
    resp = client.get("/v1/quota", headers={"Authorization": "Bearer test-read"})
    assert resp.status_code == 200


def test_admin_required_for_mutations(make_client):
    client = make_client()
    resp = client.post(
        "/admin/accounts", headers=CLIENT, json={"api_key": "k", "quota_limit": 5}
    )
    assert resp.status_code == 403


def test_open_mode_when_no_keys_configured(make_client, settings):
    open_settings = replace(settings, router_keys={})
    client = make_client(settings_override=open_settings)
    _add(client)
    resp = client.get("/v1/quota")
    assert resp.status_code == 200
    assert resp.json()["accounts_total"] == 1


# ------------------------------------------------------------------ admin


def test_account_lifecycle(make_client):
    client = make_client()
    account = _add(client, label="first", key="k1", limit=100)
    assert account["key_hint"] == "****"
    assert account["quota_limit"] == 100

    duplicate = client.post(
        "/admin/accounts", headers=ADMIN, json={"api_key": "k1", "quota_limit": 5}
    )
    assert duplicate.status_code == 409

    patched = client.patch(
        "/admin/accounts/1", headers=ADMIN, json={"status": "disabled", "label": "renamed"}
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "disabled"
    assert patched.json()["label"] == "renamed"

    listed = client.get("/admin/accounts", headers=ADMIN).json()["accounts"]
    assert listed[0]["status"] == "disabled"

    assert client.delete("/admin/accounts/1", headers=ADMIN).status_code == 204
    assert client.get("/admin/accounts", headers=ADMIN).json()["accounts"] == []
    assert client.delete("/admin/accounts/99", headers=ADMIN).status_code == 404


def test_account_validation_errors(make_client):
    client = make_client()
    assert (
        client.post("/admin/accounts", headers=ADMIN, json={"api_key": ""}).status_code
        == 400
    )
    assert (
        client.post(
            "/admin/accounts", headers=ADMIN, json={"api_key": "k", "quota_limit": -3}
        ).status_code
        == 400
    )
    assert (
        client.patch("/admin/accounts/1", headers=ADMIN, json={"status": "bogus"}).status_code
        == 400
    )
    assert (
        client.patch("/admin/accounts/99", headers=ADMIN, json={"status": "active"}).status_code
        == 404
    )


def test_admin_config_hides_secrets(make_client, settings):
    client = make_client()
    body = client.get("/admin/config", headers=ADMIN).json()
    assert body["upstream_base_url"] == "https://upstream.test"
    assert body["auth_enabled"] is True
    assert "key-1" not in str(body)
    assert "test-admin" not in str(body)


def test_reset_endpoints(make_client):
    client = make_client()
    _add(client)
    assert client.post("/admin/reset", headers=ADMIN).status_code == 200
    assert client.post("/admin/accounts/1/reset", headers=ADMIN).status_code == 200
    assert client.post("/admin/accounts/42/reset", headers=ADMIN).status_code == 404


# ------------------------------------------------------------------ quota


def test_quota_endpoints_report_and_gate(make_client, settings):
    client = make_client(settings_override=replace(settings, default_quota_limit=3))
    _add(client, limit=3)

    quota_body = client.get("/v1/quota", headers=CLIENT).json()
    assert quota_body["quota_limit_total"] == 3
    assert quota_body["quota_available_total"] == 3
    assert quota_body["can_serve"] is True

    assert client.get("/v1/quota?need=3", headers=CLIENT).status_code == 200
    assert client.get("/v1/quota?need=4", headers=CLIENT).status_code == 409

    check = client.post("/v1/quota/check", headers=CLIENT, json={"count": 2})
    assert check.status_code == 200 and check.json()["allowed"] is True
    assert client.post("/v1/quota/check", headers=CLIENT, json={"count": 9}).status_code == 409

    per_account = client.get("/v1/quota/accounts", headers=CLIENT).json()
    assert per_account["accounts"][0]["key_hint"] == "****ey-1"
    assert len(per_account["accounts"]) == 1


def test_quota_check_accepts_query_param(make_client):
    client = make_client()
    _add(client, limit=5)
    assert client.post("/v1/quota/check?count=1", headers=CLIENT).status_code == 200


# -------------------------------------------------------- dashboard / ops


def test_dashboard_is_public_and_renders_settings(make_client):
    client = make_client()
    _add(client, label="visible")
    page = client.get("/")
    assert page.status_code == 200
    assert "SERP" in page.text
    assert "auto-refresh" in page.text
    status = client.get("/api/status").json()
    assert status["accounts"][0]["label"] == "visible"
    assert status["strategy"] == "most_remaining"
    assert "cache" in status and "ratelimit" in status


def test_private_dashboard_requires_a_key(make_client, settings):
    client = make_client(settings_override=replace(settings, dashboard_public=False))
    assert client.get("/").status_code == 401
    assert client.get("/api/status").status_code == 401
    assert client.get("/", headers=READ).status_code == 200
    assert client.get("/api/status", headers=READ).status_code == 200


def test_health_and_metrics(make_client):
    client = make_client()
    _add(client, label="one", limit=10)

    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/readyz").status_code == 200

    metrics = client.get("/metrics", headers=READ)
    assert metrics.status_code == 200
    body = metrics.text
    assert "serpent_quota_remaining{" in body
    assert 'account="1:one"' in body
    assert "serpent_accounts{" in body
    assert "serpent_quota_capacity{" in body


def test_readyz_fails_with_no_usable_accounts(make_client):
    client = make_client()
    assert client.get("/readyz").status_code == 503


def test_cache_clear_endpoint(make_client, settings):
    client = make_client(settings_override=replace(settings, cache_ttl_seconds=30))
    resp = client.post("/admin/cache/clear", headers=ADMIN)
    assert resp.json()["entries_cleared"] == 0


def test_unknown_admin_route_404s(make_client):
    client = make_client()
    assert client.get("/admin/nope", headers=ADMIN).status_code == 404
