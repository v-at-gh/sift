"""Domain-level messages posted by TUI widgets.

Kept widget-agnostic so that SiftApp can register a single handler for each
domain action, regardless of which view (tree, table, extensions pane)
originated it.

Currently wired:
- ExtensionToggleRequested: posted by ExtensionsPane (tui/widgets/extensions.py).

Declared for upcoming extraction (see refactor steps 4-5):
- FileToggleRequested, DirectoryToggleRequested.
"""

from __future__ import annotations

from pathlib import Path

from textual.message import Message

from ..core import SourceFile


class FileToggleRequested(Message):
    def __init__(self, source_file: SourceFile) -> None:
        self.source_file = source_file
        super().__init__()


class DirectoryToggleRequested(Message):
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        super().__init__()


class ExtensionToggleRequested(Message):
    def __init__(self, extension: str) -> None:
        self.extension = extension
        super().__init__()

class CurrentFileChanged(Message):
    """The cursor moved to a new file (or off all files, ``None``).

    Posted by any view that highlights files — the preview pane follows.
    Views that also allow directory cursors post ``None`` when on a
    non-file row (directory, empty table).
    """
    def __init__(self, source_file: SourceFile | None) -> None:
        self.source_file = source_file
        super().__init__()
