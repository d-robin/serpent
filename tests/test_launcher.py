"""The ./serpent entry point: executable, valid shell, and usable before anything is installed."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(not sys.platform.startswith(("linux", "darwin")), reason="needs bash")


def test_launcher_is_executable_shell():
    launcher = ROOT / "serpent"
    assert os.access(launcher, os.X_OK)
    assert subprocess.run(["bash", "-n", str(launcher)]).returncode == 0


@pytest.fixture
def bare_tree(tmp_path):
    """A clone-like tree with no .venv."""
    shutil.copytree(ROOT / "src", tmp_path / "src", ignore=shutil.ignore_patterns("__pycache__", "ui_dist"))
    shutil.copy(ROOT / "serpent", tmp_path / "serpent")
    return tmp_path


def run(tree, *args):
    return subprocess.run([str(tree / "serpent"), *args], capture_output=True, text=True,
                          cwd=tree, env={**os.environ, "SERPENT_HOME": str(tree)}, timeout=60)


def test_help_and_version_work_with_nothing_installed(bare_tree):
    for args in (["--help"], ["help"], ["version"]):
        r = run(bare_tree, *args)
        assert r.returncode == 0, r.stderr
    assert "start here:" in run(bare_tree, "help").stdout
    assert not (bare_tree / ".venv").exists()  # asking for help must not install anything


def test_works_through_a_symlink_from_elsewhere(bare_tree, tmp_path_factory):
    link_dir = tmp_path_factory.mktemp("bin")
    (link_dir / "serpent").symlink_to(bare_tree / "serpent")
    r = subprocess.run([str(link_dir / "serpent"), "--help"], capture_output=True, text=True,
                       cwd="/", env={**os.environ, "SERPENT_HOME": str(bare_tree)}, timeout=60)
    assert r.returncode == 0 and "Serpent" in r.stdout


def test_uninstall_on_a_never_installed_tree_does_nothing(bare_tree):
    r = run(bare_tree, "uninstall", "--yes")
    assert r.returncode == 0 and "Nothing from Serpent" in r.stdout
