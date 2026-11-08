from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable

from sift.engine import ScanOptions, SiftEngine
from sift.tui.messages import ExtensionToggleRequested
from sift.tui.widgets import ExtensionsPane

# --- widget integration ----------------------------------------------


class _Host(App):
    """Minimal host so messages can be captured at app level."""

    def __init__(self, engine: SiftEngine) -> None:
        super().__init__()
        self.engine = engine
        self.captured: list[ExtensionToggleRequested] = []

    def compose(self) -> ComposeResult:
        yield ExtensionsPane(id="pane")

    def on_mount(self) -> None:
        self.query_one(ExtensionsPane).rebuild(self.engine)

    def on_extension_toggle_requested(
        self,
        msg: ExtensionToggleRequested,
    ) -> None:
        self.captured.append(msg)


@pytest.fixture
def engine(sample_tree: Path, isolated_home: Path) -> SiftEngine:
    e = SiftEngine([sample_tree], use_cache=False)
    e.scan(ScanOptions(include_patterns=["*"]))
    return e


async def test_rebuild_populates_rows(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        pane = app.query_one(ExtensionsPane)
        table = pane.query_one(DataTable)
        # sample_tree has .py and .txt
        assert table.row_count >= 2
        assert pane.current_extension() is not None


async def test_toggle_current_posts_message(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        pane = app.query_one(ExtensionsPane)
        ext = pane.current_extension()
        assert ext is not None
        pane.toggle_current()
        await pilot.pause()
        assert len(app.captured) == 1
        assert app.captured[0].extension == ext


async def test_enter_on_row_posts_message(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        pane = app.query_one(ExtensionsPane)
        pane.query_one(DataTable).focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.captured) == 1


async def test_rebuild_preserves_cursor(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        pane = app.query_one(ExtensionsPane)
        table = pane.query_one(DataTable)
        # Move cursor to the last row, capture its extension
        last = table.row_count - 1
        table.move_cursor(row=last, column=0, animate=False, scroll=False)
        await pilot.pause()
        chosen = pane.current_extension()
        # Rebuild; cursor should stay on same extension
        pane.rebuild(engine)
        await pilot.pause()
        assert pane.current_extension() == chosen


async def test_hide_show(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        pane = app.query_one(ExtensionsPane)
        assert not pane.is_hidden()
        pane.set_hidden(True)
        await pilot.pause()
        assert pane.is_hidden()
        pane.set_hidden(False)
        await pilot.pause()
        assert not pane.is_hidden()
