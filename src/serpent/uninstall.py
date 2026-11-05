"""``serpent uninstall``: find what an install left behind, remove it, and check the result.

Nothing here guesses.  Every item is looked up on disk first; the plan is shown; only
then is anything removed; afterwards each item is looked at again and reported.
Your data (``data/`` and ``.env``) is kept unless you say otherwise, so the server can
be deployed differently without starting from scratch.  The source checkout itself is
never deleted, and neither is anything outside this install (no ``sudo``).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from . import __version__
from .cli import (
    CliError,
    Home,
    _ask,
    _terminate,
    clear_run_files,
    eprint,
    pid_alive,
    read_pid,
    read_port,
    say,
    table,
)

MANIFEST = ".serpent-install.json"
SYSTEM_UNIT = Path("/etc/systemd/system/serpent.service")
DIST_NAME = "serpent-router"

# What a plan item does when it is carried out.
KEEP, REMOVE, STOP, MANUAL = "keep", "remove", "stop", "manual"


# ------------------------------------------------------------- manifest -----


def manifest_path(home: Home) -> Path:
    return home.root / MANIFEST


def read_manifest(home: Home) -> dict:
    try:
        return json.loads(manifest_path(home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record_install(home: Home) -> None:
    """Note what the installer created, so uninstall removes exactly that.

    ``install.sh`` sets ``SERPENT_VENV_CREATED=1`` when it made ``.venv`` itself; a
    virtualenv that was already there is never claimed.
    """
    data = read_manifest(home)
    data.setdefault("installed_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    data["version"] = __version__
    data["home"] = str(home.root)
    if os.environ.get("SERPENT_VENV_CREATED") == "1":
        data["venv_created"] = True
    try:
        manifest_path(home).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass  # a read-only home must not break `serpent init`


def remembered_port(home: Home) -> int | None:
    port = read_manifest(home).get("port")
    return port if isinstance(port, int) else None


def remember_port(home: Home, port: int) -> None:
    """Pin this install to ``port``: later starts try it first (see ``cli.base_port``)."""
    data = read_manifest(home)
    if data.get("port") == port:
        return
    data["port"] = port
    try:
        manifest_path(home).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


# ------------------------------------------------------------ inventory -----


@dataclass
class Item:
    key: str
    what: str
    where: str
    category: str  # "data" (kept on request), "install" or "system"
    action: str = REMOVE
    size: int = 0
    note: str = ""
    path: Path | None = None
    result: str = ""  # filled in by verify()
    ok: bool = True


@dataclass
class Inventory:
    home: Home
    items: list[Item] = field(default_factory=list)
    running_pid: int | None = None
    port: int | None = None

    def get(self, key: str) -> Item | None:
        return next((i for i in self.items if i.key == key), None)


def _size(path: Path) -> int:
    if path.is_file() or path.is_symlink():
        try:
            return path.lstat().st_size
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda _e: None):
        for name in files:
            try:
                total += (Path(root) / name).lstat().st_size
            except OSError:
                pass
    return total


def human(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def port_open(port: int | None) -> bool:
    if not port:
        return False
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _in_venv(home: Home) -> bool:
    try:
        return Path(sys.prefix).resolve() == (home.root / ".venv").resolve()
    except OSError:
        return False


def scan(home: Home) -> Inventory:
    inv = Inventory(home)
    manifest = read_manifest(home)
    root = home.root

    pid = read_pid(home)
    if pid_alive(pid):
        inv.running_pid, inv.port = pid, read_port(home)
        where = f"pid {pid}" + (f", port {inv.port}" if inv.port else "")
        inv.items.append(Item("daemon", "the running server", where, "install", STOP))

    def add(key, what, rel, category, note="", action=REMOVE):
        path = root / rel
        if path.exists() or path.is_symlink():
            inv.items.append(Item(key, what, str(path), category, action,
                                  _size(path), note, path))

    add("data", "database: accounts, provider keys, request history", "data", "data")
    add("env", "settings and router keys (.env)", ".env", "data")
    add("logs", "logs", "logs", "install")
    add("run", "runtime files (pid, port)", "run", "install")
    add("unit", "generated systemd unit file", "deploy/serpent.local.service", "install")

    venv = root / ".venv"
    if venv.is_dir() and (manifest.get("venv_created") or (venv / "bin" / "serpent").exists()):
        note = "" if manifest.get("venv_created") else "created by install.sh (no manifest found)"
        add("venv", "virtualenv with Serpent installed", ".venv", "install", note)

    if SYSTEM_UNIT.exists():
        inv.items.append(Item(
            "system-unit", "systemd service", str(SYSTEM_UNIT), "system", MANUAL,
            note="needs sudo: sudo systemctl disable --now serpent && "
                 f"sudo rm {SYSTEM_UNIT} && sudo systemctl daemon-reload",
            path=SYSTEM_UNIT))

    pkg = _outside_package(home)
    if pkg and inv.items:  # a package alone does not make this folder an install
        inv.items.append(pkg)

    if manifest_path(home).exists():
        add("manifest", "install record", MANIFEST, "install")
    return inv


def _outside_package(home: Home) -> Item | None:
    """Serpent installed into a Python environment other than this checkout's .venv.

    That environment may serve other Serpent homes, so it is never removed for you:
    the exact command is printed instead.
    """
    if _in_venv(home):
        return None
    try:
        metadata.distribution(DIST_NAME)
    except metadata.PackageNotFoundError:
        return None
    pipx = "pipx" in Path(sys.prefix).parts
    cmd = f"pipx uninstall {DIST_NAME}" if pipx else f"{sys.executable} -m pip uninstall {DIST_NAME}"
    return Item("package", f"Python package {DIST_NAME}", sys.prefix, "install", MANUAL,
                note=f"may serve other installs, so not removed automatically: {cmd}")


# ----------------------------------------------------------------- plan -----


def apply_choice(inv: Inventory, keep_data: bool) -> None:
    for item in inv.items:
        if item.category == "data":
            item.action = KEEP if keep_data else REMOVE


def show_plan(inv: Inventory) -> None:
    say(f"\nInstall at {inv.home.root}\n")
    rows = []
    for i in inv.items:
        size = human(i.size) if i.size else ""
        rows.append((i.action.upper(), i.what, size, i.where))
    say(table(rows, ["ACTION", "WHAT", "SIZE", "WHERE"]))
    notes = [i for i in inv.items if i.note]
    for i in notes:
        say(f"  - {i.what}: {i.note}")


# -------------------------------------------------------------- execute -----


def _rm(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def execute(inv: Inventory) -> None:
    home = inv.home
    # Stop first, so nothing is writing while files are removed.
    for item in inv.items:
        if item.action == STOP and inv.running_pid:
            _terminate(inv.running_pid, 10)
            clear_run_files(home)
    # The virtualenv holds the interpreter that is running us: remove it last.
    ordered = sorted(inv.items, key=lambda i: i.key == "venv")
    for item in ordered:
        if item.action != REMOVE:
            continue
        try:
            if item.path is not None:
                _rm(item.path)
        except OSError as exc:
            item.result = f"error: {exc}"


def verify(inv: Inventory) -> int:
    """Look at everything again; return the number of problems."""
    problems = 0
    for item in inv.items:
        if item.action == STOP:
            alive = pid_alive(inv.running_pid) or port_open(inv.port)
            item.ok = not alive
            item.result = "stopped" if item.ok else "STILL RUNNING"
        elif item.action == REMOVE:
            item.ok = not (item.path and (item.path.exists() or item.path.is_symlink()))
            item.result = item.result if item.result.startswith("error") else (
                "removed" if item.ok else "STILL PRESENT")
        elif item.action == KEEP:
            item.ok = bool(item.path and item.path.exists())
            item.result = "kept" if item.ok else "MISSING (expected to be kept)"
        else:
            item.ok, item.result = True, "do this yourself (see above)"
        problems += 0 if item.ok else 1
    return problems


# ------------------------------------------------------------- command ------


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def cmd_uninstall(home: Home, args: argparse.Namespace) -> int:
    if args.keep_data and args.delete_data:
        raise CliError("choose one of --keep-data and --delete-data")
    inv = scan(home)
    if not inv.items:
        say(f"Nothing from Serpent was found at {home.root}.")
        return 0

    interactive = _interactive() and not args.yes
    if not interactive and not args.yes and not args.dry_run:
        raise CliError("not a terminal: add --yes (and --keep-data or --delete-data), "
                       "or --dry-run to preview")

    has_data = any(i.category == "data" for i in inv.items)
    if args.delete_data:
        keep = False
    elif args.keep_data or args.yes or args.dry_run:
        keep = True  # the safe default whenever nobody was asked
    elif has_data:
        say("\nYour data is the database (accounts, provider keys, request history) and .env.")
        say("Keeping it lets you redeploy later (another folder, Docker, systemd) without")
        say("re-entering anything.")
        keep = _ask("\nKeep your data and settings? [Y/n] ").lower() not in ("n", "no")
    else:
        keep = True
    apply_choice(inv, keep)
    show_plan(inv)

    if args.dry_run:
        say("\n(dry run: nothing was changed)")
        return 0

    if not keep and has_data:
        size = sum(i.size for i in inv.items if i.category == "data")
        if interactive:
            say(f"\nThis permanently deletes {human(size)} of data, including provider API keys.")
            if _ask("Type 'delete' to confirm: ") != "delete":
                say("Cancelled. Nothing was changed.")
                return 1
    elif interactive and _ask("\nProceed? [y/N] ").lower() not in ("y", "yes"):
        say("Cancelled. Nothing was changed.")
        return 1

    execute(inv)
    problems = verify(inv)

    say("\nResult\n")
    say(table([("OK" if i.ok else "FAIL", i.what, i.result) for i in inv.items],
              ["", "WHAT", "RESULT"]))
    manual = [i for i in inv.items if i.action == MANUAL]
    if manual:
        say("\nStill to do by hand:")
        for i in manual:
            say(f"  - {i.what}: {i.note}")
    if keep and has_data:
        say(f"\nYour data is still in {home.root}. To run Serpent again, install it and use")
        say(f"  SERPENT_HOME={home.root} serpent up")
        say("or copy data/ and .env to the new location (serpent move does this).")
    if home.is_checkout and not (keep and has_data):
        say(f"\nThe source folder was left alone; delete it yourself if you are done:\n  rm -rf {home.root}")
    elif home.is_checkout:
        say("\nThe source folder was left alone. Do not delete it while you want to keep the data in it.")
    if problems:
        eprint(f"\nuninstall finished with {problems} problem(s); see FAIL rows above")
        return 1
    say("\nuninstall: verified clean")
    return 0
