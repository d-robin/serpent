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
    assert "Snake Charmer terminal" in terminal.text and "Providers" in terminal.text
    terminal.send("down", "enter")  # lynx-style: arrows then Enter
    assert "No provider yet" in terminal.text
    terminal.send("a")
    assert "pick a preset" in terminal.text and "Serper" in terminal.text
    terminal.send("esc")  # closes the dialog, stays on the screen
    assert "No provider yet" in terminal.text
    terminal.send("left")
    assert "Overview" in terminal.text  # back on the main menu
    terminal.send("q", wait=1.0)
    time.sleep(0.5)
    assert not terminal.alive()


def test_tui_adds_a_provider_and_an_account(terminal):
    terminal.send("down", "enter", "a", "enter", "enter", wait=1.0)  # Serper preset, default name
    assert "serper" in terminal.text and "[default]" in terminal.text
    terminal.send("left", "down", "enter", "a")  # Accounts -> add
    terminal.send("work-1", "enter", "sk-typed-in-the-terminal-1234", "enter", "enter", wait=1.0)
    text = terminal.text
    assert "work-1" in text and "****1234" in text and "sk-typed-in" not in text
