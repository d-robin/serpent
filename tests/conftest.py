"""Shared pytest fixtures: an isolated DB per test and a mocked SERP provider."""

from __future__ import annotations

import contextlib
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from serpent import db
from serpent.config import Settings
from serpent.main import create_app

ADMIN_KEY = "test-admin"
CLIENT_KEY = "test-client"
READ_KEY = "test-read"

ADMIN = {"X-Router-Key": ADMIN_KEY}
CLIENT = {"X-Router-Key": CLIENT_KEY}
READ = {"X-Router-Key": READ_KEY}


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        db_path=str(tmp_path / "router.db"),
        upstream_base_url="https://upstream.test",
        router_keys={ADMIN_KEY: "admin", CLIENT_KEY: "client", READ_KEY: "read"},
        strategy="most_remaining",
        max_retries=2,
        default_quota_limit=250,
        cooldown_base_seconds=1.0,
        cooldown_max_seconds=5.0,
        request_log_size=50,
    )


def ok_responder(payload: dict | None = None, status: int = 200):
    body = payload or {"organic": [{"title": "hello"}]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return handler


@pytest.fixture
def make_client(settings):
    """create_app() with a MockTransport upstream; yields TestClients."""
    stack = contextlib.ExitStack()

    def _make(responder=None, *, settings_override: Settings | None = None):
        s = settings_override or settings
        transport = httpx.MockTransport(responder or ok_responder())
        app = create_app(s, transport=transport)
        client = stack.enter_context(TestClient(app))
        client.router_app = app
        return client

    yield _make
    stack.close()


@pytest.fixture
def seeded_client(make_client, settings):
    """Client with three accounts at 250 credits each."""
    client = make_client(settings_override=settings)
    for index in range(3):
        resp = client.post(
            "/admin/accounts",
            headers=ADMIN,
            json={"label": f"acct-{index + 1}", "api_key": f"key-{index + 1}", "quota_limit": 250},
        )
        assert resp.status_code == 201, resp.text
    return client


@pytest.fixture
def tight_settings(settings) -> Settings:
    """Small limits so quota edges are easy to hit."""
    from dataclasses import replace

    return replace(settings, default_quota_limit=3, max_retries=2)


def db_rows(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return db.connection().execute(sql, params).fetchall()
