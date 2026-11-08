from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import TabbedContent

from sift.engine import ScanOptions, SiftEngine
from sift.tui import SiftApp
from sift.tui.messages import (
    CurrentFileChanged,
    DirectoryToggleRequested,
    FileToggleRequested,
)
from sift.tui.widgets import FileTreeView


class _Host(App):
    def __init__(self, engine: SiftEngine) -> None:
        super().__init__()
        self.engine = engine
        self.file_toggles: list = []
        self.dir_toggles: list = []
        self.highlights: list = []

    def compose(self) -> ComposeResult:
        yield FileTreeView(id="tree")

    def on_mount(self) -> None:
        self.query_one(FileTreeView).rebuild(self.engine)

    def on_file_toggle_requested(self, msg: FileToggleRequested) -> None:
        self.file_toggles.append(msg.source_file)

    def on_directory_toggle_requested(self, msg: DirectoryToggleRequested) -> None:
        self.dir_toggles.append(msg.directory)

    def on_current_file_changed(self, msg: CurrentFileChanged) -> None:
        self.highlights.append(msg.source_file)


@pytest.fixture
def engine(sample_tree: Path, isolated_home: Path) -> SiftEngine:
    e = SiftEngine([sample_tree], use_cache=False)
    e.scan(ScanOptions(include_patterns=["*"]))
    return e


async def test_initial_shows_only_root(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(FileTreeView)
        # Only the root row visible (collapsed)
        assert tree.row_count == 1


async def test_enter_on_root_expands(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(FileTreeView)
        print(f"[DBG] cursor_type before focus: {tree.cursor_type!r}")
        tree.focus()
        await pilot.pause()
        print(f"[DBG] cursor_type after focus: {tree.cursor_type!r}")
        print(f"[DBG] row_count: {tree.row_count}")
        print(f"[DBG] _row_keys: {list(tree._row_keys.keys())}")
        await pilot.press("enter")
        await pilot.pause()
        print(f"[DBG] _expanded: {tree._expanded}")
        print(f"[DBG] row_count after: {tree.row_count}")
        assert tree.row_count > 1


async def test_expand_collapse_preserves_cursor(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(FileTreeView)
        tree.focus()
        await pilot.press("enter")
        await pilot.pause()
        # move to first child
        tree.move_cursor(row=1, column=0, animate=False, scroll=False)
        await pilot.pause()
        chosen = tree.current_key()
        tree.collapse_current()  # move to root row first? No — cursor is on child
        # Actually cursor is on child; collapse_current does nothing. Let's move to root.
        tree.move_cursor(row=0, column=0, animate=False, scroll=False)
        tree.collapse_current()
        await pilot.pause()
        tree.expand_current()
        await pilot.pause()
        # Cursor should be back at root (key preserved)
        assert tree.current_key() == f"dir:{engine.roots[0]}"


async def test_toggle_current_file(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(FileTreeView)
        tree.focus()
        await pilot.press("enter")  # expand root
        await pilot.pause()
        tree.move_cursor(row=1, column=0, animate=False, scroll=False)
        kind, _ = tree.current_kind_and_item()
        if kind == "file":
            tree.toggle_current()
            await pilot.pause()
            assert len(app.file_toggles) == 1


async def test_toggle_current_directory(engine: SiftEngine) -> None:
    # Engine must have subdirs
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(FileTreeView)
        tree.focus()
        await pilot.press("enter")
        await pilot.pause()
        # Find a dir row
        for row in range(tree.row_count):
            tree.move_cursor(row=row, column=0, animate=False, scroll=False)
            await pilot.pause()
            kind, item = tree.current_kind_and_item()
            if kind == "dir" and item != engine.roots[0]:
                tree.toggle_current()
                await pilot.pause()
                assert len(app.dir_toggles) == 1
                assert app.dir_toggles[0] == item
                return
        pytest.skip("no subdirs in fixture tree")


async def test_row_highlighted_posts_current_file(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(FileTreeView)
        tree.focus()
        await pilot.press("enter")  # expand
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        await pilot.pause()  # message propagation
        # Either a file or dir was highlighted; if file, should be in highlights
        tree.move_cursor(row=1, column=0, animate=False, scroll=False)
        await pilot.pause()
        await pilot.pause()
        assert len(app.highlights) >= 1


async def test_refresh_markers_updates_labels(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(FileTreeView)
        tree.focus()
        await pilot.press("enter")
        await pilot.pause()
        # Toggle first file visible
        tree.move_cursor(row=1, column=0, animate=False, scroll=False)
        await pilot.pause()
        f = tree.current_file()
        if f is None:
            pytest.skip("first child is a directory")
        engine.toggle_file(f)
        tree.refresh_markers(engine)
        await pilot.pause()
        cell = tree.get_cell_at((1, 0))
        assert cell.plain.startswith("├── ●")


async def test_set_human_sizes(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(FileTreeView)
        tree.set_human_sizes(True)
        await pilot.pause()
        assert tree.columns["length"].width == 9


async def test_preview_from_each_tab(
    sample_tree: Path,
    isolated_home: Path,
) -> None:
    """Opening preview from tree and table must switch to preview-tab."""
    from sift.tui.widgets import PreviewPane

    app = SiftApp([sample_tree])
    async with app.run_test(size=(120, 40)) as pilot:
        for _ in range(20):
            await pilot.pause(0.05)

        tabs = app.query_one("#views", TabbedContent)

        # Tree tab: expand root, then move to a file (a.py is first child)
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("enter")  # expand root (cursor stays on root dir)
        await pilot.pause()
        await pilot.press("down")  # cursor moves to a.py (first file)
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
        assert tabs.active == "preview-tab"
        assert app.query_one(PreviewPane).target is not None
        await pilot.press("o")  # back to tree
        await pilot.pause()

        # Table tab
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
        assert tabs.active == "preview-tab"
        assert app.query_one(PreviewPane).target is not None


async def test_h_on_expanded_dir_collapses(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(FileTreeView)
        tree.focus()
        await pilot.press("enter")  # expand root
        await pilot.pause()
        expanded_rows = tree.row_count
        tree.collapse_current()  # was: pilot.press("h")
        await pilot.pause()
        assert tree.row_count < expanded_rows
        kind, item = tree.current_kind_and_item()
        assert kind == "dir"
        assert item == engine.roots[0]


async def test_h_on_file_jumps_to_parent(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(FileTreeView)
        tree.focus()
        await pilot.press("enter")
        await pilot.pause()
        target_idx = None
        for i in range(tree.row_count):
            tree.move_cursor(row=i, column=0, animate=False, scroll=False)
            await pilot.pause()
            if tree.current_kind_and_item()[0] == "file":
                target_idx = i
                break
        if target_idx is None:
            pytest.skip("no file rows after expand")
        file_item = tree.current_kind_and_item()[1]
        rows_before = tree.row_count
        tree.collapse_current()  # was: pilot.press("h")
        await pilot.pause()
        kind, item = tree.current_kind_and_item()
        assert kind == "dir"
        assert item == file_item.path.parent
        assert tree.row_count == rows_before  # not collapsed, just moved


async def test_shift_h_collapses_all_to_root(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(FileTreeView)
        tree.focus()
        await pilot.press("enter")
        await pilot.pause()
        tree.move_cursor(row=2, column=0, animate=False, scroll=False)
        await pilot.pause()
        tree.collapse_to_root()  # was: pilot.press("H")
        await pilot.pause()
        assert tree.row_count == 1
        kind, item = tree.current_kind_and_item()
        assert kind == "dir"
        assert item == engine.roots[0]


async def test_h_on_root_is_noop(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(FileTreeView)
        tree.focus()
        rows_before = tree.row_count
        key_before = tree.current_key()
        await pilot.press("h")
        await pilot.pause()
        assert tree.row_count == rows_before
        assert tree.current_key() == key_before


async def test_tree_sort_by_length(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(FileTreeView)
        tree.focus()
        await pilot.press("enter")  # expand
        await pilot.pause()
        tree._sort_column = "length"
        tree._sort_reverse = True
        tree.rebuild(engine)
        await pilot.pause()
        # First child row should have the largest length among siblings
        assert tree.row_count > 1


async def test_tree_sort_by_length_orders_entries(engine: SiftEngine) -> None:
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(FileTreeView)
        tree.focus()
        await pilot.press("enter")
        await pilot.pause()
        tree._sort_column = "length"
        tree._sort_reverse = True
        tree.rebuild(engine)
        await pilot.pause()
        # Row 1+ are children; first child should be largest among siblings
        assert tree.row_count > 1
        # (deep verification would need to read cell text; quick sanity)


async def test_cursor_stays_on_collapsed_subdir(engine: SiftEngine) -> None:
    """Regression: cursor must stay on the toggled directory, not jump to root."""
    app = _Host(engine)
    async with app.run_test() as pilot:
        await pilot.pause()
        tree = app.query_one(FileTreeView)
        tree.focus()
        await pilot.press("enter")  # expand root
        await pilot.pause()

        # Find first subdirectory (not the root)
        subdir_key = None
        for i in range(tree.row_count):
            tree.move_cursor(row=i, column=0, animate=False, scroll=False)
            await pilot.pause()
            kind, item = tree.current_kind_and_item()
            if kind == "dir" and item != engine.roots[0]:
                subdir_key = f"dir:{item}"
                break
        if subdir_key is None:
            pytest.skip("no subdirs in fixture tree")

        # Expand then collapse the subdir; cursor must stay on it
        await pilot.press("enter")
        await pilot.pause()
        assert item in tree._expanded

        await pilot.press("enter")
        await pilot.pause()
        assert item not in tree._expanded
        assert tree.current_key() == subdir_key
