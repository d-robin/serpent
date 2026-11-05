"""Find, show and rotate keys.

Router keys (the ones callers and the admin use) live in ``.env``; provider API keys
(the ones you paste into accounts) live in the database.  Both are plain text on disk,
protected by file mode 0600, so recovering one means reading it back.  Nothing here
sends a key anywhere.
"""

from __future__ import annotations

import re
import secrets
import shutil
import subprocess
import sys

from .cli import Home, probe_host, read_env_file, read_port, write_private

ROLES = ("admin", "client", "read")


def mask(key: str) -> str:
    return f"{key[:3]}...{key[-4:]}" if len(key) > 10 else "****"


def router_keys(home: Home) -> list[tuple[str, str]]:
    """``[(role, key)]`` from ROUTER_KEYS in .env, in file order."""
    out = []
    for part in read_env_file(home.env_file).get("ROUTER_KEYS", "").split(","):
        key, _, role = part.strip().rpartition(":")
        if key and role:
            out.append((role, key))
    return out


def account_keys() -> list[dict]:
    """Provider keys from the database: id, label, provider slug and the full key."""
    from . import db

    rows = db.connection().execute(
        "SELECT a.id, a.label, a.api_key, p.slug AS provider FROM accounts a "
        "LEFT JOIN providers p ON p.id = a.provider_id ORDER BY a.id")
    return [{"id": r["id"], "label": r["label"], "provider": r["provider"], "key": r["api_key"]}
            for r in rows]


def rotate_router_key(home: Home, role: str) -> str:
    """Replace the key for ``role`` in .env (adding one if absent); returns the new key.

    The running server reads .env only at start, so it must be restarted.
    """
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")
    pairs = router_keys(home)
    new = f"rk-{role}-{secrets.token_urlsafe(24)}"
    if any(r == role for r, _ in pairs):
        pairs = [(r, new if r == role else k) for r, k in pairs]
    else:
        pairs.append((role, new))
    line = "ROUTER_KEYS=" + ",".join(f"{k}:{r}" for r, k in pairs)
    try:
        text = home.env_file.read_text(encoding="utf-8")
    except OSError:
        text = ""
    if re.search(r"(?m)^ROUTER_KEYS=.*$", text):
        text = re.sub(r"(?m)^ROUTER_KEYS=.*$", lambda _m: line, text, count=1)
    else:
        text = text + ("" if text.endswith("\n") or not text else "\n") + line + "\n"
    write_private(home.env_file, text)
    return new


def signin_link(home: Home) -> str | None:
    """The Snake Charmer URL that signs in as admin, or None without an admin key."""
    admin = next((k for r, k in router_keys(home) if r == "admin"), None)
    if admin is None:
        return None
    from .cli import base_port

    port = read_port(home) or base_port(home)
    return f"http://{probe_host('127.0.0.1')}:{port}/ui/#key={admin}"


def copy_to_clipboard(text: str) -> str | None:
    """Copy with the system tool if there is one; returns its name, or None."""
    candidates = [["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "-ib"]]
    if sys.platform == "win32":
        candidates = [["clip"]]
    for cmd in candidates:
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text.encode(), check=True, timeout=5)
                return cmd[0]
            except (OSError, subprocess.SubprocessError):
                continue
    return None
