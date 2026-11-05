"""End-to-end proxy behaviour against a mocked SERP provider."""

from __future__ import annotations

from dataclasses import replace

import httpx
import pytest

from serpent import quota, upstream
from tests.conftest import ADMIN, CLIENT


def _add(client, label="acct", key="key-1", limit=10):
    resp = client.post(
        "/admin/accounts",
        headers=ADMIN,
        json={"label": label, "api_key": key, "quota_limit": limit},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _capture(status_map):
    """responder that records requests and answers per (path, key) rule."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        rule = status_map(request, len(seen))
        if isinstance(rule, httpx.Response):
            return rule
        return httpx.Response(rule, json={"organic": [{"title": "ok"}]})

    return handler, seen


def test_successful_proxy_consumes_one_credit(make_client, settings):
    handler, seen = _capture(lambda req, n: 200)
    client = make_client(handler)
    _add(client, limit=10)

    resp = client.post("/v1/search", headers=CLIENT, json={"q": "raspberry pi"})

    assert resp.status_code == 200
    assert resp.json()["organic"][0]["title"] == "ok"
    assert resp.headers["x-quota-remaining"] == "9"
    assert resp.headers["x-quota-used"] == "1"
    assert resp.headers["x-router-attempts"] == "1"
    assert resp.headers["x-router-account"] == "acct"
    assert len(seen) == 1
    # the provider key is injected and the caller's router key is not leaked
    assert seen[0].headers["x-api-key"] == "key-1"
    assert "x-router-key" not in {k.lower() for k in seen[0].headers}
    assert seen[0].method == "POST"
    assert str(seen[0].url) == "https://upstream.test/search"


def test_query_style_auth_injects_api_key_param(make_client, settings):
    from tests.conftest import ADMIN as A

    handler, seen = _capture(lambda req, n: 200)
    query_settings = replace(
        settings, auth_style="query", auth_param_name="api_key"
    )
    client = make_client(handler, settings_override=query_settings)
    client.post(
        "/admin/accounts",
        headers=A,
        json={"label": "q", "api_key": "secret-key", "quota_limit": 5},
    )

    resp = client.get("/v1/search?q=hello&gl=us", headers=CLIENT)

    assert resp.status_code == 200
    url = str(seen[0].url)
    assert "api_key=secret-key" in url
    assert "q=hello" in url and "gl=us" in url
    assert "x-api-key" not in {k.lower() for k in seen[0].headers}


def test_bearer_style_auth(make_client, settings):
    handler, seen = _capture(lambda req, n: 200)
    client = make_client(handler, settings_override=replace(settings, auth_style="bearer"))
    _add(client)

    client.post("/v1/search", headers=CLIENT, json={"q": "x"})

    assert seen[0].headers["authorization"] == "Bearer key-1"


def test_401_marks_the_key_invalid_and_fails_over(make_client, settings):
    def rule(request, n):
        return 401 if request.headers["x-api-key"] == "bad" else 200

    handler, seen = _capture(rule)
    client = make_client(handler)
    _add(client, label="bad", key="bad", limit=10)
    _add(client, label="good", key="good", limit=10)

    resp = client.post("/v1/search", headers=CLIENT, json={"q": "x"})

    assert resp.status_code == 200
    assert resp.headers["x-router-attempts"] == "2"
    accounts_list = client.get("/admin/accounts", headers=ADMIN).json()["accounts"]
    by_label = {a["label"]: a for a in accounts_list}
    assert by_label["bad"]["status"] == "invalid"
    assert by_label["bad"]["used"] == 0  # refunded
    assert by_label["good"]["used"] == 1
    assert len(seen) == 2


def test_500_on_every_account_refunds_and_reports(make_client, settings):
    handler, seen = _capture(lambda req, n: 503)
    client = make_client(handler)
    _add(client, label="a", key="k1")
    _add(client, label="b", key="k2")

    resp = client.post("/v1/search", headers=CLIENT, json={"q": "x"})

    assert resp.status_code == 503
    assert resp.headers["x-router-error"] == "all_accounts_failed"
    assert resp.headers["x-router-attempts"] == "2"  # only two accounts exist
    snapshot = quota.snapshot(quota.current_period())
    assert snapshot["quota_used_total"] == 0
    assert snapshot["requests_refunded"] == 2


def test_429_cools_the_account_down_then_fails_over(make_client, settings):
    def rule(request, n):
        return 429 if request.headers["x-api-key"] == "throttled" else 200

    handler, seen = _capture(rule)
    client = make_client(handler)
    _add(client, label="throttled", key="throttled")
    _add(client, label="fine", key="fine")

    resp = client.post("/v1/search", headers=CLIENT, json={"q": "x"})

    assert resp.status_code == 200
    assert resp.headers["x-router-account"] == "fine"
    rows = client.get("/admin/accounts", headers=ADMIN).json()["accounts"]
    throttled = next(a for a in rows if a["label"] == "throttled")
    assert throttled["on_cooldown"] is True
    assert throttled["used"] == 0


def test_client_error_is_passed_through_without_retry(make_client, settings):
    handler, seen = _capture(lambda req, n: 400)
    client = make_client(handler)
    _add(client, label="a", key="k1")
    _add(client, label="b", key="k2")

    resp = client.post("/v1/search", headers=CLIENT, json={"q": "x"})

    assert resp.status_code == 400
    assert resp.headers["x-router-attempts"] == "1"
    assert len(seen) == 1  # no failover on a caller mistake
    snapshot = quota.snapshot(quota.current_period())
    assert snapshot["quota_used_total"] == 1  # provider bills these


def test_connect_errors_are_retried_and_refunded(make_client, settings):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = make_client(handler)
    _add(client, label="a", key="k1")
    _add(client, label="b", key="k2")

    resp = client.post("/v1/search", headers=CLIENT, json={"q": "x"})

    assert resp.status_code == 502
    assert resp.json()["attempts"] == 2
    assert quota.snapshot(quota.current_period())["quota_used_total"] == 0


def test_quota_exhaustion_returns_429_with_retry_after(make_client, settings):
    handler, seen = _capture(lambda req, n: 200)
    client = make_client(handler)
    _add(client, limit=1)

    assert client.post("/v1/search", headers=CLIENT, json={"q": "a"}).status_code == 200
    resp = client.post("/v1/search", headers=CLIENT, json={"q": "b"})

    assert resp.status_code == 429
    assert resp.json()["error"] == "quota exhausted"
    assert int(resp.headers["retry-after"]) > 0
    assert len(seen) == 1
    assert client.get("/readyz").status_code == 503


def test_cache_hit_costs_no_quota(make_client, settings):
    handler, seen = _capture(lambda req, n: 200)
    client = make_client(handler, settings_override=replace(settings, cache_ttl_seconds=60))
    _add(client, limit=10)

    first = client.get("/v1/search?q=same", headers=CLIENT)
    second = client.get("/v1/search?q=same", headers=CLIENT)

    assert first.status_code == 200 and second.status_code == 200
    assert first.headers.get("x-cache") is None
    assert second.headers["x-cache"] == "HIT"
    assert len(seen) == 1
    assert quota.snapshot(quota.current_period())["quota_used_total"] == 1


def test_head_requests_return_no_body(make_client, settings):
    handler, _ = _capture(lambda req, n: 200)
    client = make_client(handler)
    _add(client)
    resp = client.head("/v1/search", headers=CLIENT)
    assert resp.status_code == 200
    assert resp.content == b""


def test_path_traversal_is_rejected():
    for bad in ("../etc/passwd", "https://evil.test/x", "//evil.test/x"):
        with pytest.raises(upstream.BadTarget):
            upstream.normalize_tail(bad)


def test_oversized_body_is_rejected(make_client, settings):
    handler, seen = _capture(lambda req, n: 200)
    client = make_client(handler, settings_override=replace(settings, max_body_bytes=32))
    _add(client)
    resp = client.post("/v1/search", headers=CLIENT, json={"q": "x" * 200})
    assert resp.status_code == 413
    assert seen == []


def test_quota_headers_present_on_upstream_errors(make_client, settings):
    handler, _ = _capture(lambda req, n: 500)
    client = make_client(handler)
    _add(client, limit=4)
    resp = client.post("/v1/search", headers=CLIENT, json={"q": "x"})
    assert resp.headers["x-quota-limit"] == "4"
    assert resp.headers["x-quota-remaining"] == "4"  # credits were refunded
    # ...but the account is cooling down, so nothing is spendable this second
    assert resp.headers["x-quota-available"] == "0"


def test_recent_request_log_records_calls(make_client, settings):
    handler, _ = _capture(lambda req, n: 200)
    client = make_client(handler)
    _add(client)
    client.get("/v1/search?q=logged", headers=CLIENT)
    recent = client.get("/api/status").json()["recent"]
    assert recent[0]["path"] == "/v1/search?q=logged"
    assert recent[0]["status"] == 200
    assert recent[0]["account"] == "acct"
