"""Right sidebar: transforms and dump trigger."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Checkbox


class ActionsPane(Vertical):
    """Transform checkboxes and dump trigger, collapsible via ``a``."""

    DEFAULT_CSS = """
    ActionsPane {
        width: 24; min-width: 20; height: 1fr;
        border: round $primary;
        padding: 0 1;
        overflow-y: auto;
    }
    ActionsPane.-hidden { display: none; }

    ActionsPane > Checkbox {
        height: 1;
        min-height: 1;
        border: none;
        padding: 0;
        margin-bottom: 1;
        background: transparent;
    }

    ActionsPane > Checkbox:focus {
        border: none;
        background: $boost;
        color: $text;
    }

    ActionsPane > Checkbox > .toggle--button {
        height: 1;
        min-height: 1;
        border: none;
        background: transparent;
        padding: 0;
        margin: 0 1 0 0;
        width: auto;
        min-width: 3;
    }

    ActionsPane > Checkbox > .toggle--label {
        height: 1;
        padding: 0;
        background: transparent;
    }

    ActionsPane > #dump-btn {
        dock: bottom;
        height: 3;
        margin-bottom: 1;
        border: none;
        background: $primary;
        color: $text;
        text-style: bold;
    }
    ActionsPane > #dump-btn:hover {
        background: $primary-darken-2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Checkbox("comments", id="remove-comments")
        yield Checkbox("docs", id="remove-docs")
        yield Checkbox("json", id="compact-json")
        yield Checkbox("whitespace", id="strip-whitespace")
        yield Button("DUMP", id="dump-btn")

    def set_hidden(self, hidden: bool) -> None:
        self.set_class(hidden, "-hidden")

    def is_hidden(self) -> bool:
        return self.has_class("-hidden")
