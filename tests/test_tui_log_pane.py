from __future__ import annotations

import logging
from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import TabbedContent, TabPane

from sift.tui.widgets import LogErrorCountChanged, LogPane


class _Host(App):
    def __init__(self) -> None:
        super().__init__()
        self.received: list[int] = []

    def compose(self) -> ComposeResult:
        with TabbedContent(initial="log-tab"):
            with TabPane("Log", id="log-tab"):
                yield LogPane(id="pane")

    def on_log_error_count_changed(self, msg: LogErrorCountChanged) -> None:
        self.received.append(msg.count)


async def test_log_appends_info_and_error(isolated_home: Path) -> None:
    app = _Host()
    async with app.run_test() as pilot:
        pane = app.query_one(LogPane)
        pane.log_message("hello", level="info")
        pane.log_message("oops", level="error")
        await pilot.pause()
        assert pane.error_count == 1


async def test_error_count_messages_incremental(isolated_home: Path) -> None:
    app = _Host()
    async with app.run_test() as pilot:
        pane = app.query_one(LogPane)
        pane.log_message("e1", level="error")
        pane.log_message("e2", level="error")
        pane.log_message("i1", level="info")
        await pilot.pause()
        assert app.received == [1, 2]


async def test_log_file_receives_entries(isolated_home: Path) -> None:
    app = _Host()
    async with app.run_test() as pilot:
        pane = app.query_one(LogPane)
        pane.log_message("persisted-entry", level="info")
        await pilot.pause()
        log_path = pane.log_file
        assert log_path is not None
        assert "persisted-entry" in log_path.read_text(encoding="utf-8")


async def test_no_duplicate_handlers_on_remount(isolated_home: Path) -> None:
    logger = logging.getLogger("sift")
    app1 = _Host()
    async with app1.run_test():
        pass
    app2 = _Host()
    async with app2.run_test():
        pass
    handlers_for_session = [
        h
        for h in logger.handlers
        if getattr(h, "baseFilename", "").endswith("session.log")
    ]
    assert len(handlers_for_session) <= 1
