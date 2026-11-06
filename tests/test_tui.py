"""Terminal UI: list navigation, key mapping, and a real run inside a pseudo-terminal."""

from __future__ import annotations

import curses
import os
import sys
import time

import pytest

from serpent import tui


def test_nav_moves_and_scrolls():
    nav = tui.Nav()
    for _ in range(12):
        nav.move(1, 20, 5)
    assert nav.cur == 12 and nav.top == 8  # window follows the cursor
    nav.move(-100, 20, 5)
    assert nav.cur == 0 and nav.top == 0
    nav.end(20, 5)
    assert nav.cur == 19 and nav.top == 15
    nav.home(20, 5)
    assert (nav.cur, nav.top) == (0, 0)


def test_nav_handles_empty_and_short_lists():
    nav = tui.Nav()
    nav.move(5, 0, 5)
    assert nav.cur == 0
    nav.move(5, 3, 10)
    assert nav.cur == 2 and nav.top == 0


def test_key_mapping():
    assert tui.read_key(curses.KEY_UP) == "up" and tui.read_key(10) == "enter"
    assert tui.read_key(27) == "esc" and tui.read_key(ord("j")) == "j" and tui.read_key(1000) == ""


def test_tab_keys_and_mouse_are_mapped():
    assert tui.read_key(9) == "tab" and tui.read_key(curses.KEY_BTAB) == "btab"
    assert tui.read_key(16) == "ctrl-p" and tui.read_key(curses.KEY_MOUSE) == "mouse"


def test_step_skips_group_titles():
    rows = [tui.Row("Group", style="head"), tui.Row("a"), tui.Row("b"), tui.Row("Group 2", style="head"),
            tui.Row("c")]
    nav = tui.Nav()
    tui.step(nav, 0, rows, 10)
    assert nav.cur == 1  # never rests on a title
    tui.step(nav, 1, rows, 10)
    tui.step(nav, 1, rows, 10)
    assert nav.cur == 4  # hopped over "Group 2"
    tui.step(nav, -1, rows, 10)
    tui.step(nav, -1, rows, 10)
    assert nav.cur == 1
    tui.step(nav, -1, rows, 10)
    assert nav.cur == 1  # stays on the first real row at the top


def test_fuzzy_matching_for_the_palette():
    assert tui.fuzzy("pa", "Provider: add") and tui.fuzzy("ACC", "Account: add")
    assert tui.fuzzy("", "anything") and not tui.fuzzy("zq", "Provider: add")


def test_gauge_and_sparkline():
    g = tui.glyphs(False)
    assert [style for _t, style in tui.bar(0.5, 10, g)] == ["good", "dim"]
    assert tui.bar(0.75, 10, g)[0][1] == "warn" and tui.bar(0.95, 10, g)[0][1] == "bad"
    assert len(tui.bar(1.0, 10, g)[0][0]) == 10 and tui.bar(2.0, 10, g)[1][0] == ""
    line = tui.spark([1, 5, 9], g)
    assert len(line) == 3 and line[0] != line[-1] and tui.spark([], g) == ""
    assert tui.human_size(2048) == "2.0 KB" and tui.human_size(10) == "10 B"


@pytest.fixture
def terminal(tmp_path):
    pyte = pytest.importorskip("pyte")
    if not sys.platform.startswith(("linux", "darwin")):
        pytest.skip("needs a POSIX pty")
    import fcntl
    import pty
    import select
    import struct
    import termios

    from serpent import cli

    home = tmp_path / "home"
    assert cli.main(["--home", str(home), "init"]) == 0
    screen = pyte.Screen(100, 28)
    stream = pyte.ByteStream(screen)
    pid, fd = pty.fork()
    if pid == 0:  # child: run the real command in the pty
        os.execvpe(sys.executable, [sys.executable, "-m", "serpent", "--home", str(home)],
                   {**os.environ, "TERM": "xterm-256color"})
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 28, 100, 0, 0))

    class T:
        def pump(self, seconds=0.6):
            end = time.time() + seconds
            while time.time() < end:
                ready, _, _ = select.select([fd], [], [], 0.1)
                if ready:
                    try:
                        data = os.read(fd, 65536)
                    except OSError:
                        return
                    if not data:
                        return
                    stream.feed(data)

        def send(self, *chunks, wait=0.5):
            codes = {"down": "\x1bOB", "up": "\x1bOA", "right": "\x1bOC", "left": "\x1bOD", "enter": "\r", "esc": "\x1b"}
            for c in chunks:
                os.write(fd, codes.get(c, c).encode())
                time.sleep(0.05)
            self.pump(wait)

        @property
        def text(self):
            return "\n".join(line.rstrip() for line in screen.display)

        def alive(self):
            try:
                return os.waitpid(pid, os.WNOHANG) == (0, 0)
            except ChildProcessError:
                return False

    t = T()
    t.pump(2.0)
    yield t
    try:
        os.kill(pid, 9)
        os.waitpid(pid, 0)
    except (OSError, ChildProcessError):
        pass


def test_tui_walks_through_screens_and_quits(terminal):
    text = terminal.text
    assert "SERPENT" in text and "Overview" in text and "Providers" in text and "Manage" in text
    assert "Credits" in text and "Traffic" in text  # the dashboard
    terminal.send("2")  # tabs: a number jumps straight there
    assert "No provider yet" in terminal.text
    terminal.send("a")
    assert "pick a preset" in terminal.text and "Serper" in terminal.text
    terminal.send("esc")  # closes the dialog, stays on the screen
    assert "No provider yet" in terminal.text
    terminal.send("left")  # arrows switch tabs too
    assert "Credits" in terminal.text
    terminal.send("q", wait=1.0)
    time.sleep(0.5)
    assert not terminal.alive()


def test_tui_adds_a_provider_and_an_account(terminal):
    terminal.send("2", "a", "enter", "enter", wait=1.0)  # Serper preset, default name
    assert "serper" in terminal.text and "[default]" in terminal.text
    terminal.send("3", "a")  # Accounts -> add
    terminal.send("work-1", "enter", "sk-typed-in-the-terminal-1234", "enter", "enter", wait=1.0)
    text = terminal.text
    assert "work-1" in text and "****1234" in text and "sk-typed-in" not in text


def test_tui_command_palette_runs_an_action(terminal):
    terminal.send(":")
    assert "Command palette" in terminal.text
    terminal.send("provider add", wait=0.6)
    assert "Provider: add" in terminal.text
    terminal.send("enter")
    assert "pick a preset" in terminal.text
    terminal.send("esc")


def test_tui_filter_narrows_the_list(terminal):
    terminal.send("8")  # Manage
    assert "Danger zone" in terminal.text and "Uninstall Serpent" in terminal.text
    terminal.send("/", "back up", wait=0.6)
    text = terminal.text
    assert "Back up the database" in text and "Uninstall Serpent" not in text
    terminal.send("esc")
    assert "Uninstall Serpent" in terminal.text


def test_tui_uninstall_shows_the_plan_and_changes_nothing_when_declined(terminal, tmp_path):
    home = tmp_path / "home"
    terminal.send("8")
    terminal.send("/", "uninstall", "enter", wait=0.6)
    terminal.send("enter", wait=0.8)  # the Uninstall row
    assert "Keep my data" in terminal.text and "Delete everything" in terminal.text
    terminal.send("enter", wait=0.8)  # keep my data
    text = terminal.text
    assert "This is what will happen" in text and "KEEP" in text
    terminal.send("enter", wait=0.6)  # default answer is No
    assert terminal.alive()
    assert (home / ".env").exists() and (home / "data").exists()  # nothing was touched
    terminal.send("esc")
    terminal.send("q", wait=1.0)


def test_tui_mouse_clicks_switch_tabs(terminal):
    def click(x, y):  # the classic X10 encoding that most terminfo entries use
        terminal.send(f"\x1b[M{chr(32)}{chr(32 + x)}{chr(32 + y)}", f"\x1b[M{chr(35)}{chr(32 + x)}{chr(32 + y)}")

    click(34, 2)  # on the "3 Accounts" tab label
    if "Accounts" not in terminal.text.splitlines()[0]:  # the header names the current screen
        pytest.skip("this curses build does not use X10 mouse reports")
    assert "No accounts yet" in terminal.text
    click(18, 2)  # "2 Providers"
    assert "No provider yet" in terminal.text
    terminal.send("m")  # mouse off, with a note
    assert "mouse off" in terminal.text
