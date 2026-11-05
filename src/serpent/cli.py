"""The ``serpent`` command: run the gateway and manage providers, chains and accounts.

Standard library only.  State lives in a *home* directory (``--home``,
``$SERPENT_HOME`` or the current directory)::

    <home>/.env              configuration and router keys (mode 600)
    <home>/data/serpent.db   SQLite: providers, chains, accounts, usage
    <home>/logs/             router.log (rotated at 2 MB) and faults.log
    <home>/run/              serpent.pid, serpent.port
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from . import __version__

DEFAULT_PORT = 8971
PORT_SCAN = 200
LOG_ROTATE_BYTES = 2 * 1024 * 1024
FAULT_KEEP = 50


class CliError(Exception):
    """A problem to report as ``error: ...`` with exit status 1."""


# ---------------------------------------------------------------- output ----


def _tty() -> bool:
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _tty() else text


_STATUS_COLOR = {"ok": "32", "warn": "33", "fail": "31"}


def say(text: str = "") -> None:
    print(text)


def eprint(text: str) -> None:
    print(text, file=sys.stderr)


def table(rows: Sequence[Sequence[object]], header: Sequence[str]) -> str:
    cells = [[str(c) for c in row] for row in rows]
    widths = [len(h) for h in header]
    for row in cells:
        for i, c in enumerate(row):
            widths[i] = max(widths[i], len(c))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    lines = [fmt.format(*header), "  ".join("-" * w for w in widths)]
    lines += [fmt.format(*row).rstrip() for row in cells]
    return "\n".join(lines)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ home ----


@dataclass(frozen=True)
class Home:
    root: Path

    @property
    def env_file(self) -> Path:
        return self.root / ".env"

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def run(self) -> Path:
        return self.root / "run"

    @property
    def log(self) -> Path:
        return self.logs / "router.log"

    @property
    def faults(self) -> Path:
        return self.logs / "faults.log"

    @property
    def pidf(self) -> Path:
        return self.run / "serpent.pid"

    @property
    def portf(self) -> Path:
        return self.run / "serpent.port"

    def ensure(self) -> None:
        for d in (self.root, self.data, self.logs, self.run):
            d.mkdir(parents=True, exist_ok=True)
        try:
            self.data.chmod(0o700)  # holds the database with provider keys
        except OSError:
            pass

    @property
    def is_checkout(self) -> bool:
        return (self.root / "pyproject.toml").is_file() and (self.root / "src" / "serpent").is_dir()


def resolve_home(explicit: str | None = None) -> Home:
    raw = explicit or os.environ.get("SERPENT_HOME") or os.getcwd()
    return Home(Path(raw).expanduser().resolve())


def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def load_settings_for(home: Home):
    """Settings as the server would see them, without leaking .env into os.environ."""
    from .config import load_settings

    snapshot = dict(os.environ)
    try:
        os.environ["SERPENT_HOME"] = str(home.root)
        settings = load_settings(home.env_file)
        if "DB_PATH" not in os.environ:
            settings = replace(settings, db_path=str(home.data / "serpent.db"))
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
    return settings


def boot(home: Home):
    """Open the home's database (creating it if needed) and return the settings."""
    from . import db, providers

    settings = load_settings_for(home)
    db.init_db(settings.db_path)
    providers.ensure_default(settings)
    return settings


# ------------------------------------------------------------------ logs ----


def logline(home: Home, message: str) -> None:
    home.logs.mkdir(parents=True, exist_ok=True)
    with home.log.open("a", encoding="utf-8") as fh:
        fh.write(f"[{now_utc()}] ctl: {message}\n")


def rotate_log(home: Home) -> None:
    try:
        if home.log.stat().st_size > LOG_ROTATE_BYTES:
            os.replace(home.log, home.log.with_name(home.log.name + ".1"))
    except OSError:
        pass


def tail_lines(path: Path, n: int) -> list[str]:
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            block, data = 8192, b""
            while size > 0 and data.count(b"\n") <= n:
                step = min(block, size)
                size -= step
                fh.seek(size)
                data = fh.read(step) + data
        return data.decode("utf-8", "replace").splitlines()[-n:]
    except OSError:
        return []


def read_faults(home: Home) -> list[dict]:
    entries: list[dict] = []
    try:
        text = home.faults.read_text(encoding="utf-8")
    except OSError:
        return entries
    for line in text.splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except ValueError:
                pass
    return entries


def record_fault(home: Home, kind: str, reason: str, hint: str) -> None:
    home.logs.mkdir(parents=True, exist_ok=True)
    context = [ln[:400] for ln in tail_lines(home.log, 25) if ln.strip()]
    entries = read_faults(home)
    entries.append(
        {"ts": now_utc(), "kind": kind, "reason": reason, "hint": hint, "context": context}
    )
    with home.faults.open("w", encoding="utf-8") as fh:
        for entry in entries[-FAULT_KEEP:]:
            fh.write(json.dumps(entry) + "\n")


_DIAGNOSES: list[tuple[str, str, str]] = [
    (r"address already in use|errno 48|errno 98", "the port is already in use",
     "let serpent pick the next free port, or pass --port N"),
    (r"Read-only file system", "the disk or database directory is read-only",
     "on a Pi the SD card may have remounted read-only: sudo mount -o remount,rw / ; "
     "otherwise check DB_PATH and data/ permissions"),
    (r"No space left on device", "the disk is full",
     "free space (df -h) or move DB_PATH to another volume"),
    (r"No module named", "a python package is missing from the environment",
     "reinstall: pip install -e . (or ./install.sh)"),
    (r"ModuleNotFoundError|ImportError", "an import failed at startup",
     "reinstall with ./install.sh; if it persists, read the traceback in logs/router.log"),
    (r"SyntaxError|IndentationError", "a source file did not compile",
     "a recent edit broke the syntax - see the traceback"),
    (r"unable to open database|attempt to write a readonly database|database is locked"
     r"|sqlite3\.\w*Error", "the database could not be opened or is locked",
     "check DB_PATH, that data/ is writable, and that the path is not on a network share"),
    (r"Permission denied", "permission denied", "check ownership/mode of the home dir, .env and data/"),
    (r"no free port", "no free port was found", "raise --port or free a port in the range"),
]


def diagnose(lines: Sequence[str]) -> tuple[str, str, str]:
    """Turn the tail of a log into (reason, hint, evidence)."""
    lines = [ln for ln in lines if ln.strip()]

    def last(pattern: str) -> str:
        for ln in reversed(lines):
            if re.search(pattern, ln, re.I):
                return ln.strip()
        return ""

    for pattern, reason, hint in _DIAGNOSES:
        hit = last(pattern)
        if hit:
            return reason, hint, hit[:300]
    exc = last(r"^[A-Za-z_][A-Za-z0-9_.]*(Error|Exception)\b.*:")
    if exc:
        return ("startup crashed - " + exc[:220], "see logs/router.log for the full traceback", exc[:300])
    tail = lines[-1][:300] if lines else "log is empty"
    if last(r"Traceback \(most recent call last\)"):
        return "startup crashed with a traceback", "see logs/router.log for the traceback", tail
    return "the process exited without an obvious error message", "check logs/router.log", tail


# ------------------------------------------------------------- processes ----


def read_pid(home: Home) -> int | None:
    try:
        return int(home.pidf.read_text().strip())
    except (OSError, ValueError):
        return None


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def is_running(home: Home) -> bool:
    return pid_alive(read_pid(home))


def read_port(home: Home) -> int | None:
    try:
        return int(home.portf.read_text().strip())
    except (OSError, ValueError):
        return None


def clear_run_files(home: Home) -> None:
    for p in (home.pidf, home.portf):
        try:
            p.unlink()
        except OSError:
            pass


def proc_info(pid: int) -> tuple[str, str]:
    """(elapsed, rss) from ps; empty strings when unavailable."""
    try:
        out = subprocess.run(
            ["ps", "-o", "etime=,rss=", "-p", str(pid)], capture_output=True, text=True, timeout=3
        ).stdout.split()
        if len(out) == 2:
            return out[0], f"{int(out[1]) // 1024} MB"
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return "", ""


def find_port(base: int, host: str) -> int | None:
    """First port from ``base`` that we can really bind (not just one lsof says is free)."""
    probe = "0.0.0.0" if host in ("0.0.0.0", "::") else host
    for port in range(base, min(base + PORT_SCAN, 65536)):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((probe, port))
        except OSError:
            continue
        finally:
            sock.close()
        return port
    return None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http_get(url: str, timeout: float = 3.0, headers: dict | None = None) -> tuple[int, str, float]:
    """(status, body, ms).  Status 0 means no response."""
    start = time.perf_counter()
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(65536).decode("utf-8", "replace")
            return resp.status, body, (time.perf_counter() - start) * 1000
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(65536).decode("utf-8", "replace")
        except Exception:
            body = ""
        return exc.code, body, (time.perf_counter() - start) * 1000
    except Exception:
        return 0, "", (time.perf_counter() - start) * 1000


def probe_host(host: str) -> str:
    return "127.0.0.1" if host in ("0.0.0.0", "::") else host


def base_port(home: Home, explicit: int | None = None) -> int:
    if explicit:
        return explicit
    for raw in (os.environ.get("SERPENT_PORT"), read_env_file(home.env_file).get("BIND_PORT")):
        if raw and raw.isdigit():
            return int(raw)
    from .uninstall import remembered_port
    return remembered_port(home) or DEFAULT_PORT


def port_owner(port: int) -> str:
    """Best effort: who is listening on a local port ('' when it cannot be told)."""
    def lsof(*args: str) -> str:
        try:
            return subprocess.run(["lsof", "-nP", *args], capture_output=True, text=True,
                                  timeout=3).stdout
        except (OSError, subprocess.SubprocessError):
            return ""

    fields = {ln[0]: ln[1:] for ln in lsof(f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpc").splitlines() if ln}
    pid = fields.get("p")
    if not pid or not pid.isdigit():
        return ""
    cwd = next((ln[1:] for ln in lsof("-p", pid, "-a", "-d", "cwd", "-Fn").splitlines()
                if ln.startswith("n")), "")
    try:
        if cwd and int((Path(cwd) / "run" / "serpent.pid").read_text().strip()) == int(pid):
            return f"another Serpent install at {cwd} (pid {pid})"
    except (OSError, ValueError):
        pass
    return f"pid {pid} ({fields.get('c', '?')}{', ' + cwd if cwd else ''})"


def print_install_info(home: Home) -> None:
    """What a user needs to find a running install again."""
    d = status_data(home)
    cmd_status(home, argparse.Namespace(json=False))
    if d.get("url"):
        say(f"ui        {d['url']}/ui/")
    say(f"port      {d['port']}   (this install keeps it; another folder gets the next free one)")


def pick_host(explicit: str | None = None) -> str:
    return explicit or os.environ.get("SERPENT_HOST") or "127.0.0.1"


def server_env(home: Home, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env["SERPENT_HOME"] = str(home.root)
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.update(extra or {})
    return env


def uvicorn_cmd(host: str, port: int, *, workers: int | None = None, level: str = "info") -> list[str]:
    cmd = [sys.executable, "-m", "uvicorn", "serpent.main:app", "--host", host, "--port", str(port),
           "--no-access-log", "--log-level", level]
    if workers and workers > 1:
        cmd += ["--workers", str(workers)]
    return cmd


# ------------------------------------------------------------------ start ---


def cmd_start(home: Home, args: argparse.Namespace) -> int:
    if is_running(home):
        say("Serpent is already running for this install - not starting a second copy.\n")
        print_install_info(home)
        say("\nstop it: serpent stop    restart: serpent restart")
        say("a second install in another folder will start on its own port")
        return 1
    clear_run_files(home)
    home.ensure()
    rotate_log(home)
    host = pick_host(args.host)
    base = base_port(home, args.port)
    chosen = find_port(base, host)
    if chosen is None:
        reason = f"no free port in {base}..{base + PORT_SCAN - 1}"
        logline(home, reason)
        record_fault(home, "start-failed", reason, "pass --port, e.g. serpent start --port 9100")
        raise CliError(reason)
    logline(home, f"start requested host={host} base={base} chosen={chosen} workers={args.workers or 1}")
    if chosen != base:
        owner = port_owner(base)
        why = f"port {base} is in use" + (f" by {owner}" if owner else "")
        logline(home, f"{why}, using {chosen}")
        say(f"{why}; using {chosen}")

    level = os.environ.get("LOG_LEVEL", read_env_file(home.env_file).get("LOG_LEVEL", "info")).lower()
    with home.log.open("ab") as logfh:
        proc = subprocess.Popen(
            uvicorn_cmd(host, chosen, workers=args.workers, level=level),
            stdout=logfh, stderr=logfh, stdin=subprocess.DEVNULL,
            cwd=home.root, env=server_env(home), start_new_session=True,
        )
    home.pidf.write_text(f"{proc.pid}\n")
    home.portf.write_text(f"{chosen}\n")
    url = f"http://{probe_host(host)}:{chosen}"

    code = 0
    for _ in range(int(args.wait * 2)):
        if proc.poll() is not None:
            break
        code, _, _ = http_get(url + "/healthz")
        if code == 200:
            break
        time.sleep(0.5)

    if code != 200:
        return _start_failed(home, proc, url)

    from .uninstall import remember_port
    remember_port(home, chosen)
    logline(home, f"started pid={proc.pid} host={host} port={chosen} url={url}")
    say(f"started  pid {proc.pid} on {url}")
    say(f"ui         {url}/")
    say(f"log        {home.log}   (serpent log -f to follow)")
    say("stop       serpent stop")
    if not getattr(args, "from_up", False):
        say("setup      serpent up   (opens the web UI)")
    if host in ("127.0.0.1", "localhost"):
        say("note: loopback only - use --host 0.0.0.0 to reach it from the LAN")
    return 0


def _start_failed(home: Home, proc: subprocess.Popen, url: str) -> int:
    reason, hint, evidence = diagnose(tail_lines(home.log, 80))
    if proc.poll() is None:
        record_fault(home, "unhealthy", "started but /healthz never returned 200",
                     "check the log; the port may be firewalled or the app is stuck")
        eprint(f"error: started (pid {proc.pid}) but /healthz did not come up")
        _terminate(proc.pid, 5)
    else:
        record_fault(home, "start-failed", reason, hint)
        eprint("error: the process exited during startup")
        eprint(f"reason: {reason}")
        if evidence:
            eprint(f"  saw : {evidence[:200]}")
    clear_run_files(home)
    eprint("\nlast log lines:")
    for ln in tail_lines(home.log, 12):
        eprint("  " + ln)
    eprint("\ndetails: serpent fault")
    return 1


def _signal_group(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, sig)
        except OSError:
            pass


def _terminate(pid: int, grace: float) -> bool:
    """SIGTERM then SIGKILL.  Returns True when a forced kill was needed."""
    _signal_group(pid, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and pid_alive(pid):
        time.sleep(0.1)
    if pid_alive(pid):
        _signal_group(pid, signal.SIGKILL)
        time.sleep(0.2)
        return True
    return False


def cmd_stop(home: Home, args: argparse.Namespace | None = None) -> int:
    pid = read_pid(home)
    if not pid_alive(pid):
        if pid:
            logline(home, f"removed stale pid file (pid {pid} not running)")
        clear_run_files(home)
        say("not running")
        return 0
    logline(home, f"stop requested pid={pid}")
    forced = _terminate(pid, 10)  # type: ignore[arg-type]
    if forced:
        record_fault(home, "stop-forced", "the process ignored SIGTERM for 10s",
                     "a request was probably stuck; check the upstream timeout")
        logline(home, f"killed pid={pid} after 10s")
        say("stopped (forced)")
    else:
        logline(home, f"stopped pid={pid}")
        say("stopped")
    clear_run_files(home)
    return 0


def cmd_restart(home: Home, args: argparse.Namespace) -> int:
    cmd_stop(home)
    return cmd_start(home, args)


def cmd_run(home: Home, args: argparse.Namespace) -> int:
    if is_running(home):
        raise CliError(f"already running for this install (pid {read_pid(home)}, "
                       f"port {read_port(home) or '?'}); serpent stop first")
    host = pick_host(args.host)
    base = base_port(home, args.port)
    chosen = find_port(base, host)
    if chosen is None:
        raise CliError(f"no free port in {base}..{base + PORT_SCAN - 1}")
    if chosen != base:
        say(f"port {base} is busy, using {chosen}")
    say(f"Serpent  ->  http://{host}:{chosen}/")
    say(f"Snake Charmer UI and dashboard  ->  http://{host}:{chosen}/")
    say(f"Quota API  ->  http://{host}:{chosen}/v1/quota\n")
    home.ensure()
    os.chdir(home.root)
    os.execve(sys.executable, uvicorn_cmd(host, chosen, level=os.environ.get("LOG_LEVEL", "info")),
              server_env(home))
    return 0  # pragma: no cover


# ----------------------------------------------------------------- status ---


def quota_line(home: Home, url: str) -> str:
    try:
        settings = load_settings_for(home)
        keys = settings.router_keys
        key = next((k for k, r in keys.items() if r == "read"), None) or next(
            (k for k, r in keys.items() if r == "client"), None)
        code, body, _ = http_get(url + "/v1/quota", headers={settings.router_key_header: key} if key else None)
        d = json.loads(body)
        if code != 200:
            raise ValueError(f"HTTP {code}")
        return (f"{d['accounts_usable']}/{d['accounts_total']} accounts usable, "
                f"{d['quota_available_total']} credits available ({d['quota_used_total']} used this period)")
    except Exception as exc:
        return f"(quota unavailable: {exc})"


def status_data(home: Home) -> dict:
    pid, port = read_pid(home), read_port(home)
    running = pid_alive(pid)
    data: dict = {"home": str(home.root), "running": running, "pid": pid if running else None,
                  "port": port}
    if running and pid:
        data["uptime"], data["memory"] = proc_info(pid)
        data["url"] = f"http://127.0.0.1:{port or '?'}"
        data["health"] = http_get(data["url"] + "/healthz")[0]
        data["accounts"] = quota_line(home, data["url"])
    elif port:
        data["unmanaged"] = http_get(f"http://127.0.0.1:{port}/healthz")[0] == 200
    data["log_bytes"] = home.log.stat().st_size if home.log.exists() else 0
    faults = read_faults(home)
    data["faults"] = len(faults)
    data["last_fault"] = f"{faults[-1]['ts']}  {faults[-1]['kind']}  {faults[-1]['reason']}" if faults else None
    return data


def cmd_status(home: Home, args: argparse.Namespace) -> int:
    d = status_data(home)
    if getattr(args, "json", False):
        say(json.dumps(d, indent=2))
        return 0
    if d["running"]:
        extra = ", ".join(x for x in (f"up {d['uptime']}" if d["uptime"] else "", d["memory"]) if x)
        say(f"state     running (pid {d['pid']}{', ' + extra if extra else ''})")
        say(f"url       {d['url']}")
        say(f"health    {d['health']}")
        say(f"accounts  {d['accounts']}")
    else:
        say("state     stopped")
        if d.get("unmanaged"):
            say(f"warning   port {d['port']} answers /healthz but no live pid - unmanaged instance?")
    say(f"home      {d['home']}")
    say(f"log       {home.log} ({d['log_bytes']} bytes)")
    say(f"faults    {d['faults']} recorded; last: {d['last_fault']}" if d["faults"] else "faults    none recorded")
    return 0


# -------------------------------------------------------------- log/fault ---


def cmd_log(home: Home, args: argparse.Namespace) -> int:
    if not home.log.exists():
        say(f"no log yet ({home.log})")
        return 0
    for ln in tail_lines(home.log, args.lines):
        say(ln)
    if args.follow:
        try:
            with home.log.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(0, os.SEEK_END)
                while True:
                    line = fh.readline()
                    if line:
                        sys.stdout.write(line)
                        sys.stdout.flush()
                    else:
                        time.sleep(0.3)
        except KeyboardInterrupt:
            return 0
    return 0


_FAULT_SCAN = re.compile(r"ERROR|CRITICAL|Traceback|address already in use|Error:")


def cmd_fault(home: Home, args: argparse.Namespace) -> int:
    entries = read_faults(home)
    if entries:
        if args.all:
            say(f"{len(entries)} fault(s), oldest first:")
            for e in entries:
                say("  " + e["ts"] + "  " + e["kind"].ljust(13) + e["reason"])
            return 0
        e = entries[-1]
        say(f"last fault : {e['ts']}  ({e['kind']})")
        say(f"reason     : {e['reason']}")
        if e.get("hint"):
            say(f"try        : {e['hint']}")
        if e.get("context"):
            say("context    : last log lines before it was recorded")
            for ln in e["context"][-15:]:
                say("  " + ln)
        return 0

    lines = tail_lines(home.log, 2000)
    if not lines:
        say(f"no faults recorded and no log content yet ({home.log})")
        return 0
    hits = [(i, ln) for i, ln in enumerate(lines) if _FAULT_SCAN.search(ln)]
    if not hits:
        say("no faults recorded; the log has no ERROR/Traceback lines")
        say("last lines:")
        for ln in lines[-8:]:
            say("  " + ln)
        return 0
    reason, hint, _ = diagnose(lines[-80:])
    say(f"no faults recorded in {home.faults.name}, but the log has errors:")
    say(f"reason     : {reason}")
    say(f"try        : {hint}")
    say("matches    :")
    for _, ln in hits[-3:]:
        say("  " + ln[:300])
    at = hits[-1][0]
    say("context    :")
    for ln in lines[max(0, at - 3): at + 16]:
        say("  " + ln)
    return 0


# ----------------------------------------------------------------- health ---

Check = tuple[str, str, str]  # name, ok|warn|fail, detail


def collect_health(home: Home) -> tuple[str, list[Check]]:
    rows: list[Check] = []
    pid, port = read_pid(home), read_port(home)
    url = f"http://127.0.0.1:{port or base_port(home)}"
    if pid_alive(pid):
        up, _ = proc_info(pid)  # type: ignore[arg-type]
        rows.append(("process", "ok", f"running, pid {pid}, up {up or '?'}"))
    else:
        rows.append(("process", "fail", "not running (serpent start)"))

    try:
        settings = load_settings_for(home)
    except Exception as exc:
        settings = None
        rows.append(("config", "fail", f"cannot load settings: {exc}"))

    code, _, ms = http_get(url + "/healthz", 4)
    rows.append(("healthz", "ok" if code == 200 else "fail",
                 f"200 in {ms:.0f} ms" if code == 200 else
                 "no response (down, or wrong host/port)" if code == 0 else f"{code} in {ms:.0f} ms"))

    code, body, _ = http_get(url + "/readyz", 4)
    detail = ""
    if code in (200, 503):
        try:
            d = json.loads(body)
            detail = (f"{d.get('accounts_usable', 0)}/{d.get('accounts_total', 0)} accounts usable, "
                      f"{d.get('quota_available_total', 0)} credits available")
        except ValueError:
            detail = "unreadable response"
    if code == 200:
        rows.append(("readyz", "ok", detail))
    elif code == 503:
        rows.append(("readyz", "warn", "not ready: " + (detail or "no usable accounts")))
    else:
        rows.append(("readyz", "fail", "no response" if code == 0 else f"{code} {detail}"))

    code, _, ms = http_get(url + "/", 4)
    rows.append(("dashboard", "ok" if code == 200 else "fail",
                 f"200 in {ms:.0f} ms" if code == 200 else "no response" if code == 0 else str(code)))

    if settings is not None:
        rows.append(_check_database(settings.db_path))
    rows.append(_check_disk(home.root))
    rows.append(_check_faults(home))
    if home.log.exists():
        rows.append(("log", "ok", f"{home.log.stat().st_size / 1024:.1f} KB"))
    else:
        rows.append(("log", "warn", "no log yet"))
    return url, rows


def _check_database(path: str) -> Check:
    try:
        size = os.path.getsize(path)
        conn = sqlite3.connect(path, timeout=3)
        try:
            verdict = conn.execute("PRAGMA quick_check(1)").fetchone()[0]
        finally:
            conn.close()
        writable = os.access(path, os.W_OK) and os.access(os.path.dirname(path) or ".", os.W_OK)
        if verdict != "ok":
            return ("database", "fail", f"quick_check says: {verdict}")
        if not writable:
            return ("database", "warn", f"readable ({size // 1024} KB) but not writable")
        return ("database", "ok", f"quick_check ok, {size // 1024} KB")
    except Exception as exc:
        return ("database", "fail", f"cannot open {path}: {exc}")


def _check_disk(root: Path) -> Check:
    try:
        free = shutil.disk_usage(root).free
        return ("disk", "ok" if free > 200 * 1024 * 1024 else "warn", f"{free / 1024 ** 3:.1f} GB free")
    except Exception as exc:
        return ("disk", "warn", f"cannot measure: {exc}")


def _check_faults(home: Home) -> Check:
    cutoff = time.time() - 86400
    recent = []
    for e in read_faults(home):
        try:
            stamp = datetime.strptime(e.get("ts", ""), "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
        if stamp >= cutoff:
            recent.append(e)
    if recent:
        return ("faults", "warn", f"{len(recent)} in the last 24h, newest: {recent[-1].get('reason', '?')}")
    return ("faults", "ok", "none in the last 24h")


def report(rows: list[Check], url: str, args: argparse.Namespace, label: str = "health") -> int:
    counts = {"ok": 0, "warn": 0, "fail": 0}
    for _, status, _ in rows:
        counts[status if status in counts else "fail"] += 1
    ok, warn, fail = counts["ok"], counts["warn"], counts["fail"]
    if args.json:
        say(json.dumps({"url": url, "ok": ok, "warn": warn, "fail": fail, "healthy": fail == 0,
                        "checks": [{"name": n, "status": s, "detail": d} for n, s, d in rows]}, indent=2))
    elif args.quiet:
        say(f"{label}: FAIL ({ok} ok, {warn} warn, {fail} fail) - serpent {label} for detail" if fail
            else f"{label}: PASS ({ok} ok, {warn} warn)")
    else:
        for name, status, detail in rows:
            say(f"  {name:<10} {paint(f'{status:<4}', _STATUS_COLOR.get(status, '0'))} {detail}")
        say()
        if fail:
            say(f"{label}: FAIL - {ok} ok, {warn} warn, {fail} fail")
        elif warn:
            say(f"{label}: PASS with {warn} warning(s) - {ok} ok")
        else:
            say(f"{label}: PASS - {ok} checks")
    if fail or (args.strict and warn):
        return 1
    return 0


def cmd_health(home: Home, args: argparse.Namespace) -> int:
    url, rows = collect_health(home)
    return report(rows, url, args)


def environment_checks(home: Home) -> list[Check]:
    rows: list[Check] = []
    ok = sys.version_info >= (3, 10)
    rows.append(("python", "ok" if ok else "fail", f"{sys.version.split()[0]} at {sys.executable}"))
    for mod in ("fastapi", "uvicorn", "httpx"):
        try:
            m = __import__(mod)
            rows.append((mod, "ok", getattr(m, "__version__", "installed")))
        except ImportError:
            rows.append((mod, "fail", "not installed - pip install -e ."))
    if not home.env_file.exists():
        rows.append((".env", "warn", f"missing in {home.root} - run: serpent init"))
    else:
        mode = home.env_file.stat().st_mode & 0o777
        rows.append((".env", "ok" if mode & 0o077 == 0 else "warn",
                     f"mode {mode:o}" + ("" if mode & 0o077 == 0 else " - should be 600")))
        env = read_env_file(home.env_file)
        rows.append(("auth", "ok" if env.get("ROUTER_KEYS") else "warn",
                     "ROUTER_KEYS set" if env.get("ROUTER_KEYS") else "ROUTER_KEYS empty - proxy is OPEN"))
    writable = os.access(home.root, os.W_OK)
    rows.append(("home", "ok" if writable else "fail", f"{home.root}{'' if writable else ' (not writable)'}"))
    try:
        from . import accounts, providers

        boot(home)
        n_acc, n_prov = len(accounts.list_accounts()), len(providers.list_providers())
        rows.append(("config-db", "ok" if n_acc else "warn",
                     f"{n_prov} provider(s), {n_acc} account(s)" + ("" if n_acc else " - add one: serpent accounts add")))
    except Exception as exc:
        rows.append(("config-db", "fail", str(exc)))
    return rows


def cmd_doctor(home: Home, args: argparse.Namespace) -> int:
    url, rows = collect_health(home)
    rows = environment_checks(home) + rows
    return report(rows, url, args, label="doctor")


# ----------------------------------------------------------------- verify ---

VERIFY_ADMIN, VERIFY_CLIENT, VERIFY_READ = "verify-admin", "verify-client", "verify-read"


def run_verify(home: Home | None, quiet: bool = False) -> int:
    failures = 0

    def ok(msg: str) -> None:
        if not quiet:
            say(f"  {paint('ok  ', '32')} {msg}")

    def fail(msg: str) -> None:
        nonlocal failures
        failures += 1
        say(f"  {paint('FAIL', '31')} {msg}")

    port = free_port()
    with tempfile.TemporaryDirectory(prefix="serpent-verify.") as tmp:
        scratch = Home(Path(tmp))
        scratch.ensure()
        env = server_env(scratch, {
            "ENV_FILE": str(scratch.env_file), "DB_PATH": str(scratch.data / "verify.db"),
            "ROUTER_KEYS": f"{VERIFY_ADMIN}:admin,{VERIFY_CLIENT}:client,{VERIFY_READ}:read",
            "ROUTER_KEY_HEADER": "X-Router-Key", "SERP_ACCOUNTS": "verify:verify-placeholder-key",
            "DEFAULT_QUOTA_LIMIT": "250", "BIND_HOST": "127.0.0.1", "BIND_PORT": str(port),
            "DASHBOARD_PUBLIC": "true",
        })
        for k in ("CACHE_TTL_SECONDS", "RATE_LIMIT_PER_MINUTE"):
            env.pop(k, None)
        env["UPSTREAM_BASE_URL"] = "http://127.0.0.1:9"  # placeholder; verify never forwards
        # Import in a child so this process never picks up the cwd's .env.
        imp = subprocess.run([sys.executable, "-c", "import serpent.main"], capture_output=True,
                             text=True, cwd=tmp, env=env)
        if imp.returncode != 0:
            fail("importing serpent.main")
            for ln in imp.stderr.splitlines()[-25:]:
                say("    " + ln)
            return 1
        ok("imports serpent.main")
        logpath = scratch.logs / "server.log"
        with logpath.open("wb") as logfh:
            proc = subprocess.Popen(uvicorn_cmd("127.0.0.1", port, level="warning"), stdout=logfh,
                                    stderr=logfh, stdin=subprocess.DEVNULL, cwd=tmp, env=env,
                                    start_new_session=True)
        base = f"http://127.0.0.1:{port}"
        try:
            ready = False
            for _ in range(80):
                if proc.poll() is not None:
                    break
                if http_get(base + "/healthz", 2)[0] == 200:
                    ready = True
                    break
                time.sleep(0.25)
            if not ready:
                fail(f"server did not become healthy on port {port}")
                for ln in tail_lines(logpath, 30):
                    say("    " + ln)
                failures = max(failures, 1)
            else:
                ok(f"booted and answered /healthz on port {port}")
                failures += _verify_endpoints(base, ok, fail)
        finally:
            if proc.poll() is None:
                _terminate(proc.pid, 5)
    if failures and home is not None:
        record_fault(home, "verify-failed", "verify reported a failure",
                     "read the checks above; they name the broken endpoint or setting")
        eprint(f"\nverify failed - recorded in {home.faults} (serpent fault)")
    if quiet:
        say("verify: FAIL" if failures else "verify: PASS")
    elif not failures:
        say("\nverify: PASS")
    return 1 if failures else 0


def _verify_endpoints(base: str, ok: Callable[[str], None], fail: Callable[[str], None]) -> int:
    count = {"n": 0}

    def bad(msg: str) -> None:
        count["n"] += 1
        fail(msg)

    admin, client, read = ({"X-Router-Key": k} for k in (VERIFY_ADMIN, VERIFY_CLIENT, VERIFY_READ))

    def check(cond: bool, good: str, broken: str) -> None:
        ok(good) if cond else bad(broken)

    check(http_get(base + "/readyz")[0] == 200, "/readyz reports ready", "/readyz not ready")
    code, body, _ = http_get(base + "/")
    check(code == 200 and "<title>" in body, "dashboard page renders", f"dashboard returned {code}")
    check(http_get(base + "/v1/quota")[0] == 401, "unauthenticated /v1/quota is rejected (401)",
          "/v1/quota is open without a key")
    check(http_get(base + "/admin/accounts", headers=client)[0] == 403,
          "client key cannot use /admin (403)", "client key reached /admin")
    check(http_get(base + "/admin/accounts", headers=admin)[0] == 200,
          "admin key can list accounts", "admin key rejected on /admin/accounts")
    code, body, _ = http_get(base + "/v1/quota", headers=read)
    try:
        total = json.loads(body).get("quota_limit_total")
    except ValueError:
        total = None
    check(code == 200 and total == 250, "quota API reports the seeded 250 credits",
          f"quota API returned {code}, quota_limit_total={total}")
    code, body, _ = http_get(base + "/admin/providers", headers=admin)
    try:
        slugs = [p["slug"] for p in json.loads(body).get("providers", [])]
    except (ValueError, AttributeError, KeyError, TypeError):
        slugs = []
    check(code == 200 and "default" in slugs, "default provider exists",
          f"/admin/providers returned {code}, providers={slugs}")
    return count["n"]


def cmd_verify(home: Home, args: argparse.Namespace) -> int:
    return run_verify(home, quiet=args.quiet)


# ------------------------------------------------------------------- init ---

ENV_TEMPLATE = """\
# Serpent configuration - written by `serpent init`.  Mode 600: it holds router keys.
# Every setting has a default; see .env.example in the repository for the full list.

ROUTER_KEYS={keys}
ROUTER_KEY_HEADER=X-Router-Key
DASHBOARD_PUBLIC=true

# No provider is built in: add yours in Snake Charmer (Providers) or with
# `serpent providers presets` / `serpent providers add`.  Only set the next lines to
# adopt an older single-upstream setup as a provider named 'default'.
# UPSTREAM_BASE_URL=
# AUTH_STYLE=header
# AUTH_HEADER_NAME=X-API-KEY
# BIND_PORT=8971
"""


def new_router_keys() -> dict[str, str]:
    return {role: f"rk-{role}-{secrets.token_urlsafe(24)}" for role in ("admin", "client", "read")}


def write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o600)


def admin_key(home: Home) -> str | None:
    """The admin router key from .env, or None when auth is off or no admin key exists."""
    for part in read_env_file(home.env_file).get("ROUTER_KEYS", "").split(","):
        key, _, role = part.strip().rpartition(":")
        if key and role == "admin":
            return key
    return None


def next_steps(url: str, *, key: str | None) -> str:
    link = f"{url}/ui/" + (f"#key={key}" if key else "")
    return (
        "\n  Next: set it up in Snake Charmer (the web UI)\n"
        f"    1. open   {link}\n"
        "    2. Providers: choose your search API from the presets, or enter its URL\n"
        "    3. Accounts:  paste your provider API key(s)\n"
        "    4. Try it:    send a test search\n"
        "    5. Use it:    point your app at "
        f"{url}/v1/... with your client key (see the .env file)\n"
        "\n  Prefer the terminal?  serpent --help   (serpent providers add / accounts add)\n"
        "\n  After a reboot Serpent is not running: start it again with  serpent up\n"
        "  (to start at boot on Linux: serpent systemd --help, or see docs/deploying.md)\n"
    )


def cmd_up(home: Home, args: argparse.Namespace) -> int:
    """One command: initialise if needed, start, and open Snake Charmer signed in."""
    if is_running(home):
        say("Serpent is already running for this install - not starting a second copy.\n")
        print_install_info(home)
        port = read_port(home)
        local = pick_host(args.host) in ("127.0.0.1", "localhost", "::1")
        key = admin_key(home) if local else None
        if port:
            say(f"\nopen      http://127.0.0.1:{port}/ui/" + (f"#key={key}" if key else ""))
        say("stop it: serpent stop    restart: serpent restart")
        return 0
    if not home.env_file.exists():
        cmd_init(home, argparse.Namespace(force=False, json=False, from_up=True))
        say("")
    rc = cmd_start(home, argparse.Namespace(
        host=args.host, port=args.port, workers=None, wait=30, from_up=True))
    if rc:
        return rc
    port = read_port(home)
    host = pick_host(args.host)
    url = f"http://{probe_host(host)}:{port}"
    local = host in ("127.0.0.1", "localhost", "::1")
    key = admin_key(home) if local else None
    say(next_steps(url, key=key))
    if local and not args.no_open and sys.stdout.isatty():
        try:
            import webbrowser
            webbrowser.open(f"{url}/ui/" + (f"#key={key}" if key else ""))
        except Exception:
            pass
    return 0


def cmd_init(home: Home, args: argparse.Namespace) -> int:
    home.ensure()
    created = not home.env_file.exists() or args.force
    keys: dict[str, str] = {}
    if created:
        keys = new_router_keys()
        write_private(home.env_file, ENV_TEMPLATE.format(
            keys=",".join(f"{k}:{role}" for role, k in keys.items())))
    boot(home)
    from .uninstall import record_install
    record_install(home)
    if args.json:
        say(json.dumps({"home": str(home.root), "created_env": created, "keys": keys}, indent=2))
        return 0
    say(f"home      {home.root}")
    say("database  ready (no provider yet: you add yours in Snake Charmer)")
    if created:
        say(f"config    wrote {home.env_file} (mode 600)\n")
        for role, key in keys.items():
            say(f"  {role + ' key':<11}: {key}")
        say("\n  Keep these safe - they are shown once. Admin manages; client sends searches; read views quota.")
    else:
        say(f"config    kept existing {home.env_file} (use --force to regenerate keys)")
    if not getattr(args, "from_up", False):
        say("\nnext      serpent up      (starts it and opens the Snake Charmer web UI)")
    return 0


# ----------------------------------------------------------- management -----


def _providers_by_id() -> dict:
    from . import providers
    return {p.id: p for p in providers.list_providers()}


def _provider_id(slug: str | None) -> int | None:
    if not slug:
        return None
    from . import providers
    try:
        return providers.get_provider(slug).id
    except providers.ProviderError as exc:
        raise CliError(str(exc)) from exc


def _guard_errors():
    from . import accounts, providers, tunables
    return (accounts.AccountError, providers.ProviderError, tunables.TunableError)


def _account_rows(settings, provider_slug: str | None) -> list[dict]:
    from . import quota
    period = quota.current_period(reset_day=settings.quota_reset_day)
    rows = quota.accounts_snapshot(period, reset_day=settings.quota_reset_day,
                                   reserve_floor=settings.quota_reserve)
    if provider_slug:
        pid = _provider_id(provider_slug)
        rows = [r for r in rows if r.get("provider_id") == pid]
    return rows


def cmd_accounts_list(home: Home, args: argparse.Namespace) -> int:
    from . import accounts, quota
    settings = boot(home)
    rows = _account_rows(settings, args.provider)
    hints = {a["id"]: a["key_hint"] for a in accounts.list_accounts()}
    provs = _providers_by_id()
    if args.json:
        for r in rows:
            r["key_hint"] = hints.get(r["id"], "****")
            r["provider"] = provs[r["provider_id"]].slug if r.get("provider_id") in provs else None
        say(json.dumps(rows, indent=2))
        return 0
    if not rows:
        say("no accounts configured")
        return 0
    period = quota.current_period(reset_day=settings.quota_reset_day)
    say(f"period {period}  (resets on day {settings.quota_reset_day}, UTC)")
    say(table(
        [(r["id"], r["label"][:18], provs[r["provider_id"]].slug if r.get("provider_id") in provs else "-",
          r["status"] + ("*" if r.get("on_cooldown") else ""), f"{r['used']}/{r['quota_limit']}",
          r["available"], hints.get(r["id"], "****"), r["last_used_at"] or "-") for r in rows],
        ["#", "label", "provider", "status", "used", "avail", "key", "last used"]))
    agg = quota.aggregate(period, reset_day=settings.quota_reset_day, reserve_floor=settings.quota_reserve)
    say(f"\n{agg['accounts_usable']}/{agg['accounts_total']} usable  "
        f"available {agg['quota_available_total']}/{agg['quota_limit_total']}  resets {agg['resets_at']}")
    if any(r.get("on_cooldown") for r in rows):
        say("(* cooling down after an upstream failure)")
    return 0


def _read_secret(arg: str | None, prompt: str) -> str:
    if arg and arg != "-":
        return arg
    if arg == "-" or not sys.stdin.isatty():
        return sys.stdin.readline().strip()
    return getpass.getpass(prompt).strip()


def cmd_accounts_add(home: Home, args: argparse.Namespace) -> int:
    from . import accounts
    settings = boot(home)
    key = _read_secret(args.key, "provider api key (hidden): ")
    provider_id = _provider_id(args.provider)
    if provider_id is None:
        existing = len(accounts.list_accounts())
    else:
        existing = sum(1 for a in accounts.list_accounts() if a.get("provider_id") == provider_id)
    if existing:
        print(
            f"warning: this provider already has {existing} account(s). Many providers forbid using\n"
            "multiple accounts to get around free-tier limits and may suspend them; check their terms.\n"
            "See docs/responsible-use.md. This is only a reminder; nothing is blocked.",
            file=sys.stderr,
        )
    try:
        acc = accounts.add_account(
            key, label=args.label, notes=args.notes, provider_id=provider_id,
            quota_limit=args.limit if args.limit is not None else settings.default_quota_limit)
    except _guard_errors() as exc:
        raise CliError(str(exc)) from exc
    say(json.dumps(acc, indent=2))
    return 0


def cmd_accounts_set(home: Home, args: argparse.Namespace) -> int:
    from . import accounts, quota
    settings = boot(home)
    verb = args.cmd2
    try:
        if verb in ("enable", "disable"):
            acc = accounts.update_account(args.id, status="active" if verb == "enable" else "disabled")
            say(json.dumps(acc, indent=2))
        elif verb == "remove":
            accounts.delete_account(args.id)
            say(f"deleted account {args.id}")
        elif verb == "reset":
            period = quota.current_period(reset_day=settings.quota_reset_day)
            accounts.get_account(args.id)
            quota.reset_account(args.id, period)
            say(f"reset quota for account {args.id} in {period}")
        elif verb == "move":
            acc = accounts.update_account(args.id, provider_id=_provider_id(args.provider))
            say(f"account {args.id} now belongs to provider id {acc['provider_id']}")
    except _guard_errors() as exc:
        raise CliError(str(exc)) from exc
    return 0


def cmd_providers(home: Home, args: argparse.Namespace) -> int:
    from . import providers
    boot(home)
    verb = args.cmd2
    try:
        if verb == "presets":
            say(table([(k, v["name"], v["base_url"], v["auth_style"]) for k, v in providers.PRESETS.items()],
                      ["preset", "name", "base url", "auth"]))
        elif verb == "list":
            counts = {r[0]: r[1] for r in _provider_account_counts()}
            rows = [(p.slug, p.name, p.base_url, p.auth_style, "yes" if p.enabled else "no",
                     counts.get(p.id, 0)) for p in providers.list_providers()]
            if args.json:
                say(json.dumps([p.public() for p in providers.list_providers()], indent=2))
            else:
                say(table(rows, ["slug", "name", "base url", "auth", "enabled", "accounts"]))
        elif verb == "add":
            p = providers.add_provider(
                args.slug, name=args.name or "", preset=args.preset, base_url=args.base_url or "",
                auth_style=args.auth_style or "", auth_header_name=args.auth_header_name or "",
                auth_param_name=args.auth_param_name or "")
            say(f"added provider {p.slug}  {p.base_url}  auth={p.auth_style}")
            say(f"route: /p/{p.slug}/<path>   add accounts: serpent accounts add --provider {p.slug}")
        elif verb in ("enable", "disable"):
            providers.update_provider(args.slug, enabled=(verb == "enable"))
            say(f"{verb}d provider {args.slug}")
        elif verb == "remove":
            providers.delete_provider(args.slug)
            say(f"removed provider {args.slug}")
    except _guard_errors() as exc:
        raise CliError(str(exc)) from exc
    return 0


def _provider_account_counts() -> list[tuple[int, int]]:
    from . import db
    rows = db.connection().execute(
        "SELECT provider_id, COUNT(*) FROM accounts WHERE provider_id IS NOT NULL GROUP BY provider_id")
    return [(r[0], r[1]) for r in rows]


def cmd_chains(home: Home, args: argparse.Namespace) -> int:
    from . import providers
    boot(home)
    verb = args.cmd2
    try:
        if verb == "list":
            chains = providers.list_chains()
            if args.json:
                say(json.dumps(chains, indent=2))
            elif not chains:
                say("no chains - create one: serpent chains add web serper serpapi")
            else:
                say(table([(c["slug"], " -> ".join(c["steps"]), "yes" if c["enabled"] else "no")
                           for c in chains], ["slug", "steps (tried in order)", "enabled"]))
        elif verb == "add":
            c = providers.add_chain(args.slug, args.steps, name=args.name or "")
            say(f"added chain {c['slug']}: {' -> '.join(c['steps'])}   route: /p/{c['slug']}/<path>")
        elif verb in ("enable", "disable"):
            providers.update_chain(args.slug, enabled=(verb == "enable"))
            say(f"{verb}d chain {args.slug}")
        elif verb == "remove":
            providers.delete_chain(args.slug)
            say(f"removed chain {args.slug}")
    except _guard_errors() as exc:
        raise CliError(str(exc)) from exc
    return 0


def cmd_route(home: Home, args: argparse.Namespace) -> int:
    from . import providers
    boot(home)
    try:
        if args.cmd2 == "set":
            slug = providers.set_default_route(args.slug)
            say(f"default route is now {slug}  (/v1/* goes there)")
            return 0
        slug = providers.get_default_route()
        steps = providers.resolve(slug)
    except _guard_errors() as exc:
        raise CliError(str(exc)) from exc
    say(f"default route : {slug}   (/v1/*)")
    say("tries        : " + (" -> ".join(p.slug for p in steps) if steps else "(nothing enabled)"))
    return 0


def cmd_requests(home: Home, args: argparse.Namespace) -> int:
    from . import db
    boot(home)
    rows = db.connection().execute(
        "SELECT ts, method, path, status, account, provider_slug, latency_ms FROM request_log "
        "ORDER BY id DESC LIMIT ?", (max(1, min(args.n, 500)),)).fetchall()
    if args.json:
        say(json.dumps([dict(r) for r in rows], indent=2))
        return 0
    for r in rows:
        say(f"{r['ts']}  {r['method']:<4} {r['path']:<32} {r['status']}  "
            f"{(r['provider_slug'] or '-'):<10} {(r['account'] or '-'):<12} {r['latency_ms']}ms")
    if not rows:
        say("no requests logged yet")
    return 0


def cmd_seed(home: Home, args: argparse.Namespace) -> int:
    from . import accounts
    settings = boot(home)
    say(f"imported {accounts.seed_accounts(settings.account_seed, settings.default_quota_limit)} account(s)")
    return 0


def cmd_version(home: Home, args: argparse.Namespace) -> int:
    info = {"version": __version__, "python": sys.version.split()[0], "home": str(home.root)}
    say(json.dumps(info) if args.json else f"serpent {__version__}  (python {info['python']}, home {home.root})")
    return 0


# ---------------------------------------------------------------- systemd ---


def systemd_unit(home: Home, port: int, host: str, user: str) -> str:
    return f"""\
[Unit]
Description=Serpent (multi-account quota-aware SERP gateway)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={user}
WorkingDirectory={home.root}
Environment=SERPENT_HOME={home.root}
ExecStart={sys.executable} -m uvicorn serpent.main:app --host {host} --port {port} --no-access-log --log-level info
Restart=always
RestartSec=3
MemoryMax=320M
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths={home.data} {home.logs}

[Install]
WantedBy=multi-user.target
"""


def cmd_systemd(home: Home, args: argparse.Namespace) -> int:
    unit = systemd_unit(home, base_port(home, args.port), args.host or "0.0.0.0",
                        args.user or getpass.getuser())
    if args.out:
        Path(args.out).write_text(unit, encoding="utf-8")
        say(f"wrote {args.out}")
    else:
        sys.stdout.write(unit)
    if args.install:
        target = args.out or "serpent.service"
        eprint("\n# To install (serpent never runs sudo itself):")
        if not args.out:
            eprint("#   serpent systemd --out serpent.service")
        eprint(f"#   sudo cp {target} /etc/systemd/system/serpent.service")
        eprint("#   sudo systemctl daemon-reload && sudo systemctl enable --now serpent")
        eprint("# Do not run `serpent start` at the same time - both would want the port.")
    return 0


def cmd_uninstall(home: Home, args: argparse.Namespace) -> int:
    from .uninstall import cmd_uninstall as run
    return run(home, args)


# ------------------------------------------------------------------- move ---

REMOTE_PATH = re.compile(r"^[A-Za-z0-9._/@~+-]+$")
CODE_ITEMS = ("src", "tests", "scripts", "deploy", "docs", "branding", "ui", "pyproject.toml",
              "requirements.txt", "README.md", "LICENSE", "NOTICE", "CHANGELOG.md", ".env.example",
              "install.sh", "ctl.sh", "Dockerfile")
SKIP_DIRS = {".venv", "__pycache__", ".pytest_cache", ".git", "node_modules", ".ruff_cache", ".mypy_cache"}


@dataclass
class MovePlan:
    src: Path
    remote: str
    dest: str
    mode: str
    with_env: bool
    with_data: bool


def parse_target(target: str) -> tuple[str, str]:
    """Split a move target into (remote, path); remote is '' for a local directory."""
    if target.startswith("ssh://"):
        rest = target[len("ssh://"):]
        host, _, path = rest.partition("/")
        return host, "/" + path
    if target.startswith(("/", "./", "../", "~", ".")):
        return "", target
    if ":" in target:
        host, _, path = target.partition(":")
        return host, path
    return "", target


def check_move_safety(src: Path, dest: Path, force: bool) -> None:
    if dest == src:
        raise CliError("source and destination are the same directory")
    if src in dest.parents:
        raise CliError(f"destination is inside the source ({dest})")
    if dest in src.parents:
        raise CliError(f"source is inside the destination ({src})")
    if dest in (Path("/"), Path.home()):
        raise CliError(f"refusing to deploy into {dest}")
    if dest.exists() and any(dest.iterdir()):
        previous = (dest / "src" / "serpent" / "main.py").exists() or (dest / ".env").exists()
        if not previous and not force:
            raise CliError(f"{dest} exists and is not a previous copy of this project (use --force)")


def copy_selection(plan: MovePlan) -> list[str]:
    """Top-level names under src to transfer."""
    names = list(CODE_ITEMS) if plan.src.joinpath("pyproject.toml").exists() else []
    names.append("deploy")
    if plan.with_env:
        names.append(".env")
    if plan.with_data:
        names.append("data")
    return sorted({n for n in names if (plan.src / n).exists()})


def _ignore(_dir: str, names: list[str]) -> set[str]:
    return {n for n in names if n in SKIP_DIRS or n.endswith(".pyc") or n == ".DS_Store"
            or n.endswith((".db-wal", ".db-shm"))}


def copy_local(plan: MovePlan, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in copy_selection(plan):
        s, d = plan.src / name, dest / name
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True, ignore=_ignore, symlinks=True)
        else:
            shutil.copy2(s, d)
    if plan.with_env and (dest / ".env").exists():
        os.chmod(dest / ".env", 0o600)


def copy_remote(plan: MovePlan) -> None:
    excludes = [f"--exclude={n}" for n in sorted(SKIP_DIRS)] + ["--exclude=*.pyc", "--exclude=.DS_Store"]
    tar = subprocess.Popen(["tar", "-czf", "-", *excludes, "-C", str(plan.src), *copy_selection(plan)],
                           stdout=subprocess.PIPE)
    ssh = subprocess.run(["ssh", "-o", "BatchMode=yes", plan.remote,
                          f"mkdir -p '{plan.dest}' && tar -xzf - -C '{plan.dest}'"],
                         stdin=tar.stdout, capture_output=True, text=True)
    tar.wait()
    if ssh.returncode != 0 or tar.returncode != 0:
        raise CliError(f"tar over ssh failed: {ssh.stderr.strip()[:200]}")


def _run_step(cmd: list[str], **kw) -> bool:
    sys.stdout.flush()
    return subprocess.run(cmd, **kw).returncode == 0


def install_and_verify(plan: MovePlan, dest: Path | None, verify: bool) -> bool:
    """Run the destination's own installer, then `serpent verify` there."""
    checkout = plan.src.joinpath("pyproject.toml").exists()
    if plan.remote:
        inner = "bash ./install.sh" if checkout else "true"
        if verify:
            inner += (" && .venv/bin/serpent verify" if checkout
                      else " && SERPENT_HOME=. serpent verify")
        return _run_step(["ssh", "-o", "BatchMode=yes", "-t", plan.remote, f"cd '{plan.dest}' && {inner}"])
    assert dest is not None
    env = {**os.environ, "SERPENT_HOME": str(dest)}
    if checkout and not _run_step(["bash", str(dest / "install.sh")], cwd=dest, env=env):
        return False
    if not verify:
        return True
    py = dest / ".venv" / "bin" / "python"
    exe = str(py) if py.exists() else sys.executable
    return _run_step([exe, "-m", "serpent.cli", "--home", str(dest), "verify"], env=env, cwd=dest)


def cmd_move(home: Home, args: argparse.Namespace) -> int:
    remote, raw = parse_target(args.dest)
    if remote and not raw:
        raise CliError(f"remote target needs a path, e.g. {remote}:/home/pi/serpent")
    if remote and not REMOTE_PATH.match(raw):
        raise CliError(f"remote path may only contain letters, digits and . _ / @ ~ + - (got: {raw})")
    plan = MovePlan(home.root, remote, raw, "move" if args.move else "copy", args.with_env, args.with_data)
    dest: Path | None = None
    if not remote:
        dest = Path(raw).expanduser().resolve()
        check_move_safety(home.root, dest, args.force)

    where = f"{remote}:{raw}" if remote else str(dest)
    say("==> plan")
    say(f"  from : {home.root}")
    say(f"  to   : {where}")
    say(f"  mode : {plan.mode}")
    say(f"  keep : .env={int(plan.with_env)} data={int(plan.with_data)}   (the python venv is always rebuilt)")
    say(f"  items: {', '.join(copy_selection(plan)) or '(nothing to copy)'}")
    if args.dry_run:
        say("\ndry run - nothing changed")
        return 0

    if is_running(home):
        say("stopping the running instance first")
        cmd_stop(home)
    logline(home, f"move requested -> {args.dest}")
    try:
        if remote:
            say(f"\n==> checking ssh to {remote}")
            if not _run_step(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", remote, "true"],
                             capture_output=True):
                raise CliError(f"cannot ssh to {remote} without a password prompt (set up a key first)")
            say("\n==> copying files")
            copy_remote(plan)
        else:
            say("\n==> copying files")
            assert dest is not None
            copy_local(plan, dest)
        say("\n==> installing and verifying (this can take a minute)")
        if not install_and_verify(plan, dest, verify=not args.no_verify):
            raise CliError(f"the copy at {where} did not install/verify - original left untouched")
    except CliError as exc:
        record_fault(home, "move-failed", str(exc),
                     "the destination was rejected or did not verify; the original is untouched")
        raise

    if plan.mode == "move":
        proceed = args.yes
        if not proceed:
            reply = input(f"\nDelete the original at {home.root}? [y/N] ") if sys.stdin.isatty() else ""
            proceed = reply.strip().lower() in ("y", "yes")
        if proceed:
            say("\n==> removing the original")
            shutil.rmtree(home.root)
            say(f"  removed {home.root}")
        else:
            say("keeping the original")
            plan.mode = "copy"
    say("\n==> done")
    say(f"  live at : {where}")
    say(f"  start   : {'ssh ' + remote + ' ' if remote else ''}serpent --home {raw if remote else dest} start")
    if not plan.with_env:
        if home.is_checkout:
            say("  note    : a fresh .env with new router keys was generated there (printed above)")
        else:
            say("  note    : no .env was copied - run `serpent init` there to create one")
    if not plan.with_data:
        say("  note    : accounts were not copied - add them there with `serpent accounts add`")
    return 0


# ------------------------------------------------------------------- menu ---


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return "0"


def _pause() -> None:
    try:
        input("\npress enter to continue ")
    except EOFError:
        pass


def _ns(**kw) -> argparse.Namespace:
    return argparse.Namespace(**kw)


def menu_header(home: Home) -> str:
    running = is_running(home)
    state = f"running  pid {read_pid(home)}  port {read_port(home) or '?'}" if running else "stopped"
    return "\n".join([
        "+" + "-" * 63 + "+",
        "|  " + "Serpent control".ljust(61) + "|",
        f"|  {str(home.root)[-61:]:<61}|",
        f"|  {state:<61}|",
        "+" + "-" * 63 + "+",
    ])


MENU_TEXT = """
 SERVICE
  1) start          2) stop
  3) restart        4) status

 DIAGNOSTICS
  5) health         6) doctor
  7) verify         8) log
  9) last fault

 CONFIGURE
 10) providers      11) chains & route
 12) accounts       13) add account

 PORTABILITY
 14) move or copy to another directory/host

  0) quit
"""


def _menu_run(fn: Callable[[], object]) -> None:
    try:
        fn()
    except CliError as exc:
        eprint(f"error: {exc}")
    _pause()


def _health_ns(**kw):
    return _ns(json=False, quiet=False, strict=False, **kw)


def menu_add_account(home: Home) -> None:
    label = _ask("label (e.g. serper-1): ")
    slug = _ask("provider slug (see: serpent providers list): ")
    key = getpass.getpass("provider api key (hidden): ").strip()
    limit = _ask("credits per period [default]: ")
    if not key:
        say("no key given")
        return
    cmd_accounts_add(home, _ns(key=key, label=label, provider=slug, notes=None,
                               limit=int(limit) if limit.isdigit() else None))


def menu_routing(home: Home) -> None:
    cmd_chains(home, _ns(cmd2="list", json=False))
    say()
    cmd_route(home, _ns(cmd2="show"))


def menu_move(home: Home) -> None:
    dest = _ask("destination (dir or user@host:/path): ")
    if not dest:
        return
    yes = lambda q: _ask(q + " [y/N] ").lower() in ("y", "yes")  # noqa: E731
    cmd_move(home, _ns(dest=dest, move=yes("move (delete the original afterwards)?"),
                       with_env=yes("carry .env (same router keys)?"),
                       with_data=yes("carry data/ (accounts + usage)?"),
                       no_verify=False, force=False, yes=False, dry_run=yes("dry run only?")))


def cmd_menu(home: Home) -> int:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        say("no terminal attached - try: serpent --help")
        return 0
    start_ns = _ns(host=None, port=None, workers=None, wait=30)
    actions: dict[str, Callable[[], object]] = {
        "1": lambda: cmd_start(home, start_ns),
        "2": lambda: cmd_stop(home),
        "3": lambda: cmd_restart(home, start_ns),
        "4": lambda: cmd_status(home, _ns(json=False)),
        "5": lambda: cmd_health(home, _health_ns()),
        "6": lambda: cmd_doctor(home, _health_ns()),
        "7": lambda: cmd_verify(home, _ns(quiet=False)),
        "8": lambda: cmd_log(home, _ns(lines=40, follow=False)),
        "9": lambda: cmd_fault(home, _ns(all=False)),
        "10": lambda: cmd_providers(home, _ns(cmd2="list", json=False)),
        "11": lambda: menu_routing(home),
        "12": lambda: cmd_accounts_list(home, _ns(provider=None, json=False)),
        "13": lambda: menu_add_account(home),
        "14": lambda: menu_move(home),
    }
    while True:
        say("\033[H\033[2J" if _tty() else "")
        say(menu_header(home))
        say(MENU_TEXT)
        choice = _ask("choice> ").lower()
        if choice in ("0", "q", "quit", "exit"):
            say("bye")
            return 0
        action = actions.get(choice)
        if action:
            say()
            _menu_run(action)


# ----------------------------------------------------------------- parser ---


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="serpent",
        description="Serpent - quota-aware gateway for SERP APIs. Run with no arguments for a menu.")
    p.add_argument("--home", help="state directory (default: $SERPENT_HOME or the current directory)")
    sub = p.add_subparsers(dest="command", metavar="command")

    def add(name: str, fn, help_: str, aliases: Sequence[str] = ()):
        sp = sub.add_parser(name, help=help_, aliases=list(aliases), description=help_)
        sp.set_defaults(func=fn or (lambda h, a, _sp=sp: _usage(_sp)))
        return sp

    def serve_opts(sp):
        sp.add_argument("--host", help="bind address (default 127.0.0.1; 0.0.0.0 for the LAN)")
        sp.add_argument("--port", type=int, help=f"first port to try (default {DEFAULT_PORT})")

    sp = add("init", cmd_init, "create the home dir, .env with generated keys, and the database")
    sp.add_argument("--force", action="store_true", help="regenerate .env and keys")
    sp.add_argument("--json", action="store_true")

    sp = add("up", cmd_up, "first run and every day: set up if needed, start, and open the web UI")
    serve_opts(sp)
    sp.add_argument("--no-open", action="store_true", help="do not open a browser")

    sp = add("start", cmd_start, "start in the background (logged)")
    serve_opts(sp)
    sp.add_argument("--workers", type=int)
    sp.add_argument("--wait", type=float, default=30, help="seconds to wait for /healthz")
    add("stop", cmd_stop, "stop the background instance")
    sp = add("restart", cmd_restart, "stop, then start")
    serve_opts(sp)
    sp.add_argument("--workers", type=int)
    sp.add_argument("--wait", type=float, default=30)
    sp = add("run", cmd_run, "run in the foreground (unlogged)")
    serve_opts(sp)
    sp = add("status", cmd_status, "pid, url, accounts, log, last fault")
    sp.add_argument("--json", action="store_true")

    for name, fn, help_ in (("health", cmd_health, "liveness, readiness, db, disk, faults"),
                            ("doctor", cmd_doctor, "health plus environment checks")):
        sp = add(name, fn, help_)
        sp.add_argument("-q", "--quiet", action="store_true")
        sp.add_argument("--json", action="store_true")
        sp.add_argument("--strict", action="store_true", help="fail on warnings too")

    sp = add("log", cmd_log, "tail logs/router.log", aliases=["logs"])
    sp.add_argument("-n", "--lines", type=int, default=40)
    sp.add_argument("-f", "--follow", action="store_true")
    sp = add("fault", cmd_fault, "last incident: reason, hint and log context", aliases=["faults"])
    sp.add_argument("-a", "--all", action="store_true")
    sp = add("verify", cmd_verify, "boot a scratch copy on a throwaway DB and check the endpoints")
    sp.add_argument("-q", "--quiet", action="store_true")

    sp = add("move", cmd_move, "copy/move this install to a directory or user@host:/path")
    sp.add_argument("dest")
    sp.add_argument("--move", action="store_true", help="remove the original after a successful verify")
    sp.add_argument("--copy", dest="move", action="store_false")
    sp.add_argument("--with-env", action="store_true", help="carry .env (keeps router keys)")
    sp.add_argument("--with-data", action="store_true", help="carry data/ (accounts, usage)")
    sp.add_argument("--no-verify", action="store_true")
    sp.add_argument("--force", action="store_true")
    sp.add_argument("-y", "--yes", action="store_true", help="do not ask before deleting the source")
    sp.add_argument("--dry-run", action="store_true")

    acc = add("accounts", None, "manage provider accounts")
    asub = acc.add_subparsers(dest="cmd2")
    sp = asub.add_parser("list", help="show accounts and quota")
    sp.add_argument("--provider")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_accounts_list)
    sp = asub.add_parser("add", help="register a provider account")
    sp.add_argument("--key", help="API key ('-' or omit to read it from stdin / a hidden prompt)")
    sp.add_argument("--label", default="")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--notes")
    sp.add_argument("--provider", help="provider slug (default: 'default')")
    sp.set_defaults(func=cmd_accounts_add)
    for verb in ("enable", "disable", "remove", "reset"):
        sp = asub.add_parser(verb, help=f"{verb} an account")
        sp.add_argument("id", type=int)
        sp.set_defaults(func=cmd_accounts_set)
    sp = asub.add_parser("move", help="move an account to another provider")
    sp.add_argument("id", type=int)
    sp.add_argument("--provider", required=True)
    sp.set_defaults(func=cmd_accounts_set)

    prov = add("providers", None, "manage upstream providers")
    psub = prov.add_subparsers(dest="cmd2")
    for verb in ("list", "presets"):
        sp = psub.add_parser(verb)
        sp.add_argument("--json", action="store_true")
        sp.set_defaults(func=cmd_providers)
    sp = psub.add_parser("add", help="add a provider from a preset or a custom URL")
    sp.add_argument("slug")
    sp.add_argument("--preset")
    sp.add_argument("--name")
    sp.add_argument("--base-url")
    sp.add_argument("--auth-style", choices=["header", "query", "bearer"])
    sp.add_argument("--auth-header-name")
    sp.add_argument("--auth-param-name")
    sp.set_defaults(func=cmd_providers)
    for verb in ("enable", "disable", "remove"):
        sp = psub.add_parser(verb)
        sp.add_argument("slug")
        sp.set_defaults(func=cmd_providers)

    ch = add("chains", None, "manage fallback chains")
    csub = ch.add_subparsers(dest="cmd2")
    sp = csub.add_parser("list")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_chains)
    sp = csub.add_parser("add", help="chains add SLUG provider1 provider2 ...")
    sp.add_argument("slug")
    sp.add_argument("steps", nargs="+")
    sp.add_argument("--name")
    sp.set_defaults(func=cmd_chains)
    for verb in ("enable", "disable", "remove"):
        sp = csub.add_parser(verb)
        sp.add_argument("slug")
        sp.set_defaults(func=cmd_chains)

    rt = add("route", None, "show or set the default route used by /v1/*")
    rsub = rt.add_subparsers(dest="cmd2")
    rsub.add_parser("show").set_defaults(func=cmd_route)
    sp = rsub.add_parser("set")
    sp.add_argument("slug")
    sp.set_defaults(func=cmd_route)

    sp = add("requests", cmd_requests, "recent proxied requests")
    sp.add_argument("-n", type=int, default=20)
    sp.add_argument("--json", action="store_true")
    add("seed", cmd_seed, "import SERP_ACCOUNTS from the environment")
    sp = add("uninstall", cmd_uninstall, "stop Serpent and remove what the install created (asks about your data)")
    sp.add_argument("--keep-data", action="store_true", help="keep data/ and .env (the default with --yes)")
    sp.add_argument("--delete-data", action="store_true", help="also delete the database and .env")
    sp.add_argument("--yes", "-y", action="store_true", help="do not ask questions")
    sp.add_argument("--dry-run", action="store_true", help="show what would happen and change nothing")

    sp = add("systemd", cmd_systemd, "print a systemd unit with this machine's real paths")
    serve_opts(sp)
    sp.add_argument("--user")
    sp.add_argument("--out", help="write the unit to a file")
    sp.add_argument("--install", action="store_true", help="also print the install commands")
    sp = add("version", cmd_version, "print version information")
    sp.add_argument("--json", action="store_true")
    return p


def _usage(parser: argparse.ArgumentParser) -> int:
    parser.print_help()
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    home = resolve_home(args.home)
    try:
        if not getattr(args, "func", None):
            if sys.stdin.isatty() and sys.stdout.isatty():
                return cmd_menu(home)
            parser.print_help()
            return 0
        return int(args.func(home, args) or 0)
    except CliError as exc:
        eprint(f"error: {exc}")
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        try:
            from . import db
            db.close_current_thread()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
