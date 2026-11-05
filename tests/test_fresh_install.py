"""A fresh install ships with no provider: you choose one."""

from __future__ import annotations

from dataclasses import replace

import pytest

from serpent import accounts
from tests.conftest import ADMIN, CLIENT


@pytest.fixture
def fresh(make_client, settings):
    return make_client(settings_override=replace(settings, upstream_base_url=""))


def test_no_provider_exists_until_you_add_one(fresh):
    status = fresh.get("/api/status", headers=ADMIN).json()
    assert status["providers"] == [] and status["upstream"] == ""


def test_proxy_explains_what_to_do_instead_of_404(fresh):
    r = fresh.post("/v1/search", json={"q": "x"}, headers=CLIENT)
    assert r.status_code == 503 and "no provider configured" in r.json()["error"]


def test_account_needs_a_provider(fresh):
    r = fresh.post("/admin/accounts", json={"api_key": "k1", "label": "a"}, headers=ADMIN)
    assert r.status_code == 400 and "provider" in r.text


def test_first_provider_becomes_the_default_route(fresh):
    r = fresh.post("/admin/providers", json={"slug": "main", "preset": "brave"}, headers=ADMIN)
    assert r.status_code in (200, 201)
    status = fresh.get("/api/status", headers=ADMIN).json()
    assert status["default_route"] == "main"
    assert status["upstream"] == "https://api.search.brave.com/res/v1"
    # with exactly one provider, an account needs no explicit choice
    acc = accounts.add_account("k1", label="a")
    assert acc["provider_id"] == status["providers"][0]["id"]


def test_old_env_upstream_is_still_adopted_as_default(make_client, settings):
    client = make_client()  # settings fixture sets UPSTREAM_BASE_URL
    slugs = [p["slug"] for p in client.get("/api/status", headers=ADMIN).json()["providers"]]
    assert slugs == ["default"]
