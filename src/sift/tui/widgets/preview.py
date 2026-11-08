"""Read-only file preview with vim/emacs scroll bindings."""

from __future__ import annotations

from textual.widgets import TextArea

from ...core import SourceFile, is_binary
from ..format import MAX_PREVIEW_SIZE, format_size


class PreviewPane(TextArea):
    """Content of the currently highlighted file; owns its own target.

    ``load()`` skips redundant reads when called with the same SourceFile
    instance — important because ``CellHighlighted`` fires on every cursor
    move and reading a 500 KB file per keystroke would stall the UI.
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(
            "",
            id=id,
            read_only=True,
            show_line_numbers=True,
            soft_wrap=False,
        )
        self._target: SourceFile | None = None

    @property
    def target(self) -> SourceFile | None:
        return self._target

    def load(self, source_file: SourceFile | None) -> None:
        if source_file is self._target:
            return
        self._target = source_file
        self._apply()

    def _apply(self) -> None:
        f = self._target
        if f is None:
            self.load_text("")
            return
        if is_binary(f.path):
            self.load_text(f"[Binary file: {format_size(f.size, False).strip()}]")
            return
        if f.size > MAX_PREVIEW_SIZE:
            self.load_text(
                f"[Preview disabled: file is {format_size(f.size, False).strip()}, "
                f"larger than {format_size(MAX_PREVIEW_SIZE, False).strip()}]"
            )
            return
        try:
            text = f.path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.load_text(f"[Cannot read {f.path}: {exc}]")
            return
        self.load_text(text)

    def toggle_soft_wrap(self) -> None:
        """Flip line wrapping on/off. State persists across ``load()`` calls."""
        self.soft_wrap = not self.soft_wrap

    def on_key(self, event) -> None:
        """Scroll bindings; only active while the preview pane has focus."""
        key = event.key
        if key in ("j", "ctrl+n"):
            self.scroll_down(animate=False)
            event.prevent_default()
        elif key in ("k", "ctrl+p"):
            self.scroll_up(animate=False)
            event.prevent_default()
        elif key == "ctrl+f":
            self.scroll_page_down(animate=False)
            event.prevent_default()
        elif key == "ctrl+b":
            self.scroll_page_up(animate=False)
            event.prevent_default()
        elif key == "g":
            self.scroll_home(animate=False)
            event.prevent_default()
        elif key == "G":
            self.scroll_end(animate=False)
            event.prevent_default()
        elif key == "h":
            self.scroll_left(animate=False)
            event.prevent_default()
        elif key == "l":
            self.scroll_right(animate=False)
            event.prevent_default()
