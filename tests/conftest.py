"""Shared fixtures: hermetic HOME/XDG and a deterministic sample tree."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect HOME/XDG and cwd so tests never touch the developer's files."""
    home = tmp_path / "home"
    config = home / ".config"
    cache = home / ".cache"
    home.mkdir()
    config.mkdir()
    cache.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    for name in ("SIFT_SCAN_PRESETS", "SIFT_CACHE_PATH", "SIFT_NO_CACHE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # no repo .sift.toml
    return home


@pytest.fixture
def sample_tree(tmp_path: Path) -> Path:
    """Small known tree: 3 .py in /, 1 .py in sub/, 1 .txt, 1 .py in ignored/."""
    root = tmp_path / "src"
    root.mkdir()
    (root / "a.py").write_text("print('a')\n", encoding="utf-8")
    (root / "b.py").write_text("print('b')\n", encoding="utf-8")
    (root / "notes.txt").write_text("hello\n", encoding="utf-8")
    sub = root / "sub"
    sub.mkdir()
    (sub / "c.py").write_text("print('c')\n", encoding="utf-8")
    ignored = root / "ignored"
    ignored.mkdir()
    (ignored / "d.py").write_text("print('d')\n", encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def _isolated_sift_logger():
    """Remove sift logger handlers after each test.

    LogPane registers a RotatingFileHandler at mount but does not remove it
    at unmount; without this fixture, handlers leak across test files (each
    test gets a fresh XDG_CACHE_HOME, so paths differ and the idempotence
    guard in LogPane._setup_logging doesn't fire).
    """
    logger = logging.getLogger("sift")
    yield
    for handler in list(logger.handlers):
        try:
            handler.close()
        except Exception:
            pass
        logger.removeHandler(handler)
