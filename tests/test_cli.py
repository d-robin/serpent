"""CLI tests: every command runs against a throwaway SERPENT_HOME, no network."""

from __future__ import annotations

import json
import stat

import pytest

from serpent import cli


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


@pytest.fixture
def run(home, capsys):
    def _run(*argv: str, expect: int = 0):
        code = cli.main(["--home", str(home), *argv])
        out = capsys.readouterr()
        assert code == expect, f"{argv}: exit {code}\n{out.out}\n{out.err}"
        return out.out

    return _run


def test_init_creates_private_env_and_prints_keys_once(home, run):
    out = run("init")
    assert "rk-admin-" in out and "rk-client-" in out and "rk-read-" in out
    env = home / ".env"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert (home / "data" / "serpent.db").exists()
    again = run("init")
    assert "rk-admin-" not in again and "kept existing" in again


def test_init_json_and_force(home, run):
    first = json.loads(run("init", "--json"))
    assert first["created_env"] and set(first["keys"]) == {"admin", "client", "read"}
    second = json.loads(run("init", "--force", "--json"))
    assert second["keys"]["admin"] != first["keys"]["admin"]


def test_load_settings_does_not_leak_env(home, run, monkeypatch):
    run("init")
    monkeypatch.delenv("ROUTER_KEYS", raising=False)
    settings = cli.load_settings_for(cli.Home(home))
    assert settings.router_keys and "ROUTER_KEYS" not in cli.os.environ
    assert settings.db_path == str(home / "data" / "serpent.db")


def test_providers_chains_route_roundtrip(run):
    run("init")
    assert "serper" in run("providers", "presets")
    run("providers", "add", "serper", "--preset", "serper")
    run("providers", "add", "backup", "--base-url", "https://b.test", "--auth-style", "bearer")
    listed = json.loads(run("providers", "list", "--json"))
    assert {p["slug"] for p in listed} == {"default", "serper", "backup"}
    run("providers", "add", "serper", "--preset", "serper", expect=1)  # duplicate
    run("chains", "add", "web", "serper", "backup")
    assert "serper -> backup" in run("chains", "list")
    run("chains", "add", "bad", "ghost", expect=1)
    run("route", "set", "web")
    assert "serper -> backup" in run("route", "show")
    run("route", "set", "nope", expect=1)
    run("providers", "disable", "backup")
    assert "(nothing enabled)" not in run("route", "show")


def test_accounts_lifecycle_and_provider_scoping(run):
    run("init")
    run("providers", "add", "serper", "--preset", "serper")
    run("accounts", "add", "--provider", "serper", "--label", "s1", "--limit", "10", "--key", "sk-secret-1234")
    run("accounts", "add", "--label", "d1", "--key", "sk-other-5678")
    out = run("accounts", "list")
    assert "s1" in out and "****1234" in out and "sk-secret" not in out
    scoped = json.loads(run("accounts", "list", "--provider", "serper", "--json"))
    assert [a["label"] for a in scoped] == ["s1"] and scoped[0]["provider"] == "serper"
    run("accounts", "disable", "1")
    assert "disabled" in run("accounts", "list")
    run("accounts", "enable", "1")
    run("accounts", "reset", "1")
    run("accounts", "move", "2", "--provider", "serper")
    run("accounts", "add", "--key", "sk-secret-1234", expect=1)  # duplicate key
    run("providers", "remove", "serper", expect=1)  # still has accounts
    run("accounts", "remove", "1")
    run("accounts", "remove", "99", expect=1)


def test_account_key_read_from_stdin(run, monkeypatch):
    import io

    run("init")
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("sk-from-stdin-9999\n"))
    run("accounts", "add", "--label", "piped", "--key", "-")
    assert "****9999" in run("accounts", "list")


def test_status_and_health_when_stopped(run):
    run("init")
    status = json.loads(run("status", "--json"))
    assert status["running"] is False and status["faults"] == 0
    health = json.loads(run("health", "--json", expect=1))
    by_name = {c["name"]: c["status"] for c in health["checks"]}
    assert by_name["process"] == "fail" and by_name["database"] == "ok" and not health["healthy"]
    assert "FAIL" in run("health", "-q", expect=1)


def test_doctor_reports_environment(run):
    run("init")
    rows = {c["name"]: c for c in json.loads(run("doctor", "--json", expect=1))["checks"]}
    assert rows["python"]["status"] == "ok" and rows[".env"]["status"] == "ok"
    assert rows["auth"]["status"] == "ok" and rows["config-db"]["status"] == "warn"


def test_fault_log_and_diagnosis(home, run):
    run("init")
    h = cli.Home(home)
    assert "no faults recorded" in run("fault")
    cli.logline(h, "something happened")
    cli.record_fault(h, "start-failed", "the port is already in use", "pass --port")
    out = run("fault")
    assert "start-failed" in out and "pass --port" in out and "something happened" in out
    assert "1 fault(s)" in run("fault", "--all")
    for i in range(cli.FAULT_KEEP + 5):
        cli.record_fault(h, "k", f"r{i}", "")
    assert len(cli.read_faults(h)) == cli.FAULT_KEEP


def test_fault_falls_back_to_scanning_the_log(home, run):
    run("init")
    (home / "logs" / "router.log").write_text(
        "boot\nOSError: [Errno 48] address already in use\nmore\n", encoding="utf-8")
    out = run("fault")
    assert "the port is already in use" in out


@pytest.mark.parametrize("line,reason", [
    ("ModuleNotFoundError: No module named 'fastapi'", "package is missing"),
    ("sqlite3.OperationalError: database is locked", "locked"),
    ("OSError: [Errno 28] No space left on device", "disk is full"),
    ("PermissionError: [Errno 13] Permission denied: 'x'", "permission denied"),
    ("ValueError: boom: bad", "startup crashed"),
    ("nothing useful", "without an obvious error"),
])
def test_diagnose(line, reason):
    assert reason in cli.diagnose(["noise", line])[0]


def test_log_command(home, run):
    run("init")
    assert "no log yet" in run("log")
    (home / "logs" / "router.log").write_text("\n".join(f"line{i}" for i in range(100)) + "\n")
    out = run("log", "-n", "3").splitlines()
    assert out == ["line97", "line98", "line99"]


def test_port_finder_skips_busy_ports():
    import socket

    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        found = cli.find_port(port, "127.0.0.1")
    assert found is not None and found != port


def test_parse_target():
    assert cli.parse_target("/srv/x") == ("", "/srv/x")
    assert cli.parse_target("pi@host:/home/pi/s") == ("pi@host", "/home/pi/s")
    assert cli.parse_target("ssh://pi@host/opt/s") == ("pi@host", "/opt/s")
    assert cli.parse_target("rel/dir") == ("", "rel/dir")


def test_move_safety_and_dry_run(home, run, tmp_path):
    run("init")
    out = run("move", str(tmp_path / "dest"), "--dry-run", "--with-env")
    assert "dry run" in out and not (tmp_path / "dest").exists()
    run("move", str(home), expect=1)
    run("move", str(home / "inner"), expect=1)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("x")
    run("move", str(foreign), expect=1)
    run("move", "pi@host:/bad path;rm", expect=1)


def test_move_copy_carries_only_what_was_asked(home, run, tmp_path):
    run("init")
    run("accounts", "add", "--label", "a", "--key", "sk-move-0001")
    dest = tmp_path / "copy"
    run("move", str(dest), "--with-data", "--no-verify")
    assert (dest / "data" / "serpent.db").exists() and not (dest / ".env").exists()
    assert home.exists()


def test_move_deletes_original_only_when_asked(home, run, tmp_path):
    run("init")
    dest = tmp_path / "moved"
    run("move", str(dest), "--move", "--yes", "--with-env", "--with-data", "--no-verify")
    assert not home.exists() and (dest / ".env").exists()


def test_systemd_unit_has_real_paths(home, run):
    unit = run("systemd", "--port", "9000", "--user", "pi")
    assert f"WorkingDirectory={home}" in unit and "--port 9000" in unit and "User=pi" in unit
    assert "serpent.main:app" in unit and "NoNewPrivileges=true" in unit


def test_version_and_help(run, capsys):
    assert json.loads(run("version", "--json"))["version"]
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert "providers" in capsys.readouterr().out


def test_seed_imports_env_accounts(run, monkeypatch):
    run("init")
    monkeypatch.setenv("SERP_ACCOUNTS", "one:sk-seed-1111,two:sk-seed-2222")
    assert "imported 2" in run("seed")
    assert "imported 0" in run("seed")


def test_start_status_stop_cycle(home, run):
    """One real daemon on a free port: start -> healthy -> stop."""
    run("init")
    port = cli.free_port()
    out = run("start", "--port", str(port), "--wait", "30")
    try:
        assert f"127.0.0.1:{port}" in out
        status = json.loads(run("status", "--json"))
        assert status["running"] and status["health"] == 200
        assert "already running" in run("start", "--port", str(port))
        assert json.loads(run("health", "--json"))["healthy"] is True
    finally:
        run("stop")
    assert json.loads(run("status", "--json"))["running"] is False
    assert not (home / "run" / "serpent.pid").exists()


def test_second_account_on_a_provider_prints_a_terms_warning(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("SERPENT_HOME", str(tmp_path))
    from serpent import cli

    assert cli.main(["init"]) == 0
    assert cli.main(["accounts", "add", "--label", "a", "--key", "k1"]) == 0
    capsys.readouterr()
    assert cli.main(["accounts", "add", "--label", "b", "--key", "k2"]) == 0
    assert "responsible-use.md" in capsys.readouterr().err


def test_admin_key_and_next_steps(tmp_path, monkeypatch):
    monkeypatch.setenv("SERPENT_HOME", str(tmp_path))
    from serpent import cli

    home = cli.resolve_home(None)
    home.ensure()
    home.env_file.write_text("ROUTER_KEYS=c1:client,a1:admin,r1:read\n")
    assert cli.admin_key(home) == "a1"
    text = cli.next_steps("http://127.0.0.1:8971", key="a1")
    assert "http://127.0.0.1:8971/ui/#key=a1" in text and "Accounts" in text
    assert "#key=" not in cli.next_steps("http://10.0.0.5:8971", key=None)
    home.env_file.write_text("ROUTER_KEYS=\n")
    assert cli.admin_key(home) is None
