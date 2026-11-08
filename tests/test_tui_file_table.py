from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult

from sift.engine import ScanOptions, SiftEngine
from sift.tui.messages import CurrentFileChanged, FileToggleRequested
from sift.tui.widgets import FileTableView
from sift.tui.widgets.file_table import MAX_TABLE_ROWS


class _Host(App):
    def __init__(self, engine: SiftEngine) -> None:
        super().__init__()
        self.engine = engine
        self.toggles: list[SourceFile] = []
        self.highlights: list[SourceFile | None] = []

    def compose(self) -> ComposeResult:
        yield FileTableView(id="table")

    def on_mount(self) -> None:
        self.query_one(FileTableView).rebuild(self.engine)

    def on_file_toggle_requested(self, msg: FileToggleRequested) -> None:
        self.toggles.append(msg.source_file)

    def on_current_file_changed(self, msg: CurrentFileChanged) -> None:
        self.highlights.append(msg.source_file)


from sift.core import SourceFile  # noqa: E402


@pytest.fixture
def engine(sample_tree: Path, isolated_home: Path) -> SiftEngine:
    e = SiftEngine([sample_tree], use_cache=False)
    e.scan(ScanOptions(include_patterns=["*"]))
    return e


async def test_rebuild_populates_rows(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        table = app.query_one(FileTableView)
        assert table.row_count == len(engine.visible_files())


async def test_hidden_count(engine: SiftEngine, tmp_path: Path) -> None:
    # Build an engine with more than MAX_TABLE_ROWS files
    root = tmp_path / "big"
    root.mkdir()
    for i in range(MAX_TABLE_ROWS + 5):
        (root / f"f{i}.py").write_text("x", encoding="utf-8")
    big = SiftEngine([root], use_cache=False)
    big.scan(ScanOptions(include_patterns=["*.py"]))
    app = _Host(big)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(FileTableView)
        assert table.row_count == MAX_TABLE_ROWS
        assert table.hidden_count == 5


async def test_current_file(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(FileTableView)
        assert table.current_file() is not None


async def test_rebuild_preserves_cursor_by_identity(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(FileTableView)
        table.move_cursor(row=2, column=0, animate=False, scroll=False)
        await pilot.pause()
        chosen = table.current_file()
        table.rebuild(engine)
        await pilot.pause()
        assert table.current_file() == chosen


async def test_refresh_markers_does_not_rebuild(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(FileTableView)
        current = table.current_file()
        assert current is not None
        engine.toggle_file(current)
        table.refresh_markers(engine.selection)
        await pilot.pause()
        cell = table.get_cell_at((table.cursor_row, 0))
        assert cell.plain.startswith("●")


async def test_apply_sort_toggles_direction(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(FileTableView)
        assert table.sort_column == "name"
        assert table.sort_reverse is False
        table.apply_sort("name")
        assert table.sort_reverse is True
        table.apply_sort("length")
        assert table.sort_column == "length"
        assert table.sort_reverse is True
        table.apply_sort("length")
        assert table.sort_reverse is False


async def test_sort_changed_message_posted(engine: SiftEngine) -> None:
    captured: list[tuple[str, bool]] = []

    class _SortHost(App):
        def compose(self) -> ComposeResult:
            yield FileTableView(id="table")

        def on_mount(self) -> None:
            self.query_one(FileTableView).rebuild(engine)

        def on_file_table_view_sort_changed(
            self,
            msg: FileTableView.SortChanged,
        ) -> None:
            captured.append((msg.column, msg.reverse))

    app = _SortHost()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(FileTableView).apply_sort("length")
        await pilot.pause()
        assert captured == [("length", True)]


async def test_set_human_sizes_updates_cells(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(FileTableView)
        table.set_human_sizes(True)
        await pilot.pause()
        # exact format has "B" suffix; human mode leaves "KiB"/"B" too,
        # but width differs — assert the column width changed
        assert table.columns["length"].width == 9


async def test_row_selected_posts_toggle(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(FileTableView)
        table.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.toggles) == 1


async def test_highlight_posts_current_file(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(FileTableView)
        table.focus()
        await pilot.pause()
        print(len(app.highlights))
        await pilot.press("down")  # DataTable has built-in down handler
        await pilot.pause()
        await pilot.pause()  # second cycle for message propagation
        assert any(h is not None for h in app.highlights)


async def test_sort_by_mtime(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(FileTableView)
        table.apply_sort("mtime")
        await pilot.pause()
        # first row should have the largest mtime
        assert table.sort_column == "mtime"
        assert table.sort_reverse is True


async def test_sort_by_length_actually_sorts(engine: SiftEngine) -> None:
    """Regression: 'length' key must route to size sort, not fall through."""
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        table = app.query_one(FileTableView)
        table.apply_sort("length")
        await pilot.pause()
        table.rebuild(engine)
        await pilot.pause()
        # First visible file should be the largest
        sizes = [
            table._row_to_file[
                getattr(table.coordinate_to_cell_key((i, 0))[0], "value", "")
            ].size
            for i in range(table.row_count)
        ]
        assert sizes == sorted(sizes, reverse=True)
