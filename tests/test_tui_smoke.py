import pytest
from pathlib import Path
from textual.widgets import TabbedContent
from sift.tui import SiftApp
from sift.tui.widgets import PreviewPane


@pytest.mark.asyncio
async def test_app_starts_and_renders(sample_tree: Path, isolated_home: Path) -> None:
    app = SiftApp([sample_tree])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # after scan finishes
        for _ in range(20):
            await pilot.pause(0.05)
        # all tabs reachable without exception
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("j")  # cursor moves in table
        await pilot.pause()


async def test_app_renders_and_switches_tabs(
    sample_tree: Path, isolated_home: Path
) -> None:
    app = SiftApp([sample_tree])
    async with app.run_test(size=(120, 40)) as pilot:
        for _ in range(20):
            await pilot.pause(0.05)
        assert app.engine is not None
        for key in ("1", "2", "3", "4"):  # tree / table / preview / log
            await pilot.press(key)
            await pilot.pause(0.05)


async def test_preview_follows_cursor(sample_tree: Path, isolated_home: Path) -> None:
    from sift.tui.widgets import PreviewPane

    app = SiftApp([sample_tree])
    async with app.run_test(size=(120, 40)) as pilot:
        for _ in range(20):
            await pilot.pause(0.05)
        await pilot.press("2")  # table tab
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        await pilot.press("o")  # open preview
        await pilot.pause()
        preview = app.query_one(PreviewPane)
        assert preview.target is not None


async def test_preview_from_each_tab(
    sample_tree: Path,
    isolated_home: Path,
) -> None:
    """Opening preview from tree and table must not raise."""
    app = SiftApp([sample_tree])
    async with app.run_test(size=(120, 40)) as pilot:
        for _ in range(20):
            await pilot.pause(0.05)

        tabs = app.query_one("#views", TabbedContent)
        preview = app.query_one(PreviewPane)

        # From tree tab
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("enter")  # expand root
        await pilot.pause()
        await pilot.press("down")  # move to a child
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
        assert tabs.active == "preview-tab"
        # If child is a file, preview has content; if dir, target is None but no crash
        assert tabs.active == "preview-tab"

        # Back to tree, then table
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("2")
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
        assert tabs.active == "preview-tab"
        assert preview.target is not None  # cursor is on a file in table


async def test_tree_highlight_does_not_crash(
    sample_tree: Path,
    isolated_home: Path,
) -> None:
    """Cursor movement in tree fires RowHighlighted -> CurrentFileChanged."""
    app = SiftApp([sample_tree])
    async with app.run_test(size=(120, 40)) as pilot:
        for _ in range(20):
            await pilot.pause(0.05)
        await pilot.press("1")
        await pilot.pause()
        await pilot.press("enter")  # expand
        await pilot.pause()
        # Move down several times; each fires RowHighlighted
        for _ in range(3):
            await pilot.press("down")
            await pilot.pause()
        # No exception = pass. Preview may be on file or empty (dir).


async def test_tui_cli_include_filters_scan(
    sample_tree: Path,
    isolated_home: Path,
) -> None:
    """CLI --include narrows the scan itself, not just the visible set."""
    from sift.config import SiftConfig, apply_scan_cli_overrides
    from sift.tui.app import SiftApp

    cfg = SiftConfig()
    apply_scan_cli_overrides(cfg, include=["*.txt"], exclude=None, exclude_dirs=None)
    app = SiftApp([sample_tree], config=cfg)
    async with app.run_test(size=(120, 40)) as pilot:
        for _ in range(20):
            await pilot.pause(0.05)
        assert app.engine is not None
        assert all(f.extension == ".txt" for f in app.engine.files)
        assert len(app.engine.files) >= 1


async def test_w_toggles_preview_wrap_when_focused(
    sample_tree: Path,
    isolated_home: Path,
) -> None:
    from sift.tui.widgets import PreviewPane

    app = SiftApp([sample_tree])
    async with app.run_test(size=(120, 40)) as pilot:
        for _ in range(20):
            await pilot.pause(0.05)
        await pilot.press("1")  # tree
        await pilot.pause()
        await pilot.press("enter")  # expand
        await pilot.pause()
        await pilot.press("down")  # to a file
        await pilot.pause()
        await pilot.press("o")  # open preview
        await pilot.pause()
        preview = app.query_one(PreviewPane)
        assert preview.soft_wrap is False
        await pilot.press("w")
        await pilot.pause()
        assert preview.soft_wrap is True
        await pilot.press("w")
        await pilot.pause()
        assert preview.soft_wrap is False
