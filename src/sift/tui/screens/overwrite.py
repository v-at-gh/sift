"""Modal confirmation for replacing an existing dump file."""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label


class OverwriteConfirmationScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("n", "cancel", "Cancel", show=False),
        Binding("y", "confirm", "Overwrite", show=False),
    ]
    CSS = """
    OverwriteConfirmationScreen {
        align: center middle;
        background: $background 65%;
    }
    #overwrite-dialog {
        width: 72; max-width: 90%; height: auto;
        border: round $warning; background: $surface; padding: 1 2;
    }
    #overwrite-question { height: auto; text-style: bold; }
    #overwrite-path { height: auto; margin-top: 1; text-wrap: wrap; }
    #overwrite-buttons { height: 3; margin-top: 1; align-horizontal: right; }
    #overwrite-buttons Button { margin-left: 1; }
    """

    def __init__(self, output_path: Path) -> None:
        super().__init__()
        self.output_path = output_path

    def compose(self) -> ComposeResult:
        with Vertical(id="overwrite-dialog"):
            yield Label(
                "Output file already exists. Replace it?", id="overwrite-question"
            )
            yield Label(str(self.output_path), id="overwrite-path")
            with Horizontal(id="overwrite-buttons"):
                yield Button("Overwrite", variant="error", id="overwrite-confirm")
                yield Button("Cancel", variant="primary", id="overwrite-cancel")

    def on_mount(self) -> None:
        # Explicit focus: ModalScreen does not always auto-focus, so y/n/escape
        # bindings silently fail without this.
        self.query_one("#overwrite-confirm", Button).focus()

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "overwrite-confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)


class DumpModalScreen(ModalScreen[Path | None]):
    """Asks for output path and confirms write."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    CSS = """
    DumpModalScreen { align: center middle; background: $background 65%; }
    #dump-dialog {
        width: 72; max-width: 90%; height: auto;
        border: round $primary; background: $surface; padding: 1 2;
    }
    #dump-dialog Label { margin-top: 1; }
    #dump-dialog Input { margin-bottom: 1; }
    #dump-buttons { align-horizontal: right; height: 3; }
    """

    def __init__(self, default_path: str) -> None:
        super().__init__()
        self.default_path = default_path

    def compose(self) -> ComposeResult:
        with Vertical(id="dump-dialog"):
            yield Label("Output file path:")
            yield Input(value=self.default_path, id="dump-path-input")
            with Horizontal(id="dump-buttons"):
                yield Button("Save", variant="primary", id="dump-save")
                yield Button("Cancel", id="dump-cancel")

    def on_mount(self) -> None:
        self.query_one("#dump-path-input", Input).focus()

    @on(Button.Pressed)
    def on_button(self, event: Button.Pressed) -> None:
        if event.button.id == "dump-save":
            self._submit()
        else:
            self.dismiss(None)

    @on(Input.Submitted)
    def on_submit(self, event: Input.Submitted) -> None:
        self._submit()

    def _submit(self) -> None:
        path = self.query_one("#dump-path-input", Input).value.strip()
        if path:
            self.dismiss(Path(path).expanduser().absolute())

    def action_cancel(self) -> None:
        self.dismiss(None)
