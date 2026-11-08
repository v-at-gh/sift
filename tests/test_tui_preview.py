from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult

from sift.core import SourceFile
from sift.tui.format import MAX_PREVIEW_SIZE
from sift.tui.widgets import PreviewPane


class _Host(App):
    def compose(self) -> ComposeResult:
        yield PreviewPane(id="pane")


def _sf(path: Path) -> SourceFile:
    return SourceFile(
        path=path,
        root=path.parent,
        relative_path=path.name,
        size=path.stat().st_size,
    )


async def test_load_small_file(tmp_path: Path) -> None:
    path = tmp_path / "a.py"
    path.write_text("print('hi')\n", encoding="utf-8")
    app = _Host()
    async with app.run_test() as pilot:
        pane = app.query_one(PreviewPane)
        pane.load(_sf(path))
        await pilot.pause()
        assert "print('hi')" in pane.text
        assert pane.target is not None


async def test_load_none_clears(tmp_path: Path) -> None:
    app = _Host()
    async with app.run_test() as pilot:
        pane = app.query_one(PreviewPane)
        pane.load(None)
        await pilot.pause()
        assert pane.text == ""
        assert pane.target is None


async def test_identity_skips_reload(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "a.py"
    path.write_text("x\n", encoding="utf-8")
    app = _Host()
    async with app.run_test() as pilot:
        pane = app.query_one(PreviewPane)
        sf = _sf(path)
        pane.load(sf)
        await pilot.pause()
        calls: list[Path] = []
        original = Path.read_text

        def counting_read(self, *a, **kw):
            calls.append(self)
            return original(self, *a, **kw)

        monkeypatch.setattr(Path, "read_text", counting_read)
        pane.load(sf)  # same instance — must not re-read
        await pilot.pause()
        assert calls == []


async def test_load_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "gone.py"
    app = _Host()
    async with app.run_test() as pilot:
        pane = app.query_one(PreviewPane)
        sf = SourceFile(
            path=path,
            root=tmp_path,
            relative_path="gone.py",
            size=10,
        )
        pane.load(sf)
        await pilot.pause()
        assert "Cannot read" in pane.text


async def test_large_file_disabled(tmp_path: Path) -> None:
    path = tmp_path / "big.txt"
    path.write_bytes(b"x" * (MAX_PREVIEW_SIZE + 1))
    app = _Host()
    async with app.run_test() as pilot:
        pane = app.query_one(PreviewPane)
        pane.load(_sf(path))
        await pilot.pause()
        assert "Preview disabled" in pane.text


async def test_toggle_soft_wrap(tmp_path: Path) -> None:
    path = tmp_path / "a.py"
    path.write_text("x = 1\n", encoding="utf-8")
    app = _Host()
    async with app.run_test() as pilot:
        pane = app.query_one(PreviewPane)
        pane.load(_sf(path))
        await pilot.pause()
        assert pane.soft_wrap is False
        pane.toggle_soft_wrap()
        await pilot.pause()
        assert pane.soft_wrap is True
        pane.toggle_soft_wrap()
        await pilot.pause()
        assert pane.soft_wrap is False


async def test_soft_wrap_persists_across_load(tmp_path: Path) -> None:
    path_a = tmp_path / "a.py"
    path_a.write_text("x\n", encoding="utf-8")
    path_b = tmp_path / "b.py"
    path_b.write_text("y\n", encoding="utf-8")
    app = _Host()
    async with app.run_test() as pilot:
        pane = app.query_one(PreviewPane)
        pane.toggle_soft_wrap()
        pane.load(_sf(path_a))
        await pilot.pause()
        assert pane.soft_wrap is True
        pane.load(_sf(path_b))
        await pilot.pause()
        assert pane.soft_wrap is True


async def test_binary_file_shows_marker(tmp_path: Path) -> None:
    path = tmp_path / "img.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 100)
    app = _Host()
    async with app.run_test() as pilot:
        pane = app.query_one(PreviewPane)
        pane.load(_sf(path))
        await pilot.pause()
        assert "Binary file" in pane.text


async def test_empty_file_shows_empty(tmp_path: Path) -> None:
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")
    app = _Host()
    async with app.run_test() as pilot:
        pane = app.query_one(PreviewPane)
        pane.load(_sf(path))
        await pilot.pause()
        assert pane.text == ""
        assert pane.target is not None


async def test_binary_takes_precedence_over_size(tmp_path: Path) -> None:
    """Large binary reports 'Binary', not 'too large' — size is irrelevant if not text."""
    path = tmp_path / "big.db"
    path.write_bytes(b"\x00" * (MAX_PREVIEW_SIZE + 1))
    app = _Host()
    async with app.run_test() as pilot:
        pane = app.query_one(PreviewPane)
        pane.load(_sf(path))
        await pilot.pause()
        assert "Binary file" in pane.text
        assert "larger than" not in pane.text


async def test_large_text_shows_size_disabled(tmp_path: Path) -> None:
    """Large text file still reports 'too large' — binary check passes."""
    path = tmp_path / "big.txt"
    path.write_bytes(b"a" * (MAX_PREVIEW_SIZE + 1))
    app = _Host()
    async with app.run_test() as pilot:
        pane = app.query_one(PreviewPane)
        pane.load(_sf(path))
        await pilot.pause()
        assert "Preview disabled" in pane.text
        assert "Binary file" not in pane.text
