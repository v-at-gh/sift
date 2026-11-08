"""Left sidebar: extension → tri-state marker + visible-file counts."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Label

from ...engine import SiftEngine
from ..format import styled_extension_row
from ..messages import ExtensionToggleRequested

MIN_PANE_WIDTH = 20
MAX_PANE_WIDTH = 34
BORDER_AND_PADDING = 4


class ExtensionsPane(Vertical):
    """Extension groups with tri-state markers; posts toggle requests.

    Owns the underlying DataTable, its ``ext → row_key`` map, and the pane
    width (fit to the widest rendered label, clamped). Mutating the engine
    is delegated to the app via ``ExtensionToggleRequested``.
    """

    DEFAULT_CSS = """
    ExtensionsPane {
        width: 22; min-width: 18; height: 1fr;
        border: round $primary;
    }
    ExtensionsPane.-hidden { display: none; }
    ExtensionsPane > #extensions-title { height: 1; padding: 0 1; }
    ExtensionsPane > DataTable { height: 1fr; }
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._row_keys: dict[str, str] = {}
        self._columns_created = False

    def compose(self) -> ComposeResult:
        yield Label("Extensions", id="extensions-title")
        table = DataTable(id="extensions-table")
        table.cursor_type = "row"
        table.show_header = False
        table.show_row_labels = False
        yield table

    # --- public API ------------------------------------------------

    def rebuild(self, engine: SiftEngine) -> None:
        prev_ext = self.current_extension()
        table = self._table()
        if not self._columns_created:
            table.add_column("ext", key="ext")
            self._columns_created = True

        counts = _counts_by_ext(engine)
        table.clear(columns=False)
        self._row_keys.clear()
        index_of: dict[str, int] = {}
        widest = 0

        for i, ext in enumerate(engine.view.all_extensions):
            enabled = engine.view.is_extension_enabled(ext)
            total, selected = counts.get(ext, (0, 0))
            row, width = styled_extension_row(
                ext, enabled=enabled, total=total, selected=selected,
            )
            widest = max(widest, width)
            row_key = f"ext:{ext}"
            self._row_keys[ext] = row_key
            index_of[row_key] = i
            table.add_row(row, key=row_key)

        self.styles.width = max(
            MIN_PANE_WIDTH, min(MAX_PANE_WIDTH, widest + BORDER_AND_PADDING)
        )

        if prev_ext is not None and prev_ext in self._row_keys:
            table.move_cursor(
                row=index_of[self._row_keys[prev_ext]],
                column=0, animate=False, scroll=False,
            )

    # def rebuild(self, engine: SiftEngine) -> None:
    #     """Recreate rows from engine state; preserve cursor by extension."""
    #     prev_ext = self.current_extension()
    #     table = self._table()

    #     if not self._columns_created:
    #         table.add_column("ext", key="ext")
    #         self._columns_created = True

    #     counts = _counts_by_ext(engine)
    #     table.clear(columns=False)
    #     self._row_keys.clear()
    #     index_of: dict[str, int] = {}
    #     widest = 0

    #     for i, ext in enumerate(engine.view.all_extensions):
    #         enabled = engine.view.is_extension_enabled(ext)
    #         total, selected = counts.get(ext, (0, 0))
    #         label = extension_label(ext, enabled, total, selected)
    #         widest = max(widest, len(label))
    #         row_key = f"ext:{ext}"
    #         self._row_keys[ext] = row_key
    #         index_of[row_key] = i
    #         table.add_row(label, key=row_key)

    #     self.styles.width = max(
    #         MIN_PANE_WIDTH, min(MAX_PANE_WIDTH, widest + BORDER_AND_PADDING)
    #     )

    #     if prev_ext is not None and prev_ext in self._row_keys:
    #         table.move_cursor(
    #             row=index_of[self._row_keys[prev_ext]],
    #             column=0,
    #             animate=False,
    #             scroll=False,
    #         )

    def current_extension(self) -> str | None:
        key = self._current_row_key()
        return key[4:] if key and key.startswith("ext:") else None

    def toggle_current(self) -> None:
        """Post a toggle request for the current row (if any)."""
        ext = self.current_extension()
        if ext is not None:
            self.post_message(ExtensionToggleRequested(ext))

    def set_hidden(self, hidden: bool) -> None:
        self.set_class(hidden, "-hidden")

    def is_hidden(self) -> bool:
        return self.has_class("-hidden")

    # --- events ----------------------------------------------------

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table is not self._table():
            return
        key = getattr(event.row_key, "value", str(event.row_key))
        if key.startswith("ext:"):
            self.post_message(ExtensionToggleRequested(key[4:]))

    # --- private ---------------------------------------------------

    def _table(self) -> DataTable:
        return self.query_one(DataTable)

    def _current_row_key(self) -> str | None:
        table = self._table()
        if table.row_count == 0:
            return None
        try:
            rk, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:
            return None
        return getattr(rk, "value", str(rk))


def _counts_by_ext(engine: SiftEngine) -> dict[str, tuple[int, int]]:
    """(total_visible, selected_visible) per extension."""
    result: dict[str, tuple[int, int]] = {}
    for f in engine.visible_files():
        total, sel = result.get(f.extension, (0, 0))
        result[f.extension] = (
            total + 1,
            sel + (1 if engine.selection.is_selected(f) else 0),
        )
    return result
