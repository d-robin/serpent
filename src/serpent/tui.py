"""``serpent tui``: a full-screen terminal interface for everything the CLI can do.

Layout: a header with the server state, a tab bar (``1``-``8``, ``Tab`` / ``Shift-Tab`` or
``←`` ``→``), the screen, and a bar of the keys that work right now.  Move with the arrow
keys or ``j`` / ``k``; ``Enter`` acts on the highlighted row; ``/`` filters the list as you
type; ``:`` (or ``Ctrl-P``) opens a command palette; ``?`` lists every key; the mouse works
too (click, wheel; ``m`` turns it off so you can select text).  Standard library only
(``curses``): macOS, Linux and the Raspberry Pi; not Windows.

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

MIN_W, MIN_H = 64, 16
ESC, ENTER_KEYS = 27, (10, 13, curses.KEY_ENTER)
BUTTON5 = getattr(curses, "BUTTON5_PRESSED", 0x200000)  # wheel down; absent from older curses

Seg = tuple[str, str]  # (text, style)


# ------------------------------------------------------------------ model ----


@dataclass
class Row:
    text: str
    act: Callable[[], None] | None = None  # Enter
    data: object = None  # what hotkeys receive
    style: str = ""  # "", dim, good, bad, warn, accent, head (a group title)
    segs: list[Seg] | None = None  # coloured pieces; text is still used for filtering

    @property
    def header(self) -> bool:
        return self.style == "head"


@dataclass
class View:
    title: str
    rows: list[Row]
    lines: list = field(default_factory=list)  # text above the list: str or list[Seg]
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


def step(nav: Nav, delta: int, rows: list[Row], height: int) -> None:
    """Move the cursor, hopping over group titles."""
    n = len(rows)
    nav.move(delta, n, height)
    direction = 1 if delta >= 0 else -1
    while rows and rows[nav.cur].header:
        before = nav.cur
        nav.move(direction, n, height)
        if nav.cur == before:  # hit an end: turn round
            direction = -direction
            nav.move(direction, n, height)
            break


def fuzzy(needle: str, text: str) -> bool:
    """True when every character of ``needle`` appears in ``text`` in order."""
    it = iter(text.lower())
    return all(ch in it for ch in needle.lower())


def read_key(code: int) -> str:
    """Map a curses key code to a command name."""
    table = {
        curses.KEY_UP: "up", curses.KEY_DOWN: "down", curses.KEY_LEFT: "left",
        curses.KEY_RIGHT: "right", curses.KEY_PPAGE: "pgup", curses.KEY_NPAGE: "pgdn",
        curses.KEY_HOME: "home", curses.KEY_END: "end", ESC: "esc", 9: "tab",
        curses.KEY_BTAB: "btab", 16: "ctrl-p", curses.KEY_MOUSE: "mouse",
        curses.KEY_BACKSPACE: "backspace", 127: "backspace", 8: "backspace",
    }
    if code in ENTER_KEYS:
        return "enter"
    if code in table:
        return table[code]
    if 32 <= code < 127:
        return chr(code)
    return ""


NAV_KEYS = {"up": -1, "k": -1, "down": 1, "j": 1}


# ------------------------------------------------------------------ theme ----

# name: (foreground, background) for 256-colour terminals; -1 is the terminal's own.
PALETTE_256 = {
    "base": (252, -1), "dim": (245, -1), "accent": (80, -1), "good": (78, -1), "bad": (203, -1),
    "warn": (221, -1), "title": (80, -1), "border": (240, -1),
    "sel": (16, 80), "head": (252, 236), "brand": (80, 236), "hgood": (78, 236), "hbad": (203, 236),
    "tabon": (16, 80), "taboff": (246, -1), "chip": (16, 246), "chipgood": (16, 78), "chipbad": (16, 203),
}
# The same names on an 8-colour terminal: (foreground, background).
PALETTE_8 = {
    "base": (-1, -1), "dim": (-1, -1), "accent": (6, -1), "good": (2, -1), "bad": (1, -1),
    "warn": (3, -1), "title": (6, -1), "border": (-1, -1),
    "sel": (0, 6), "head": (7, 0), "brand": (6, 0), "hgood": (2, 0), "hbad": (1, 0),
    "tabon": (0, 6), "taboff": (-1, -1), "chip": (0, 7), "chipgood": (0, 2), "chipbad": (0, 1),
}
BOLD = {"title", "brand", "tabon", "accent"}


def unicode_ok() -> bool:
    return (locale.getpreferredencoding(False) or "").lower().replace("-", "") in ("utf8", "utf")


def glyphs(uni: bool) -> dict[str, str]:
    if uni:
        return {"dot": "●", "ring": "○", "full": "█", "empty": "░", "tl": "╭", "tr": "╮", "bl": "╰",
                "br": "╯", "h": "─", "v": "│", "sep": "›", "bar": "▌", "thumb": "┃", "track": "│",
                "spark": "▁▂▃▄▅▆▇█", "brand": "◆"}
    return {"dot": "*", "ring": "o", "full": "#", "empty": "-", "tl": "+", "tr": "+", "bl": "+",
            "br": "+", "h": "-", "v": "|", "sep": ">", "bar": ">", "thumb": "#", "track": "|",
            "spark": "_.-~^", "brand": "*"}


def bar(frac: float, width: int, g: dict[str, str]) -> list[Seg]:
    """A coloured gauge: green, then amber from 70%, red from 90%."""
    frac = max(0.0, min(1.0, frac))
    filled = round(frac * width)
    style = "bad" if frac >= 0.9 else "warn" if frac >= 0.7 else "good"
    return [(g["full"] * filled, style), (g["empty"] * (width - filled), "dim")]


def spark(values: list[float], g: dict[str, str]) -> str:
    if not values:
        return ""
    lo, hi = min(values), max(values)
    chars = g["spark"]
    span = (hi - lo) or 1.0
    return "".join(chars[min(len(chars) - 1, int((v - lo) / span * (len(chars) - 1)))] for v in values)


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


# -------------------------------------------------------------------- app ----


class QuitTui(Exception):
    pass


class App:
    def __init__(self, scr, home: cli.Home) -> None:
        self.scr, self.home = scr, home
        self.g = glyphs(unicode_ok())
        self.styles: dict[str, int] = {}
        self.tabs: list[tuple[str, Callable[[], View]]] = [
            ("Overview", self.v_overview), ("Providers", self.v_providers),
            ("Accounts", self.v_accounts), ("Chains", self.v_chains), ("Keys", self.v_keys),
            ("Requests", self.v_requests), ("Logs", self.v_logs), ("Manage", self.v_manage),
        ]
        self.tab = 0
        self.navs = [Nav() for _ in self.tabs]
        self.flt = [""] * len(self.tabs)
        self.tabhits: list[tuple[int, int, int]] = []  # (x0, x1, tab) for the mouse
        self.listbox = (0, 0)  # first row of the list on screen, and its height
        self.mouse_on = True
        self.mouse: tuple[int, int, int] | None = None
        self.toasts: list[tuple[str, str, float]] = []
        self.repaint: Callable[[], None] | None = None  # redraws the screen under a popup

    # ----- terminal plumbing

    def setup(self) -> None:
        with contextlib.suppress(curses.error):
            curses.curs_set(0)
        self.scr.keypad(True)
        if curses.has_colors() and "NO_COLOR" not in os.environ:
            curses.start_color()
            with contextlib.suppress(curses.error):
                curses.use_default_colors()
            palette = PALETTE_256 if curses.COLORS >= 256 else PALETTE_8
            for i, (name, (fg, bg)) in enumerate(palette.items(), start=1):
                with contextlib.suppress(curses.error):
                    curses.init_pair(i, fg, bg)
                    self.styles[name] = curses.color_pair(i) | (curses.A_BOLD if name in BOLD else 0)
        self.set_mouse(True)

    def set_mouse(self, on: bool) -> None:
        self.mouse_on = on
        with contextlib.suppress(curses.error):
            curses.mousemask(curses.ALL_MOUSE_EVENTS if on else 0)

    def attr(self, style: str) -> int:
        if style in self.styles:
            return self.styles[style]
        if style == "dim":
            return curses.A_DIM
        if style in ("bold", "head", "accent", "title"):
            return curses.A_BOLD
        if style in ("sel", "tabon", "chip", "brand"):
            return curses.A_REVERSE
        return 0

    def put(self, y: int, x: int, text: str, style: str | int = "", width: int | None = None) -> None:
        h, w = self.scr.getmaxyx()
        if not 0 <= y < h or x < 0:
            return
        limit = (w - x) if width is None else min(width, w - x)
        if limit <= 0:
            return
        attr = style if isinstance(style, int) else self.attr(style)
        with contextlib.suppress(curses.error):
            self.scr.addnstr(y, x, text, limit, attr)

    def puts(self, y: int, x: int, segs: list[Seg], width: int | None = None) -> int:
        """Draw coloured pieces left to right; returns the x after the last one."""
        w = self.scr.getmaxyx()[1]
        end = w if width is None else min(w, x + width)
        for text, style in segs:
            if x >= end:
                break
            self.put(y, x, text, style, end - x)
            x += len(text)
        return x

    def fill(self, y: int, x: int, width: int, style: str = "base") -> None:
        self.put(y, x, " " * width, style, width)

    def status_pill(self) -> tuple[list[Seg], int]:
        if cli.is_running(self.home):
            text = f"running :{cli.read_port(self.home) or '?'}"
            segs = [(self.g["dot"] + " ", "hgood"), (text + " ", "head")]
        else:
            text = "stopped"
            segs = [(self.g["ring"] + " ", "hbad"), (text + " ", "head")]
        return segs, len(text) + 3

    # ----- drawing

    def toast(self, text: str, kind: str = "good", seconds: float = 2.5) -> None:
        self.toasts.append((text, kind, time.time() + seconds))

    def draw(self, view: View, rows: list[Row], nav: Nav, flt: str) -> int:
        """Draw one frame; returns the number of list rows that fit."""
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        g = self.g
        # header
        self.fill(0, 0, w, "head")
        self.puts(0, 0, [(f" {g['brand']} ", "brand"), ("SERPENT", "brand"),
                         (f"  {g['sep']}  ", "head"), (view.title, "head")])
        pill, plen = self.status_pill()
        self.puts(0, max(0, w - plen - 1), pill)
        # tabs
        x = 1
        self.tabhits = []
        for i, (name, _) in enumerate(self.tabs):
            label = f" {i + 1} {name} "
            if x + len(label) >= w:
                break
            self.put(1, x, label, "tabon" if i == self.tab else "taboff")
            self.tabhits.append((x, x + len(label), i))
            x += len(label) + 1
        self.put(2, 0, g["h"] * w, "border")
        y = 3
        for line in view.lines:
            if isinstance(line, str):
                self.put(y, 2, line, "dim")
            else:
                self.puts(y, 2, line)
            y += 1
        if flt:
            self.puts(y, 2, [("/ ", "accent"), (flt, "base"),
                             (f"   {sum(1 for r in rows if not r.header)} shown  (Esc clears)", "dim")])
            y += 1
        height = max(1, h - y - 2)
        self.listbox = (y, height)
        nav.clamp(len(rows), height)
        for i in range(height):
            idx = nav.top + i
            if idx >= len(rows):
                break
            row = rows[idx]
            if row.header:
                self.put(y + i, 2, row.text, "accent")
            elif idx == nav.cur:
                self.fill(y + i, 0, w - 1, "sel")
                flat = "".join(t for t, _ in row.segs) if row.segs else row.text
                self.put(y + i, 0, g["bar"] + " " + flat, "sel", w - 1)
            elif row.segs:
                self.put(y + i, 0, "  ")
                self.puts(y + i, 2, row.segs, w - 3)
            else:
                self.put(y + i, 2, row.text, row.style or "base", w - 3)
        if len(rows) > height:  # scrollbar
            thumb_h = max(1, height * height // len(rows))
            thumb_y = (height - thumb_h) * nav.top // max(1, len(rows) - height)
            for i in range(height):
                on = thumb_y <= i < thumb_y + thumb_h
                self.put(y + i, w - 1, g["thumb"] if on else g["track"], "accent" if on else "border")
        self.draw_toasts(h, w)
        self.draw_keybar(view, h, w)
        if h < MIN_H or w < MIN_W:
            self.put(h // 2, 1, f"terminal too small (need {MIN_W}x{MIN_H})", "warn")
        self.scr.refresh()
        return height

    def draw_toasts(self, h: int, w: int) -> None:
        now = time.time()
        self.toasts = [t for t in self.toasts if t[2] > now]
        row = h - 2
        for text, kind, _ in self.toasts[-1:]:
            label = f" {text} "
            self.put(row, max(0, w - len(label) - 2), label, "chipbad" if kind == "bad" else "chipgood")

    def draw_keybar(self, view: View, h: int, w: int) -> None:
        self.fill(h - 1, 0, w, "base")
        x = 1
        items = [(k, label) for k, (label, _) in view.hotkeys.items()]
        items += [("/", "filter"), (":", "commands"), ("?", "help"), ("q", "quit")]
        for key, label in items:
            need = len(key) + len(label) + 5
            if x + need > w:
                break
            self.put(h - 1, x, f" {key} ", "chip")
            self.put(h - 1, x + len(key) + 2, f" {label}", "dim")
            x += need

    def render(self) -> None:
        if self.repaint:
            self.repaint()

    def getkey(self, timeout: float = 0.0) -> str:
        self.scr.timeout(int(timeout * 1000) if timeout else -1)
        code = self.scr.getch()
        if code == curses.KEY_RESIZE:
            return "resize"
        if code == curses.KEY_MOUSE:
            try:
                _id, mx, my, _z, bstate = curses.getmouse()
            except curses.error:
                return ""
            self.mouse = (mx, my, bstate)
            return "mouse"
        return "" if code == -1 else read_key(code)

    # ----- dialogs

    def box(self, y0: int, x0: int, height: int, width: int, title: str, style: str = "accent") -> None:
        g = self.g
        for r in range(height):
            self.put(y0 + r, x0, " " * width, "base", width)
        self.put(y0, x0, g["tl"] + g["h"] * (width - 2) + g["tr"], style, width)
        self.put(y0 + height - 1, x0, g["bl"] + g["h"] * (width - 2) + g["br"], style, width)
        for r in range(1, height - 1):
            self.put(y0 + r, x0, g["v"], style)
            self.put(y0 + r, x0 + width - 1, g["v"], style)
        if title:
            self.put(y0, x0 + 2, f" {title} ", "title", width - 4)

    def popup(self, title: str, lines: list, *, options: list[str] | None = None,
              start: int = 0, style: str = "accent") -> int | None:
        """Boxed list or text; returns the chosen index, or None when dismissed."""
        sel, top = start, 0
        flat = [ln if isinstance(ln, str) else "".join(t for t, _ in ln) for ln in lines]
        while True:
            self.render()  # repaint the screen first, so nothing of an earlier popup shows
            h, w = self.scr.getmaxyx()
            width = min(w - 6, max(len(title) + 8, *(len(x) + 6 for x in flat + (options or [])), 36))
            body: list = list(lines) + ([""] if lines and options else []) + list(options or [])
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
            self.box(y0, x0, height, width, title, style)
            for r in range(inner):
                idx = top + r
                if idx >= len(body):
                    break
                item = body[idx]
                is_opt = bool(options) and idx >= len(body) - len(options)
                chosen = is_opt and idx - (len(body) - len(options)) == sel
                if chosen:
                    self.fill(y0 + 1 + r, x0 + 1, width - 2, "sel")
                    self.put(y0 + 1 + r, x0 + 2, f"{self.g['bar']} {item}", "sel", width - 4)
                elif isinstance(item, list):
                    self.puts(y0 + 1 + r, x0 + 3, item, width - 5)
                else:
                    self.put(y0 + 1 + r, x0 + 3, item, "base" if not is_opt else "base", width - 5)
            self.scr.refresh()
            key = self.getkey()
            if key in ("resize", "mouse", ""):
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
            elif key in ("up", "k"):
                top = max(0, top - 1)
            elif key in ("down", "j"):
                top = min(max(0, len(body) - inner), top + 1)
            elif key == "pgdn":
                top = min(max(0, len(body) - inner), top + inner)
            elif key == "pgup":
                top = max(0, top - inner)
            elif key in ("enter", "esc", "left", "h", "q", "right", "l", " "):
                return 0

    def choose(self, title: str, options: list[str], *, lines: list | None = None,
               start: int = 0) -> int | None:
        return self.popup(title, lines or [], options=options, start=start)

    def confirm(self, question: str, *, lines: list | None = None, danger: bool = False) -> bool:
        return self.popup(question, lines or [], options=["No", "Yes"],
                          style="bad" if danger else "accent") == 1

    def message(self, title: str, text: str | list, *, style: str = "accent") -> None:
        lines = text.splitlines() if isinstance(text, str) else list(text)
        self.popup(title, [*lines, "", "any key to close"], style=style)

    def ask(self, label: str, default: str = "", *, secret: bool = False) -> str | None:
        """One-line input in a small box. Esc cancels (None); Enter accepts."""
        buf = default
        self.scr.timeout(-1)
        with contextlib.suppress(curses.error):
            curses.curs_set(1)
        try:
            while True:
                self.render()
                h, w = self.scr.getmaxyx()
                width = min(w - 2, max(46, len(label) + 8))
                y0, x0 = max(0, h // 2 - 1), max(0, (w - width) // 2)
                self.box(y0, x0, 3, width, label)
                shown = "*" * len(buf) if secret else buf
                avail = max(1, width - 6)
                text = shown[-avail:]
                self.put(y0 + 1, x0 + 3, text, "base", width - 5)
                with contextlib.suppress(curses.error):
                    self.scr.move(y0 + 1, min(w - 1, x0 + 3 + len(text)))
                self.put(y0 + 3, x0 + 2, "Enter accept   Esc cancel", "dim")
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
            with contextlib.suppress(curses.error):
                curses.curs_set(0)

    def busy(self, text: str) -> None:
        h, w = self.scr.getmaxyx()
        label = f" {text} "
        self.put(h - 2, max(0, w - len(label) - 2), label, "chip")
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
            self.message(title if ok else f"{title} - failed", text or "done",
                         style="accent" if ok else "bad")
        return ok

    def guarded(self, fn: Callable[[], object], ok_msg: str | None = None) -> bool:
        """Call a library function; show the error text from the usual library errors."""
        try:
            fn()
        except (*cli._guard_errors(), ValueError) as exc:
            self.message("Not done", str(exc), style="bad")
            return False
        if ok_msg:
            self.toast(ok_msg)
        return True

    # ----- main loop

    def goto(self, tab: int) -> None:
        self.tab = tab % len(self.tabs)

    def run(self) -> None:
        self.setup()
        if not self.home.env_file.exists() and self.confirm(
                "No Serpent install here", lines=[str(self.home.root), "", "Create one now?"]):
            self.run_cli("Set up", lambda: cli.cmd_init(
                self.home, argparse.Namespace(force=False, json=False, from_up=True)))
        cli.boot(self.home)
        while True:
            _name, builder = self.tabs[self.tab]
            view = builder()
            nav, flt = self.navs[self.tab], self.flt[self.tab]
            needle = flt.lower()
            rows = [r for r in view.rows if not needle or (not r.header and needle in r.text.lower())]
            count = len(rows)
            if view.follow and (not nav.seen or nav.cur >= nav.last_count - 1):
                nav.cur = max(0, count - 1)  # stay on the newest line unless the user scrolled up
            nav.seen, nav.last_count = True, count
            height = self.draw(view, rows, nav, flt)
            self.repaint = lambda v=view, r=rows, n=nav, f=flt: self.draw(v, r, n, f)
            wait = view.refresh
            if self.toasts:
                soon = max(0.1, min(t[2] for t in self.toasts) - time.time())
                wait = min(wait, soon) if wait else soon
            key = self.getkey(wait)
            if not key or key == "resize":
                continue
            row = rows[nav.cur] if rows and nav.cur < count else None
            if key == "mouse":
                self.on_mouse(rows, nav, height)
                continue
            if key in NAV_KEYS:
                step(nav, NAV_KEYS[key], rows, height)
            elif key == "pgdn":
                step(nav, height, rows, height)
            elif key == "pgup":
                step(nav, -height, rows, height)
            elif key in ("home", "g"):
                nav.home(count, height)
                step(nav, 0, rows, height)
            elif key in ("end", "G"):
                nav.end(count, height)
                step(nav, 0, rows, height)
            elif key in ("enter", " ") and row and row.act:
                row.act()
            elif key in view.hotkeys:
                view.hotkeys[key][1](row)
            elif key.isdigit() and 1 <= int(key) <= len(self.tabs):
                self.goto(int(key) - 1)
            elif key in ("tab", "]", "right", "l"):
                self.goto(self.tab + 1)
            elif key in ("btab", "[", "left", "h"):
                self.goto(self.tab - 1)
            elif key == "/":
                self.edit_filter()
            elif key == "esc" and flt:
                self.flt[self.tab] = ""
                nav.home(count, height)
            elif key in (":", "ctrl-p"):
                self.palette()
            elif key == "?":
                self.help(view)
            elif key == "m":
                self.set_mouse(not self.mouse_on)
                self.toast("mouse on" if self.mouse_on else "mouse off: you can select text now")
            elif key in ("q", "Q"):
                return

    def on_mouse(self, rows: list[Row], nav: Nav, height: int) -> None:
        if not self.mouse:
            return
        mx, my, state = self.mouse
        if state & curses.BUTTON4_PRESSED:
            step(nav, -3, rows, height)
        elif state & BUTTON5:
            step(nav, 3, rows, height)
        elif state & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED | curses.BUTTON1_RELEASED):
            if my == 1:
                for x0, x1, i in self.tabhits:
                    if x0 <= mx < x1:
                        self.goto(i)
                return
            y0, h = self.listbox
            if y0 <= my < y0 + h:
                idx = nav.top + (my - y0)
                if idx < len(rows) and not rows[idx].header:
                    again = idx == nav.cur
                    nav.cur = idx
                    if again and rows[idx].act and state & curses.BUTTON1_CLICKED:
                        rows[idx].act()

    def edit_filter(self) -> None:
        """Type to narrow the list; the list updates on every key. Enter keeps it, Esc clears."""
        buf = self.flt[self.tab]
        while True:
            self.flt[self.tab] = buf
            self.navs[self.tab].home(0, 1)
            _name, builder = self.tabs[self.tab]
            view = builder()
            needle = buf.lower()
            rows = [r for r in view.rows if not needle or (not r.header and needle in r.text.lower())]
            self.draw(view, rows, self.navs[self.tab], buf)
            h, w = self.scr.getmaxyx()
            self.put(h - 1, 0, " " * w, "chip")
            self.put(h - 1, 1, f"/ {buf}", "chip", w - 2)
            self.scr.refresh()
            key = self.getkey()
            if key in ("enter",):
                return
            if key == "esc":
                self.flt[self.tab] = ""
                return
            if key == "backspace":
                buf = buf[:-1]
            elif len(key) == 1:
                buf += key

    # ----- command palette

    def commands(self) -> list[tuple[str, Callable[[], None]]]:
        cmds: list[tuple[str, Callable[[], None]]] = [
            (f"Go to {name}", lambda i=i: self.goto(i)) for i, (name, _) in enumerate(self.tabs)]
        cmds += [
            ("Server: start", lambda: self.server("start")), ("Server: stop", lambda: self.server("stop")),
            ("Server: restart", lambda: self.server("restart")),
            ("Open Snake Charmer in the browser", self.open_browser),
            ("Provider: add", self.add_provider), ("Account: add", self.add_account),
            ("Chain: add", self.add_chain), ("Route: choose the default", self.pick_route),
            ("Keys: copy the sign-in link", self.copy_link),
            ("Run doctor", self.m_doctor), ("Show the last fault", self.m_fault),
            ("Back up the database", self.m_backup), ("Settings: rotation and retries", self.m_tunables),
            ("Start at boot (systemd)", self.m_systemd), ("Copy or move this install", self.m_move),
            ("Uninstall Serpent…", self.m_uninstall), ("Quit", self.quit),
        ]
        return cmds

    def quit(self) -> None:
        raise QuitTui

    def palette(self) -> None:
        buf, sel = "", 0
        cmds = self.commands()
        while True:
            self.render()
            matches = [c for c in cmds if fuzzy(buf, c[0])]
            sel = max(0, min(sel, len(matches) - 1))
            h, w = self.scr.getmaxyx()
            width = min(w - 2, 58)
            shown = matches[:max(1, min(12, h - 8))]
            height = len(shown) + 4
            y0, x0 = max(0, (h - height) // 3), max(0, (w - width) // 2)
            self.box(y0, x0, height, width, "Command palette")
            self.puts(y0 + 1, x0 + 2, [(": ", "accent"), (buf, "base"), (self.g["bar"], "accent")], width - 4)
            self.put(y0 + 2, x0 + 1, self.g["h"] * (width - 2), "border")
            for i, (label, _fn) in enumerate(shown):
                if i == sel:
                    self.fill(y0 + 3 + i, x0 + 1, width - 2, "sel")
                    self.put(y0 + 3 + i, x0 + 2, f"{self.g['bar']} {label}", "sel", width - 4)
                else:
                    self.put(y0 + 3 + i, x0 + 4, label, "base", width - 6)
            if not matches:
                self.put(y0 + 3, x0 + 4, "no match", "dim")
            self.scr.refresh()
            key = self.getkey()
            if key in ("resize", "mouse", ""):
                continue
            if key == "esc":
                return
            if key == "enter":
                if matches:
                    matches[sel][1]()
                return
            if key == "up":
                sel = max(0, sel - 1)
            elif key == "down":
                sel = min(len(shown) - 1, sel + 1)
            elif key == "backspace":
                buf, sel = buf[:-1], 0
            elif len(key) == 1:
                buf, sel = buf + key, 0

    def help(self, view: View) -> None:
        lines = [
            [("Move", "accent")], "  ↑ ↓  j k        move        PgUp PgDn   page        g G   top / bottom",
            [("Screens", "accent")], "  1-8 or Tab      jump / next      Shift-Tab   previous      ← →   previous / next",
            [("Act", "accent")], "  Enter           act on the highlighted row (opens its menu)",
            "  /               filter the list as you type (Esc clears)",
            "  :  or Ctrl-P    command palette: start typing any action",
            "  m               mouse on/off (off lets you select text)",
            "  ?  q            this help / quit",
        ]
        if view.hotkeys:
            lines += [[("On this screen", "accent")]]
            lines += [f"  {k:<15} {label}" for k, (label, _) in view.hotkeys.items()]
        self.message("Keys", lines)

    # ----- screens

    def v_overview(self) -> View:
        from . import db

        g = self.g
        d = cli.status_data(self.home)
        settings = cli.load_settings_for(self.home)
        accts = cli._account_rows(settings, None)
        used = sum(a["used"] for a in accts)
        limit = sum(a["quota_limit"] for a in accts)
        usable = sum(1 for a in accts if a["status"] == "active" and not a.get("on_cooldown"))
        lines: list = [""]
        if d["running"]:
            lines.append([("  " + g["dot"] + " ", "good"), ("running   ", "good"),
                          (f"{d['url']}   pid {d['pid']} · up {d['uptime']} · {d['memory']}", "base")])
            lines.append([("    Snake Charmer  ", "dim"), (f"{d['url']}/ui/", "accent")])
        else:
            lines.append([("  " + g["ring"] + " ", "bad"), ("stopped", "bad"),
                          ("   press Enter on Start below", "dim")])
        lines.append("")
        if accts:
            frac = used / limit if limit else 0
            lines.append([("  Credits  ", "dim"), *bar(frac, 28, g),
                          (f"  {used:,} / {limit:,} used  ·  {usable} of {len(accts)} account(s) usable", "base")])
        else:
            lines.append([("  Credits  ", "dim"), ("no accounts yet: open Accounts (3) and press a", "warn")])
        try:
            recent = db.connection().execute(
                "SELECT status, latency_ms FROM request_log ORDER BY id DESC LIMIT 60").fetchall()
        except Exception:
            recent = []
        if recent:
            ok = sum(1 for r in recent if (r["status"] or 0) < 400)
            lat = [r["latency_ms"] or 0 for r in reversed(recent)]
            median = sorted(lat)[len(lat) // 2]
            lines.append([("  Traffic  ", "dim"), (spark(lat, g), "accent"),
                          (f"  last {len(recent)} calls: ", "base"), (f"{ok} ok", "good"),
                          (f" · {len(recent) - ok} failed" if len(recent) > ok else "", "bad"),
                          (f" · median {median:.0f} ms", "base")])
        else:
            lines.append([("  Traffic  ", "dim"), ("no calls yet", "dim")])
        lines += ["", [("  ", "base"), ("Actions", "accent")]]
        rows: list[Row] = []
        if d["running"]:
            rows += [Row("Stop the server", lambda: self.server("stop")),
                     Row("Restart", lambda: self.server("restart")),
                     Row("Open Snake Charmer in the browser", self.open_browser),
                     Row("Run a health check", self.m_health)]
        else:
            rows.append(Row("Start the server", lambda: self.server("start")))
        rows.append(Row("Command palette  (: )", self.palette))
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
            self.toast("Opened Snake Charmer in your browser")
        except Exception as exc:
            self.message("Could not open a browser", str(exc), style="bad")

    # -- providers
    def v_providers(self) -> View:
        from . import providers

        counts = {r[0]: r[1] for r in cli._provider_account_counts()}
        default = providers.get_default_route()
        rows = []
        for p in providers.list_providers():
            tag = "  [default]" if p.slug == default else ""
            off = "" if p.enabled else "  (disabled)"
            text = (f"{p.slug:<14} {p.base_url:<42} {p.auth_style:<7} {counts.get(p.id, 0)} acct{tag}{off}")
            segs = [(self.g["dot"] + " ", "good" if p.enabled else "dim"), (f"{p.slug:<14} ", "base"),
                    (f"{p.base_url:<42} ", "dim"), (f"{p.auth_style:<7} ", "dim"),
                    (f"{counts.get(p.id, 0)} acct", "base"), (tag, "accent"), (off, "warn")]
            rows.append(Row(text, data=p, segs=segs))
        for r in rows:
            r.act = (lambda r=r: self.provider_menu(r.data))
        hot = {
            "a": ("add", lambda _r: self.add_provider()),
            "e": ("on/off", lambda r: r and self.toggle_provider(r.data)),
            "r": ("make default", lambda r: r and self.set_route(r.data.slug)),
            "d": ("delete", lambda r: r and self.delete_provider(r.data)),
        }
        lines = [[("  No provider yet: press ", "warn"), ("a", "accent"), (" to add one.", "warn")] if not rows else
                 "  A provider is one search API. /v1/* goes to the default route.", ""]
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
        if self.confirm(f"Delete provider {p.slug}?", lines=["It must have no accounts and no chain."],
                        danger=True):
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
            healthy = a["status"] == "active" and not a.get("on_cooldown")
            status = a["status"] + ("*" if a.get("on_cooldown") else "")
            frac = a["used"] / a["quota_limit"] if a["quota_limit"] else 0
            text = (f"{a['id']:>3}  {a['label'][:16]:<16} {slug:<12} {status:<9} "
                    f"{a['used']:>5}/{a['quota_limit']:<5} {hints.get(a['id'], '****')}")
            segs = [(f"{a['id']:>3}  ", "dim"), (f"{a['label'][:16]:<16} ", "base"), (f"{slug:<12} ", "dim"),
                    (self.g["dot"] + " ", "good" if healthy else "bad"), (f"{status:<8} ", "base"),
                    *bar(frac, 14, self.g), (f" {a['used']:>5}/{a['quota_limit']:<5} ", "base"),
                    (hints.get(a["id"], "****"), "dim")]
            rows.append(Row(text, data=a, segs=segs))
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
        lines = [f"  period {period}     (* = cooling down)",
                 [] if rows else [("  No accounts yet: press ", "warn"), ("a", "accent"),
                                  (" to add your first API key.", "warn")]]
        return View("Accounts", rows, lines=[ln for ln in lines if ln != []], hotkeys=hot, refresh=5)

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
        if self.confirm(f"Delete {a['label']}?", lines=["The key is removed from the database."], danger=True):
            self.guarded(lambda: accounts.delete_account(a["id"]), "deleted")

    # -- chains and routing
    def v_chains(self) -> View:
        from . import providers

        default = providers.get_default_route()
        steps = providers.resolve(default) if providers.route_exists(default) else []
        rows = []
        for c in providers.list_chains():
            tag = "  [default]" if c["slug"] == default else ""
            text = f"{c['slug']:<14} {' -> '.join(c['steps']):<40} {'on' if c['enabled'] else 'off'}{tag}"
            segs = [(self.g["dot"] + " ", "good" if c["enabled"] else "dim"), (f"{c['slug']:<14} ", "base"),
                    (f"{' -> '.join(c['steps']):<40} ", "dim"), ("on" if c["enabled"] else "off", "base"),
                    (tag, "accent")]
            rows.append(Row(text, data=c, segs=segs))
        for r in rows:
            r.act = (lambda r=r: self.chain_menu(r.data))
        where = " -> ".join(p.slug for p in steps) or (
            "nothing enabled" if providers.list_providers() else "no provider yet")
        lines = [[("  /v1/* goes to: ", "dim"), (default, "accent"), (f"   ({where})", "dim")],
                 "  A chain sends each request to its providers in order, moving on when one is dry or failing.",
                 "  It sends the SAME request to every step: use providers with the same API shape.",
                 [] if rows else [("  No chains yet: press ", "warn"), ("a", "accent"), (" to make one.", "warn")]]
        hot = {
            "a": ("add chain", lambda _r: self.add_chain()),
            "r": ("make default", lambda r: r and self.set_route(r.data["slug"])),
            "e": ("on/off", lambda r: r and self.toggle_chain(r.data)),
            "d": ("delete", lambda r: r and self.delete_chain(r.data)),
            "p": ("pick default…", lambda _r: self.pick_route()),
        }
        return View("Chains & routing", rows, lines=[ln for ln in lines if ln != []], hotkeys=hot)

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
        if self.confirm(f"Delete chain {c['slug']}?", danger=True):
            self.guarded(lambda: providers.delete_chain(c["slug"]), "deleted")

    # -- keys
    def v_keys(self) -> View:
        rows = [Row("Open Snake Charmer in the browser (signed in)", self.open_browser),
                Row("Copy the sign-in link", self.copy_link),
                Row("Router keys: what apps and people use to call Serpent", style="head")]
        for role, key in keys.router_keys(self.home):
            r = Row(f"  {role:<8} {keys.mask(key)}", data=("router", role, key),
                    segs=[(f"  {role:<8} ", "base"), (keys.mask(key), "dim")])
            r.act = (lambda r=r: self.key_menu(r.data))
            rows.append(r)
        accts = keys.account_keys()
        if accts:
            rows.append(Row("Provider keys: used only by the server", style="head"))
        for a in accts:
            r = Row(f"  {a['label'][:14]:<14} {(a['provider'] or '-'):<10} {keys.mask(a['key'])}",
                    data=("account", a["label"], a["key"]),
                    segs=[(f"  {a['label'][:14]:<14} ", "base"), (f"{(a['provider'] or '-'):<10} ", "dim"),
                          (keys.mask(a["key"]), "dim")])
            r.act = (lambda r=r: self.key_menu(r.data))
            rows.append(r)
        lines = ["  .env holds the router keys; the database holds your provider keys.",
                 "  Enter on a key reveals, copies or (router keys) replaces it. Full values are never shown by default.", ""]
        return View("Keys & sign-in", rows, lines=lines)

    def key_menu(self, data: tuple) -> None:
        kind, name, key = data
        opts = ["Reveal on screen", "Copy to clipboard"] + (["Replace with a new key"] if kind == "router" else []) + ["Cancel"]
        pick = self.choose(f"{kind} key: {name}", opts)
        if pick == 0:
            self.reveal(f"{kind} key: {name}", key)
        elif pick == 1:
            tool = keys.copy_to_clipboard(key)
            if tool:
                self.toast(f"copied with {tool}")
            else:
                self.message("No clipboard tool found", "Install pbcopy, wl-copy or xclip, or use Reveal.")
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
            self.toast("sign-in link copied (it contains the admin key)")
        else:
            self.reveal("Sign-in link", link)

    def rotate(self, role: str) -> None:
        if not self.confirm(f"Replace the {role} key?", lines=["Anything using the old key stops working.",
                                                              "The server needs a restart to pick it up."],
                            danger=True):
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
            "ORDER BY id DESC LIMIT 300").fetchall()
        rows = []
        for r in found:
            status = r["status"] or 0
            style = "good" if status < 400 else "bad"
            text = (f"{r['ts'][11:19] if r['ts'] else '':<8} {r['method']:<5} {r['path'][:44]:<44} "
                    f"{status:<4} {(r['provider_slug'] or '-')[:10]:<10} {(r['account'] or '-')[:12]:<12} "
                    f"{r['latency_ms']}ms")
            segs = [(f"{r['ts'][11:19] if r['ts'] else '':<8} ", "dim"), (f"{r['method']:<5} ", "base"),
                    (f"{r['path'][:44]:<44} ", "base"), (f"{status:<4} ", style),
                    (f"{(r['provider_slug'] or '-')[:10]:<10} ", "dim"), (f"{(r['account'] or '-')[:12]:<12} ", "dim"),
                    (f"{r['latency_ms']}ms", "dim")]
            rows.append(Row(text, segs=segs))
        return View("Requests", rows, lines=["  Newest first. Press / to filter by path, provider or account." if rows
                                             else "  No requests yet."], refresh=3)

    def v_logs(self) -> View:
        lines = cli.tail_lines(self.home.log, 300) if self.home.log.exists() else []
        rows = []
        for ln in lines:
            style = "bad" if ("ERROR" in ln or "Traceback" in ln) else "warn" if "WARN" in ln.upper()[:60] else ""
            rows.append(Row(ln, style=style))
        return View("Logs", rows, lines=[f"  {self.home.log}"], refresh=2, follow=True)

    # -- manage
    def v_manage(self) -> View:
        running = cli.is_running(self.home)

        def head(text: str) -> Row:
            return Row(text, style="head")

        rows = [
            head("Diagnose"),
            Row("  Doctor: check the environment and the server", self.m_doctor),
            Row("  Last fault: what went wrong, with a hint", self.m_fault),
            Row("  Self-test on a scratch copy (about 10 seconds)", self.m_verify),
            Row("  Install details: folder, port, files and sizes", self.m_details),
            head("Settings"),
            Row("  Rotation, retries, cooldowns, timeouts…", self.m_tunables),
            head("Data"),
            Row("  Back up the database now", self.m_backup),
            Row("  Reset this month's usage for every account", self.m_reset_all),
            Row("  Clear the request history", self.m_clear_log),
            head("Deploy"),
            Row("  Start at boot on Linux (systemd unit)", self.m_systemd),
            Row("  Copy or move this install to a folder or another machine", self.m_move),
            head("About"),
            Row("  Version and where things are", self.m_about),
            head("Danger zone"),
            Row("  Uninstall Serpent…  (asks about your data first)", self.m_uninstall, style="bad"),
        ]
        lines = ["  Housekeeping, diagnostics and deployment. Nothing here runs without asking.",
                 "  The server is running." if running else "  The server is stopped.", ""]
        return View("Manage", rows, lines=lines, refresh=0)

    def m_health(self) -> None:
        self.run_cli("Health check", lambda: cli.cmd_health(self.home, cli._health_ns()))

    def m_doctor(self) -> None:
        self.run_cli("Doctor", lambda: cli.cmd_doctor(self.home, cli._health_ns()))

    def m_fault(self) -> None:
        self.run_cli("Last fault", lambda: cli.cmd_fault(self.home, cli._ns(all=False)))

    def m_verify(self) -> None:
        self.run_cli("Self-test", lambda: cli.cmd_verify(self.home, cli._ns(quiet=False)))

    def m_about(self) -> None:
        self.run_cli("About", lambda: cli.cmd_version(self.home, cli._ns(json=False)))

    def m_details(self) -> None:
        from . import uninstall

        d = cli.status_data(self.home)
        man = uninstall.read_manifest(self.home)
        lines = [f"folder    {self.home.root}", f"state     {'running' if d['running'] else 'stopped'}",
                 f"port      {d.get('port') or uninstall.remembered_port(self.home) or 'not chosen yet'}"
                 "   (this install keeps it)", f"installed {man.get('installed_at', 'unknown')}  v{man.get('version', '?')}",
                 "", "what is here:"]
        for item in uninstall.scan(self.home).items:
            if item.path is not None:
                lines.append(f"  {item.what:<48} {human_size(item.size):>9}")
                lines.append(f"    {item.where}")
        self.message("Install details", lines)

    def m_tunables(self) -> None:
        from . import tunables

        settings = cli.load_settings_for(self.home)
        while True:
            cur = tunables.current(settings)
            labels = {
                "strategy": "how to pick an account", "max_retries": "extra accounts to try on failure",
                "quota_reserve": "credits kept unspent per account", "default_quota_limit": "limit for new accounts",
                "cooldown_base_seconds": "first cooldown after a failure (s)",
                "cooldown_max_seconds": "longest cooldown (s)", "refund_on": "failures that refund the credit",
                "upstream_timeout": "provider timeout (s)",
            }
            keys_ = list(tunables.SPEC)
            opts = [f"{labels[k]:<38} {', '.join(cur[k]) if isinstance(cur[k], list) else cur[k]}" for k in keys_]
            pick = self.choose("Settings (saved in the database)", [*opts, "Done"],
                               lines=["Pick one to change it. Takes effect after a restart of the server."])
            if pick is None or pick == len(keys_):
                return
            name = keys_[pick]
            if name == "strategy":
                from .config import VALID_STRATEGIES
                s = self.choose("Rotation strategy", list(VALID_STRATEGIES),
                                start=list(VALID_STRATEGIES).index(cur[name]) if cur[name] in VALID_STRATEGIES else 0)
                value = None if s is None else VALID_STRATEGIES[s]
            else:
                cur_v = ",".join(cur[name]) if isinstance(cur[name], list) else str(cur[name])
                value = self.ask(labels[name], cur_v)
            if value is None or value == "":
                continue
            saved = self.guarded(lambda n=name, v=value: tunables.apply(settings, {n: v}), "saved")
            if saved and cli.is_running(self.home) and self.confirm("Restart the server to apply it now?"):
                self.server("restart")

    def m_backup(self) -> None:
        try:
            self.busy("backing up…")
            target = cli.backup_db(self.home)
        except Exception as exc:
            self.message("Backup failed", f"{type(exc).__name__}: {exc}", style="bad")
            return
        self.message("Backed up", [str(target), "", "It contains your provider keys: keep it as private as .env."])

    def m_reset_all(self) -> None:
        from . import quota
        settings = cli.load_settings_for(self.home)
        period = quota.current_period(reset_day=settings.quota_reset_day)
        if self.confirm("Reset usage for every account?", lines=[f"Sets {period} back to 0 used everywhere."],
                        danger=True):
            self.guarded(lambda: quota.reset_all(period), "all usage reset")

    def m_clear_log(self) -> None:
        from . import requestlog
        if self.confirm("Clear the request history?", lines=["Only the list of past calls; credits are unaffected."]):
            self.guarded(lambda: requestlog.clear(), "history cleared")

    def m_systemd(self) -> None:
        import getpass

        if not sys.platform.startswith("linux"):
            self.message("Linux only", ["systemd exists on Linux. On macOS run `./serpent up` after login",
                                        "(a launchd helper is not built yet)."])
            return
        unit = cli.systemd_unit(self.home, cli.base_port(self.home, None), "127.0.0.1", getpass.getuser())
        pick = self.choose("Start at boot (systemd)", ["Write the unit file here", "Show the unit", "Cancel"],
                           lines=["Serpent never runs sudo; it writes a file and shows the commands."])
        if pick == 1:
            self.message("serpent.service", unit.splitlines())
        elif pick == 0:
            out = self.home.root / "deploy" / "serpent.local.service"
            out.parent.mkdir(exist_ok=True)
            out.write_text(unit, encoding="utf-8")
            self.message("Written", [str(out), "", "Then, in a terminal:",
                                     f"  sudo cp {out} /etc/systemd/system/serpent.service",
                                     "  sudo systemctl daemon-reload && sudo systemctl enable --now serpent",
                                     "", "Stop the background copy first (Overview, Stop):",
                                     "both would want the port."])

    def m_move(self) -> None:
        dest = self.ask("destination: a folder, or user@host:/path")
        if not dest:
            return
        mode = self.choose("Copy or move?", ["Copy (keep this install)", "Move (remove this one afterwards)"])
        if mode is None:
            return
        data = self.confirm("Include your data (database with provider keys)?")
        env = self.confirm("Include .env (router keys and settings)?")
        ns = dict(dest=dest, move=mode == 1, copy=mode == 0, with_env=env, with_data=data,
                  no_verify=False, force=False, yes=True)
        self.run_cli("Plan (nothing changed yet)", lambda: cli.cmd_move(self.home, cli._ns(**ns, dry_run=True)))
        if self.confirm("Carry this out?", lines=[dest], danger=mode == 1):
            self.run_cli("Move" if mode else "Copy", lambda: cli.cmd_move(self.home, cli._ns(**ns, dry_run=False)))

    def m_uninstall(self) -> None:
        from . import uninstall

        inv = uninstall.scan(self.home)
        if not inv.items:
            self.message("Nothing to remove", f"Nothing from Serpent was found at {self.home.root}.")
            return
        has_data = any(i.category == "data" for i in inv.items)
        keep = True
        if has_data:
            data_size = sum(i.size for i in inv.items if i.category == "data")
            pick = self.choose(
                "Uninstall Serpent", ["Keep my data and settings (recommended)",
                                      f"Delete everything, including my data ({human_size(data_size)})", "Cancel"],
                lines=["Your data is the database (accounts, provider keys, request history),",
                       ".env (router keys) and any backups. Keeping it lets you redeploy later",
                       "(another folder, Docker, systemd) without entering anything again.",
                       "The source folder itself is never deleted."])
            if pick is None or pick == 2:
                return
            keep = pick == 0
        uninstall.apply_choice(inv, keep)
        plan: list = [f"Install at {self.home.root}", ""]
        for i in inv.items:
            style = {"remove": "bad", "stop": "warn", "keep": "good", "manual": "dim"}.get(i.action, "base")
            plan.append([(f"{i.action.upper():<7} ", style), (f"{i.what}", "base"),
                         (f"  {human_size(i.size)}" if i.size else "", "dim")])
            here = self.home.root.as_posix()
            plan.append([("        " + i.where.replace(here, "<this folder>"), "dim")])
            if i.note:
                plan.append([("        " + i.note.replace(here, "<this folder>"), "warn")])
        if not self.confirm("This is what will happen", lines=plan, danger=not keep):
            return
        if not keep:
            typed = self.ask("type 'delete' to erase your data and keys")
            if typed != "delete":
                self.toast("cancelled: nothing was changed", "bad")
                return
        self.busy("removing…")
        uninstall.execute(inv)
        problems = uninstall.verify(inv)
        result: list = []
        for i in inv.items:
            result.append([("OK   " if i.ok else "FAIL ", "good" if i.ok else "bad"), (f"{i.what}: ", "base"),
                           (i.result, "dim")])
        manual = [i for i in inv.items if i.action == uninstall.MANUAL]
        if manual:
            result += ["", "Still to do by hand:", *[f"  {i.what}: {i.note}" for i in manual]]
        if keep and has_data:
            result += ["", f"Your data is still in {self.home.root}.",
                       "Install Serpent again and run it there, or copy data/ and .env elsewhere."]
        else:
            result += ["", "The source folder was left alone; delete it yourself if you are done."]
        self.message("Uninstalled" if not problems else f"Finished with {problems} problem(s)", result,
                     style="accent" if not problems else "bad")
        raise QuitTui


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
