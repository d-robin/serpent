"""Recovering and rotating keys: router keys from .env, provider keys from the database."""

from __future__ import annotations

import json
import os
import stat

import pytest

from serpent import cli, keys


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


@pytest.fixture
def run(home, capsys):
    def _run(*argv: str, expect: int = 0):
        code = cli.main(["--home", str(home), *argv])
        out = capsys.readouterr()
        assert code == expect, f"{argv}: exit {code}\n{out.err}{out.out}"
        return out.out
    return _run


@pytest.fixture
def installed(run, home):
    run("init")
    run("providers", "add", "main", "--preset", "serper")
    run("accounts", "add", "--label", "w1", "--key", "sk-provider-secret-1234")
    return home


def test_mask_never_shows_the_middle():
    assert keys.mask("sk-provider-secret-1234") == "sk-...1234"
    assert keys.mask("short") == "****"


def test_router_keys_come_from_env(installed):
    pairs = dict(keys.router_keys(cli.Home(installed)))
    assert set(pairs) == {"admin", "client", "read"} and pairs["admin"].startswith("rk-admin-")


def test_keys_are_masked_unless_revealed(installed, run):
    secret = "sk-provider-secret-1234"
    out = run("keys")
    assert "sk-...1234" in out and secret not in out and "rk-admin-" not in out.replace("rk-...", "")
    assert secret in run("keys", "--reveal", "--yes")
    data = json.loads(run("keys", "--json"))
    assert data["accounts"][0]["key"] == "sk-...1234"


def test_rotate_changes_only_that_role_and_stays_private(installed, run):
    h = cli.Home(installed)
    before = dict(keys.router_keys(h))
    text_before = h.env_file.read_text()
    out = run("keys", "rotate", "client", "--yes")
    after = dict(keys.router_keys(h))
    assert after["client"] != before["client"] and after["client"] in out
    assert after["admin"] == before["admin"] and after["read"] == before["read"]
    assert "DASHBOARD_PUBLIC=true" in h.env_file.read_text()  # other settings untouched
    assert len(h.env_file.read_text().splitlines()) == len(text_before.splitlines())
    assert stat.S_IMODE(os.stat(h.env_file).st_mode) == 0o600


def test_rotate_rejects_unknown_roles(installed, run):
    run("keys", "rotate", "root", "--yes", expect=1)
    run("keys", "rotate", expect=1)


def test_link_signs_in_as_admin(installed, run):
    link = run("keys", "link").strip()
    admin = dict(keys.router_keys(cli.Home(installed)))["admin"]
    assert link.endswith(f"/ui/#key={admin}")
