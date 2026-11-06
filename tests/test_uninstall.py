"""`serpent uninstall`: inventory, keep-or-delete data, and a verified result."""

from __future__ import annotations

import json

import pytest

from serpent import cli, uninstall


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
    (home / "logs").mkdir(exist_ok=True)
    (home / "logs" / "router.log").write_text("x")
    return home


def test_init_records_what_it_installed(installed):
    data = json.loads((installed / ".serpent-install.json").read_text())
    assert data["home"] == str(installed) and data["version"]


def test_venv_is_claimed_only_when_the_installer_made_it(run, home, monkeypatch):
    monkeypatch.setenv("SERPENT_VENV_CREATED", "1")
    run("init")
    assert json.loads((home / ".serpent-install.json").read_text())["venv_created"] is True


def test_dry_run_changes_nothing(installed, run):
    out = run("uninstall", "--dry-run")
    assert "KEEP" in out and "dry run" in out
    assert (installed / "data").exists() and (installed / ".env").exists()
    assert (installed / "logs").exists()


def test_keep_data_removes_the_rest_and_verifies(installed, run):
    out = run("uninstall", "--yes", "--keep-data")
    assert "verified clean" in out
    assert (installed / "data" / "serpent.db").exists() and (installed / ".env").exists()
    assert not (installed / "logs").exists() and not (installed / "run").exists()
    assert not (installed / ".serpent-install.json").exists()
    assert "SERPENT_HOME=" in out  # says how to redeploy


def test_yes_alone_never_deletes_data(installed, run):
    run("uninstall", "--yes")
    assert (installed / "data").exists() and (installed / ".env").exists()


def test_delete_data_removes_everything(installed, run):
    out = run("uninstall", "--yes", "--delete-data")
    assert "verified clean" in out
    assert not (installed / "data").exists() and not (installed / ".env").exists()


def test_refuses_without_a_terminal_or_yes(installed, run):
    run("uninstall", expect=1)
    assert (installed / ".env").exists()


def test_conflicting_flags(installed, run):
    run("uninstall", "--keep-data", "--delete-data", "--yes", expect=1)


def test_nothing_to_do_on_an_empty_directory(run, home):
    home.mkdir()
    assert "Nothing from Serpent" in run("uninstall", "--yes")


def test_verify_flags_what_could_not_be_removed(installed, monkeypatch):
    inv = uninstall.scan(cli.Home(installed))
    uninstall.apply_choice(inv, keep_data=True)
    monkeypatch.setattr(uninstall, "_rm", lambda path: None)  # simulate a failed delete
    uninstall.execute(inv)
    assert uninstall.verify(inv) >= 1
    assert any(i.result == "STILL PRESENT" for i in inv.items)


def test_never_removes_the_python_package_on_its_own(installed, run):
    from importlib import metadata

    out = run("uninstall", "--yes", "--delete-data")
    metadata.distribution("serpent-router")  # still installed: it may serve other homes
    assert "pip uninstall" in out or "pipx uninstall" in out or "serpent-router" not in out


def test_backup_is_private_valid_and_treated_as_data(installed, run, home):
    import os
    import sqlite3
    import stat

    out = run("backup")
    files = list((home / "backups").glob("serpent-*.db"))
    assert len(files) == 1 and str(files[0]) in out
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o600
    assert stat.S_IMODE(os.stat(home / "backups").st_mode) == 0o700
    con = sqlite3.connect(files[0])
    try:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        con.close()

    inv = uninstall.scan(cli.Home(home))
    item = inv.get("backups")
    assert item is not None and item.category == "data"  # kept by default, deleted only with the data
    run("uninstall", "--yes", "--keep-data")
    assert (home / "backups").exists()
    run("uninstall", "--yes", "--delete-data")
    assert not (home / "backups").exists()
