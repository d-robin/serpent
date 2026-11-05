"""``serpent tui``: a full-screen terminal interface for everything the CLI can do.

Move with the arrow keys or ``j``/``k``; ``Enter`` or ``→`` opens, ``←`` / ``Esc`` / ``q``
goes back, like lynx.  Each screen lists its own single-letter shortcuts on the bottom
line, and ``?`` shows them all.  Standard library only (``curses``): macOS, Linux and
the Raspberry Pi; not Windows.

The screens talk to the same code the CLI uses, so anything done here shows up in
Snake Charmer and vice versa.  Nothing is sent over the network except by the actions
you ask for (start, stop, health check, opening the web UI).
"""

from __future__ import annotations

import argparse
import contextlib
import curses
import io
import locale
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from . import cli, keys

MIN_W, MIN_H = 60, 14
ESC, ENTER_KEYS = 27, (10, 13, curses.KEY_ENTER)


# ------------------------------------------------------------------ model ----


@dataclass
class Row:
    text: str
    act: Callable[[], None] | None = None  # Enter / Right
    data: object = None  # what hotkeys receive
    style: str = ""  # "", "dim", "bold", "bad", "good"


@dataclass
class View:
    title: str
    rows: list[Row]
    lines: list[str] = field(default_factory=list)  # fixed text above the list
    hotkeys: dict[str, tuple[str, Callable[[Row | None], None]]] = field(default_factory=dict)
    refresh: float = 0.0  # seconds; 0 = only redraw on a key
    follow: bool = False  # start at the bottom and stick to it (logs)


class Nav:
    """Cursor and scroll position for a list; pure, so it can be tested without a terminal."""

    def __init__(self) -> None:
        self.cur = 0
        self.top = 0
        self.seen = False
        self.last_count = 0

    def clamp(self, count: int, height: int) -> None:
        height = max(1, height)
        self.cur = max(0, min(self.cur, count - 1)) if count else 0
        if self.cur < self.top:
            self.top = self.cur
        elif self.cur >= self.top + height:
            self.top = self.cur - height + 1
        self.top = max(0, min(self.top, max(0, count - height)))

    def move(self, delta: int, count: int, height: int) -> None:
        self.cur += delta
        self.clamp(count, height)

    def home(self, count: int, height: int) -> None:
        self.cur = 0
        self.clamp(count, height)

    def end(self, count: int, height: int) -> None:
        self.cur = max(0, count - 1)
        self.clamp(count, height)


def read_key(code: int) -> str:
    """Map a curses key code to a command: up down left right enter back page_up ..."""
    table = {
        curses.KEY_UP: "up", curses.KEY_DOWN: "down", curses.KEY_LEFT: "left",
        curses.KEY_RIGHT: "right", curses.KEY_PPAGE: "pgup", curses.KEY_NPAGE: "pgdn",
        curses.KEY_HOME: "home", curses.KEY_END: "end", ESC: "esc",
        curses.KEY_BACKSPACE: "backspace", 127: "backspace", 8: "backspace",
    }
    if code in ENTER_KEYS:
        return "enter"
    if code in table:
        return table[code]
    if 32 <= code < 127:
        return chr(code)
    return ""


NAV_KEYS = {
    "up": -1, "k": -1, "down": 1, "j": 1,
}


# -------------------------------------------------------------------- app ----


class QuitTui(Exception):
    pass


class App:
    def __init__(self, scr, home: cli.Home) -> None:
        self.scr, self.home = scr, home
        self.stack: list[tuple[Callable[[], View], Nav]] = []
        self.colors: dict[str, int] = {}
        self.under: tuple[View, Nav] | None = None  # the screen a popup sits on

    # ----- terminal plumbing

    def setup(self) -> None:
        curses.curs_set(0)
        self.scr.keypad(True)
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            for i, (name, fg) in enumerate((("good", curses.COLOR_GREEN), ("bad", curses.COLOR_RED),
                                            ("warn", curses.COLOR_YELLOW)), start=1):
                curses.init_pair(i, fg, -1)
                self.colors[name] = curses.color_pair(i)

    def attr(self, style: str) -> int:
        if style == "dim":
            return curses.A_DIM
        if style == "bold":
            return curses.A_BOLD
        return self.colors.get(style, 0)

    def put(self, y: int, x: int, text: str, attr: int = 0, width: int | None = None) -> None:
        h, w = self.scr.getmaxyx()
        if not 0 <= y < h:
            return
        limit = (w - x) if width is None else min(width, w - x)
        if limit <= 0:
            return
        try:
            self.scr.addnstr(y, x, text.ljust(limit) if attr & curses.A_REVERSE else text, limit, attr)
        except curses.error:
            pass

    def status_line(self) -> tuple[str, str]:
        if cli.is_running(self.home):
            return f"running on port {cli.read_port(self.home) or '?'}", "good"
        return "stopped", "bad"

    def draw(self, view: View, nav: Nav) -> int:
        """Draw one frame; returns the number of list rows that fit."""
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        state, style = self.status_line()
        self.put(0, 0, f" Serpent · {view.title}", curses.A_REVERSE | curses.A_BOLD)
        self.put(0, max(0, w - len(state) - 2), f" {state} ", curses.A_REVERSE | self.attr(style))
        y = 1
        for line in view.lines:
            self.put(y, 1, line, curses.A_DIM)
            y += 1
        height = max(1, h - y - 1)
        nav.clamp(len(view.rows), height)
        for i in range(height):
            idx = nav.top + i
            if idx >= len(view.rows):
                break
            row = view.rows[idx]
            selected = idx == nav.cur
            self.put(y + i, 0, ("▸ " if selected else "  ") + row.text,
                     curses.A_REVERSE if selected else self.attr(row.style))
        hint = "↑↓ move  →/Enter open  ←/q back  ?"
        extra = "  ".join(f"{k} {label}" for k, (label, _) in view.hotkeys.items())
        self.put(h - 1, 0, (f" {extra}  │ " if extra else " ") + hint, curses.A_DIM)
        self.scr.refresh()
        return height

    def getkey(self, timeout: float = 0.0) -> str:
        self.scr.timeout(int(timeout * 1000) if timeout else -1)
        code = self.scr.getch()
        if code == curses.KEY_RESIZE:
            return "resize"
        return "" if code == -1 else read_key(code)

    # ----- dialogs

    def popup(self, title: str, lines: list[str], *, options: list[str] | None = None,
              start: int = 0) -> int | None:
        """Boxed list or text; returns the chosen index, or None when dismissed."""
        sel, top = start, 0
        while True:
            if self.under:
                self.draw(*self.under)  # repaint the screen first, so nothing of an earlier popup shows
            h, w = self.scr.getmaxyx()
            width = min(w - 4, max(len(title) + 6, *(len(x) + 6 for x in lines + (options or [])), 30))
            body = lines + ([""] if lines and options else []) + (options or [])
            height = min(h - 2, len(body) + 2)
            y0, x0 = max(0, (h - height) // 2), max(0, (w - width) // 2)
            inner = height - 2
            if options:
                pos = len(lines) + (1 if lines else 0) + sel
                if sel == 0:
                    top = 0
                elif pos < top:
                    top = pos
                elif pos >= top + inner:
                    top = pos - inner + 1
            top = max(0, min(top, max(0, len(body) - inner)))
            for r in range(height):
                self.put(y0 + r, x0, " " * width, curses.A_REVERSE if r == 0 else 0)
            self.put(y0, x0 + 2, f" {title} ", curses.A_REVERSE | curses.A_BOLD)
            for r in range(inner):
                idx = top + r
                if idx >= len(body):
                    break
                is_opt = options and idx >= len(body) - len(options)
                chosen = is_opt and idx - (len(body) - len(options)) == sel
                self.put(y0 + 1 + r, x0 + 2, ("▸ " if chosen else "  ") + body[idx],
                         curses.A_REVERSE if chosen else 0, width - 3)
            self.scr.refresh()
            key = self.getkey()
            if key == "resize":
                self.scr.clear()
                continue
            if options:
                if key in ("up", "k"):
                    sel = (sel - 1) % len(options)
                elif key in ("down", "j"):
                    sel = (sel + 1) % len(options)
                elif key in ("enter", "right", "l"):
                    return sel
                elif key in ("esc", "left", "h", "q"):
                    return None
            else:
                if key in ("up", "k"):
                    top = max(0, top - 1)
                elif key in ("down", "j"):
                    top = min(max(0, len(body) - inner), top + 1)
                elif key == "pgdn":
                    top = min(max(0, len(body) - inner), top + inner)
                elif key == "pgup":
                    top = max(0, top - inner)
                elif key in ("enter", "esc", "left", "h", "q", "right", "l", " "):
                    return 0

    def choose(self, title: str, options: list[str], *, lines: list[str] | None = None,
               start: int = 0) -> int | None:
        return self.popup(title, lines or [], options=options, start=start)

    def confirm(self, question: str, *, lines: list[str] | None = None) -> bool:
        return self.popup(question, lines or [], options=["No", "Yes"]) == 1

    def message(self, title: str, text: str | list[str]) -> None:
        lines = text.splitlines() if isinstance(text, str) else text
        self.popup(title, [*lines, "", "(any key to close)"])

    def ask(self, label: str, default: str = "", *, secret: bool = False) -> str | None:
        """One-line input on the bottom row. Esc cancels (None); Enter accepts."""
        buf = default
        self.scr.timeout(-1)
        curses.curs_set(1)
        try:
            while True:
                h, w = self.scr.getmaxyx()
                shown = "*" * len(buf) if secret else buf
                prompt = f" {label}: "
                avail = max(1, w - len(prompt) - 1)
                text = shown[-avail:]
                self.put(h - 1, 0, prompt + text, curses.A_REVERSE, w)
                try:
                    self.scr.move(h - 1, min(w - 1, len(prompt) + len(text)))
                except curses.error:
                    pass
                self.scr.refresh()
                code = self.scr.get_wch()
                if code in ("\n", "\r") or code == curses.KEY_ENTER:
                    return buf.strip()
                if code == "\x1b":
                    return None
                if code in ("\x7f", "\b") or code == curses.KEY_BACKSPACE:
                    buf = buf[:-1]
                elif code == "\x15":  # ctrl-u
                    buf = ""
                elif isinstance(code, str) and code.isprintable():
                    buf += code
        finally:
            curses.curs_set(0)

    def busy(self, text: str) -> None:
        h, w = self.scr.getmaxyx()
        self.put(h - 1, 0, f" {text} ", curses.A_REVERSE, w)
        self.scr.refresh()

    def run_cli(self, title: str, fn: Callable[[], object], *, show: bool = True) -> bool:
        """Run a CLI function, capturing what it prints; errors become a message box."""
        out, err = io.StringIO(), io.StringIO()
        self.busy(f"{title}…")
        ok = True
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = fn()
            ok = not rc
        except cli.CliError as exc:
            ok, err = False, io.StringIO(str(exc))
        except Exception as exc:  # a library error must not take the screen down
            ok, err = False, io.StringIO(f"{type(exc).__name__}: {exc}")
        text = (out.getvalue() + err.getvalue()).strip()
        if show or not ok:
            self.message(title if ok else f"{title} - failed", text or "done")
        return ok

    def guarded(self, fn: Callable[[], object], ok_msg: str | None = None) -> bool:
        """Call a library function; show the error text from the usual library errors."""
        try:
            fn()
        except cli._guard_errors() as exc:
            self.message("Not done", str(exc))
            return False
        except ValueError as exc:
            self.message("Not done", str(exc))
            return False
        if ok_msg:
            self.busy(ok_msg)
            time.sleep(0.6)
        return True

    # ----- main loop

    def push(self, builder: Callable[[], View]) -> None:
        self.stack.append((builder, Nav()))

    def run(self) -> None:
        self.setup()
        if not self.home.env_file.exists() and self.confirm(
                "No Serpent install here", lines=[str(self.home.root), "", "Create one now?"]):
            self.run_cli("Set up", lambda: cli.cmd_init(
                self.home, argparse.Namespace(force=False, json=False, from_up=True)))
        cli.boot(self.home)
        self.push(self.v_main)
        while self.stack:
            builder, nav = self.stack[-1]
            view = builder()
            count = len(view.rows)
            if view.follow and (not nav.seen or nav.cur >= nav.last_count - 1):
                nav.cur = max(0, count - 1)  # stay on the newest line unless the user scrolled up
            nav.seen, nav.last_count = True, count
            height = self.draw(view, nav)
            self.under = (view, nav)
            if self.scr.getmaxyx()[0] < MIN_H or self.scr.getmaxyx()[1] < MIN_W:
                self.put(2, 1, f"terminal too small (need {MIN_W}x{MIN_H})")
                self.scr.refresh()
            key = self.getkey(view.refresh)
            if not key or key == "resize":
                continue
            row = view.rows[nav.cur] if view.rows and nav.cur < len(view.rows) else None
            n = len(view.rows)
            if key in NAV_KEYS:
                nav.move(NAV_KEYS[key], n, height)
            elif key == "pgdn":
                nav.move(height, n, height)
            elif key == "pgup":
                nav.move(-height, n, height)
            elif key in ("home", "g"):
                nav.home(n, height)
            elif key in ("end", "G"):
                nav.end(n, height)
            elif key in ("enter", "right", "l") and row and row.act:
                row.act()
            elif key in view.hotkeys:
                view.hotkeys[key][1](row)
            elif key == "?":
                self.help(view)
            elif key in ("left", "h", "esc", "q"):
                self.stack.pop()
            elif key == "Q":
                return

    def help(self, view: View) -> None:
        lines = ["↑ ↓  j k     move", "→ Enter  l   open / act", "← Esc q  h   back (q on the first screen quits)",
                 "PgUp PgDn    page", "g G          top / bottom", "Q            quit from anywhere", ""]
        lines += [f"{k:<12} {label}" for k, (label, _) in view.hotkeys.items()]
        self.message("Keys", lines)

    # ----- screens

    def v_main(self) -> View:
        rows = [
            Row("Overview         server, quota, start / stop", lambda: self.push(self.v_overview)),
            Row("Providers        search APIs you route to", lambda: self.push(self.v_providers)),
            Row("Accounts         API keys and their quota", lambda: self.push(self.v_accounts)),
            Row("Chains & routing fallback order, default route", lambda: self.push(self.v_chains)),
            Row("Keys & sign-in   recover or rotate keys", lambda: self.push(self.v_keys)),
            Row("Requests         recent traffic", lambda: self.push(self.v_requests)),
            Row("Logs             server log", lambda: self.push(self.v_logs)),
            Row("Quit", lambda: self.stack.clear()),
        ]
        return View("Snake Charmer terminal", rows, lines=[f"install: {self.home.root}", ""], refresh=3)

    # -- overview
    def v_overview(self) -> View:
        d = cli.status_data(self.home)
        rows: list[Row] = []
        lines = [f"home      {d['home']}"]
        if d["running"]:
            lines += [f"state     running (pid {d['pid']}, up {d['uptime']}, {d['memory']})",
                      f"url       {d['url']}   ui: {d['url']}/ui/", f"health    {d['health']}",
                      f"accounts  {d['accounts']}"]
        else:
            lines.append("state     stopped")
        lines += [f"log       {self.home.log}", ""]
        if d["running"]:
            rows += [Row("Stop", lambda: self.server("stop")), Row("Restart", lambda: self.server("restart")),
                     Row("Open Snake Charmer in the browser", self.open_browser),
                     Row("Run a health check", lambda: self.run_cli(
                         "Health check", lambda: cli.cmd_health(self.home, cli._health_ns())))]
        else:
            rows.append(Row("Start", lambda: self.server("start")))
        return View("Overview", rows, lines=lines, refresh=3)

    def server(self, what: str) -> None:
        ns = cli._ns(host=None, port=None, workers=None, wait=30)
        fn = {"start": lambda: cli.cmd_start(self.home, ns), "stop": lambda: cli.cmd_stop(self.home),
              "restart": lambda: cli.cmd_restart(self.home, ns)}[what]
        self.run_cli(what.capitalize(), fn)

    def open_browser(self) -> None:
        link = keys.signin_link(self.home)
        port = cli.read_port(self.home)
        url = link or (f"http://127.0.0.1:{port}/ui/" if port else None)
        if not url:
            self.message("Not running", "Start the server first.")
            return
        try:
            import webbrowser
            webbrowser.open(url)
            self.message("Opened", "Snake Charmer should be open in your browser, signed in.")
        except Exception as exc:
            self.message("Could not open a browser", str(exc))

    # -- providers
    def v_providers(self) -> View:
        from . import providers

        counts = {r[0]: r[1] for r in cli._provider_account_counts()}
        default = providers.get_default_route()
        rows = []
        for p in providers.list_providers():
            tag = "  [default]" if p.slug == default else ""
            off = "" if p.enabled else "  (disabled)"
            rows.append(Row(f"{p.slug:<14} {p.base_url:<42} {p.auth_style:<7} "
                            f"{counts.get(p.id, 0)} acct{tag}{off}",
                            data=p, act=None, style="" if p.enabled else "dim"))
        for r in rows:
            r.act = (lambda r=r: self.provider_menu(r.data))
        hot = {
            "a": ("add", lambda _r: self.add_provider()),
            "e": ("on/off", lambda r: r and self.toggle_provider(r.data)),
            "r": ("make default", lambda r: r and self.set_route(r.data.slug)),
            "d": ("delete", lambda r: r and self.delete_provider(r.data)),
        }
        lines = ["No provider yet - press a to add one." if not rows else
                 "A provider is one search API. /v1/* goes to the default route."]
        return View("Providers", rows, lines=lines, hotkeys=hot)

    def provider_menu(self, p) -> None:
        pick = self.choose(p.name, ["Make default route", "Disable" if p.enabled else "Enable", "Delete",
                                    "Cancel"], lines=[p.base_url, f"endpoint: /p/{p.slug}/"])
        if pick == 0:
            self.set_route(p.slug)
        elif pick == 1:
            self.toggle_provider(p)
        elif pick == 2:
            self.delete_provider(p)

    def add_provider(self) -> None:
        from . import providers

        names = list(providers.PRESETS)
        labels = [f"{providers.PRESETS[k]['name']:<14} {providers.PRESETS[k]['base_url']}" for k in names]
        pick = self.choose("Add provider - pick a preset", [*labels, "Custom URL…"])
        if pick is None:
            return
        if pick < len(names):
            preset = names[pick]
            slug = self.ask("short name", preset)
            if slug:
                self.guarded(lambda: providers.add_provider(slug, preset=preset), f"added {slug}")
            return
        slug = self.ask("short name (letters, digits, - _)")
        url = slug and self.ask("base URL (https://…)")
        if not url:
            return
        style = self.choose("How is the key sent?", ["header   (e.g. X-API-KEY: key)",
                                                     "query    (?api_key=key)", "bearer   (Authorization: Bearer key)"])
        if style is None:
            return
        auth = ("header", "query", "bearer")[style]
        extra = {}
        if auth == "header":
            extra["auth_header_name"] = self.ask("header name", "X-API-KEY") or "X-API-KEY"
        elif auth == "query":
            extra["auth_param_name"] = self.ask("query parameter", "api_key") or "api_key"
        self.guarded(lambda: providers.add_provider(slug, base_url=url, auth_style=auth, **extra),
                     f"added {slug}")

    def toggle_provider(self, p) -> None:
        from . import providers
        self.guarded(lambda: providers.update_provider(p.slug, enabled=not p.enabled))

    def delete_provider(self, p) -> None:
        from . import providers
        if self.confirm(f"Delete provider {p.slug}?", lines=["It must have no accounts and no chain."]):
            self.guarded(lambda: providers.delete_provider(p.slug), "deleted")

    def set_route(self, slug: str) -> None:
        from . import providers
        self.guarded(lambda: providers.set_default_route(slug), f"/v1/* now goes to {slug}")

    # -- accounts
    def v_accounts(self) -> View:
        from . import accounts, quota

        settings = cli.load_settings_for(self.home)
        rows_data = cli._account_rows(settings, None)
        hints = {a["id"]: a["key_hint"] for a in accounts.list_accounts()}
        provs = cli._providers_by_id()
        rows = []
        for a in rows_data:
            slug = provs[a["provider_id"]].slug if a.get("provider_id") in provs else "-"
            status = a["status"] + ("*" if a.get("on_cooldown") else "")
            style = "good" if a["status"] == "active" and not a.get("on_cooldown") else "bad"
            rows.append(Row(f"{a['id']:>3}  {a['label'][:16]:<16} {slug:<12} {status:<9} "
                            f"{a['used']:>5}/{a['quota_limit']:<5} {hints.get(a['id'], '****')}",
                            data=a, style=style))
        for r in rows:
            r.act = (lambda r=r: self.account_menu(r.data))
        period = quota.current_period(reset_day=settings.quota_reset_day)
        hot = {
            "a": ("add", lambda _r: self.add_account()),
            "e": ("on/off", lambda r: r and self.toggle_account(r.data)),
            "r": ("reset quota", lambda r: r and self.reset_account(r.data)),
            "v": ("reveal key", lambda r: r and self.reveal_account(r.data)),
            "d": ("delete", lambda r: r and self.delete_account(r.data)),
        }
        lines = [f"period {period}   " + f"{'#':>3}  {'label':<16} {'provider':<12} {'status':<9} {'used/limit':<11} key",
                 "" if rows else "No accounts yet - press a to add your first API key."]
        return View("Accounts", rows, lines=lines, hotkeys=hot, refresh=5)

    def account_menu(self, a: dict) -> None:
        on = a["status"] == "active"
        pick = self.choose(f"{a['label']} (#{a['id']})",
                           ["Disable" if on else "Enable", "Reset this month's usage", "Reveal key",
                            "Move to another provider", "Delete", "Cancel"])
        {0: lambda: self.toggle_account(a), 1: lambda: self.reset_account(a),
         2: lambda: self.reveal_account(a), 3: lambda: self.move_account(a),
         4: lambda: self.delete_account(a)}.get(pick, lambda: None)()

    def add_account(self) -> None:
        from . import accounts, providers

        provs = providers.list_providers()
        if not provs:
            self.message("No provider yet", "Add a provider first (Providers, then a).")
            return
        pick = 0 if len(provs) == 1 else self.choose("Which provider is this key for?",
                                                     [f"{p.slug}  {p.base_url}" for p in provs])
        if pick is None:
            return
        prov = provs[pick]
        existing = sum(1 for a in accounts.list_accounts() if a.get("provider_id") == prov.id)
        if existing and not self.confirm(
                f"{prov.slug} already has {existing} account(s)",
                lines=["Many providers forbid using several accounts to get around free-tier",
                       "limits and may suspend them. Check their terms (docs/responsible-use.md).",
                       "", "Add another anyway?"]):
            return
        label = self.ask("label (e.g. work-1)")
        if label is None:
            return
        key = self.ask("API key (hidden)", secret=True)
        if not key:
            return
        default = cli.load_settings_for(self.home).default_quota_limit
        limit = self.ask("credits per month", str(default))
        if limit is None:
            return
        self.guarded(lambda: accounts.add_account(
            key, label=label, provider_id=prov.id,
            quota_limit=int(limit) if limit.isdigit() else default), "account added")

    def toggle_account(self, a: dict) -> None:
        from . import accounts
        self.guarded(lambda: accounts.update_account(
            a["id"], status="disabled" if a["status"] == "active" else "active"))

    def reset_account(self, a: dict) -> None:
        from . import quota
        settings = cli.load_settings_for(self.home)
        period = quota.current_period(reset_day=settings.quota_reset_day)
        if self.confirm(f"Reset usage for {a['label']}?", lines=[f"Sets {period} back to 0 used."]):
            self.guarded(lambda: quota.reset_account(a["id"], period), "reset")

    def reveal_account(self, a: dict) -> None:
        self.reveal(f"{a['label']} (#{a['id']})",
                    next((x["key"] for x in keys.account_keys() if x["id"] == a["id"]), ""))

    def move_account(self, a: dict) -> None:
        from . import accounts, providers
        provs = providers.list_providers()
        pick = self.choose("Move to which provider?", [f"{p.slug}  {p.base_url}" for p in provs])
        if pick is not None:
            self.guarded(lambda: accounts.update_account(a["id"], provider_id=provs[pick].id), "moved")

    def delete_account(self, a: dict) -> None:
        from . import accounts
        if self.confirm(f"Delete {a['label']}?", lines=["The key is removed from the database."]):
            self.guarded(lambda: accounts.delete_account(a["id"]), "deleted")

    # -- chains and routing
    def v_chains(self) -> View:
        from . import providers

        default = providers.get_default_route()
        steps = providers.resolve(default) if providers.route_exists(default) else []
        rows = []
        for c in providers.list_chains():
            tag = "  [default]" if c["slug"] == default else ""
            rows.append(Row(f"{c['slug']:<14} {' -> '.join(c['steps']):<40} "
                            f"{'on' if c['enabled'] else 'off'}{tag}", data=c,
                            style="" if c["enabled"] else "dim"))
        for r in rows:
            r.act = (lambda r=r: self.chain_menu(r.data))
        where = " -> ".join(p.slug for p in steps) or ("nothing enabled" if providers.list_providers() else "no provider yet")
        lines = [f"/v1/* goes to: {default}  ({where})",
                 "A chain tries its providers in order and moves on when one is out of quota or failing.",
                 "" if rows else "No chains yet - press a to make one."]
        hot = {
            "a": ("add chain", lambda _r: self.add_chain()),
            "r": ("make default", lambda r: r and self.set_route(r.data["slug"])),
            "e": ("on/off", lambda r: r and self.toggle_chain(r.data)),
            "d": ("delete", lambda r: r and self.delete_chain(r.data)),
            "p": ("pick default…", lambda _r: self.pick_route()),
        }
        return View("Chains & routing", rows, lines=lines, hotkeys=hot)

    def chain_menu(self, c: dict) -> None:
        pick = self.choose(c["slug"], ["Make default route", "Disable" if c["enabled"] else "Enable",
                                       "Delete", "Cancel"], lines=[" -> ".join(c["steps"])])
        if pick == 0:
            self.set_route(c["slug"])
        elif pick == 1:
            self.toggle_chain(c)
        elif pick == 2:
            self.delete_chain(c)

    def pick_route(self) -> None:
        from . import providers
        slugs = [p.slug for p in providers.list_providers()] + [c["slug"] for c in providers.list_chains()]
        if not slugs:
            self.message("Nothing to route to", "Add a provider first.")
            return
        pick = self.choose("Send /v1/* to…", slugs)
        if pick is not None:
            self.set_route(slugs[pick])

    def add_chain(self) -> None:
        from . import providers
        provs = [p.slug for p in providers.list_providers()]
        if len(provs) < 2:
            self.message("Need two providers", "A chain falls back from one provider to the next,\n"
                                               "so add at least two providers first.")
            return
        slug = self.ask("chain name (e.g. web)")
        if not slug:
            return
        steps: list[str] = []
        while True:
            left = [p for p in provs if p not in steps]
            if not left:
                break
            opts = [*left, "Done"] if steps else left
            pick = self.choose("Then try…" if steps else "Try first…", opts,
                               lines=[("order so far: " + " -> ".join(steps)) if steps else "Pick providers in order."])
            if pick is None:
                return
            if opts[pick] == "Done":
                break
            steps.append(opts[pick])
        if steps:
            self.guarded(lambda: providers.add_chain(slug, steps), f"added chain {slug}")

    def toggle_chain(self, c: dict) -> None:
        from . import providers
        self.guarded(lambda: providers.update_chain(c["slug"], enabled=not c["enabled"]))

    def delete_chain(self, c: dict) -> None:
        from . import providers
        if self.confirm(f"Delete chain {c['slug']}?"):
            self.guarded(lambda: providers.delete_chain(c["slug"]), "deleted")

    # -- keys
    def v_keys(self) -> View:
        rows = []
        for role, key in keys.router_keys(self.home):
            rows.append(Row(f"router  {role:<8} {keys.mask(key)}", data=("router", role, key)))
        for a in keys.account_keys():
            rows.append(Row(f"account {a['label'][:14]:<14} {(a['provider'] or '-'):<10} {keys.mask(a['key'])}",
                            data=("account", a["label"], a["key"])))
        for r in rows:
            r.act = (lambda r=r: self.key_menu(r.data))
        top = [Row("Open Snake Charmer in the browser (signed in)", self.open_browser),
               Row("Copy the sign-in link", self.copy_link)]
        lines = [".env holds the router keys; the database holds your provider keys. Enter on a key",
                 "reveals, copies or (router keys) replaces it. Full values are never shown by default.", ""]
        return View("Keys & sign-in", top + rows, lines=lines)

    def key_menu(self, data: tuple) -> None:
        kind, name, key = data
        opts = ["Reveal on screen", "Copy to clipboard"] + (["Replace with a new key"] if kind == "router" else []) + ["Cancel"]
        pick = self.choose(f"{kind} key: {name}", opts)
        if pick == 0:
            self.reveal(f"{kind} key: {name}", key)
        elif pick == 1:
            tool = keys.copy_to_clipboard(key)
            self.message("Copied" if tool else "No clipboard tool found",
                         f"Copied with {tool}." if tool else "Install pbcopy, wl-copy or xclip, or use Reveal.")
        elif kind == "router" and pick == 2:
            self.rotate(name)

    def reveal(self, title: str, key: str) -> None:
        self.message(title, ["", key, "", "Keep it private. Closing this removes it from the screen."])

    def copy_link(self) -> None:
        link = keys.signin_link(self.home)
        if not link:
            self.message("No admin key", "There is no admin key in .env.")
            return
        tool = keys.copy_to_clipboard(link)
        if tool:
            self.message("Copied", "The sign-in link is in your clipboard. It contains the admin key.")
        else:
            self.reveal("Sign-in link", link)

    def rotate(self, role: str) -> None:
        if not self.confirm(f"Replace the {role} key?", lines=["Anything using the old key stops working.",
                                                              "The server needs a restart to pick it up."]):
            return
        new = keys.rotate_router_key(self.home, role)
        self.reveal(f"New {role} key (shown once)", new)
        if cli.is_running(self.home) and self.confirm("Restart now to apply it?"):
            self.server("restart")

    # -- traffic and logs
    def v_requests(self) -> View:
        from . import db

        found = db.connection().execute(
            "SELECT ts, method, path, status, account, provider_slug, latency_ms FROM request_log "
            "ORDER BY id DESC LIMIT 200").fetchall()
        rows = [Row(f"{r['ts'][11:19] if r['ts'] else '':<8} {r['method']:<5} {r['path'][:28]:<28} "
                    f"{r['status']:<4} {(r['provider_slug'] or '-')[:10]:<10} {(r['account'] or '-')[:12]:<12} "
                    f"{r['latency_ms']}ms", style="good" if 200 <= (r["status"] or 0) < 300 else "bad")
                for r in found]
        return View("Requests", rows, lines=["Newest first." if rows else "No requests yet."], refresh=3)

    def v_logs(self) -> View:
        lines = cli.tail_lines(self.home.log, 300) if self.home.log.exists() else []
        return View("Logs", [Row(ln) for ln in lines], lines=[str(self.home.log)], refresh=2, follow=True)


# ------------------------------------------------------------------ entry ----


def run(home: cli.Home) -> int:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise cli.CliError("the terminal UI needs an interactive terminal (try: serpent --help)")
    os.environ.setdefault("ESCDELAY", "25")  # make Esc respond at once
    locale.setlocale(locale.LC_ALL, "")

    def main(scr) -> None:
        try:
            App(scr, home).run()
        except QuitTui:
            pass

    try:
        curses.wrapper(main)
    except curses.error as exc:
        raise cli.CliError(f"the terminal could not start full-screen mode: {exc}") from exc
    return 0
