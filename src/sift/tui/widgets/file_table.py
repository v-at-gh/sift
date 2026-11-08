"""Paginated, sortable list of visible files."""

from __future__ import annotations

from textual.message import Message
from textual.widgets import DataTable

from ...core import SourceFile
from ...engine import SiftEngine
from ...filters import SelectionModel
from ..format import (
    file_marker,
    format_size,
    selection_style,
    styled_selection_row,
    format_datetime,
)
from ..messages import CurrentFileChanged, FileToggleRequested

MAX_TABLE_ROWS = 1000


class FileTableView(DataTable):
    """Sortable file list with pagination and cursor preservation.

    ``rebuild(engine)`` is the only full-rebuild path. Selection changes
    go through ``refresh_markers`` (in-place, no re-add). Unit switching
    goes through ``set_human_sizes`` (in-place, only the Length cells).
    """

    class SortChanged(Message):
        """Sort column or direction changed; rebuild is the app's job."""

        def __init__(self, column: str, reverse: bool) -> None:
            self.column = column
            self.reverse = reverse
            super().__init__()

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.cursor_type = "row"
        self.show_row_labels = False
        self._columns_created = False
        self._row_to_file: dict[str, SourceFile] = {}
        self._index_of: dict[str, int] = {}
        self._sort_column: str = "name"  # "name" | "size" | "mtime" | "ctime"
        self._sort_reverse: bool = False
        self._human_sizes: bool = False
        self._hidden_count: int = 0
        self._pending_cursor: tuple[int, int] | None = None

    # --- public API --------------------------------------------------

    @property
    def hidden_count(self) -> int:
        """Files beyond MAX_TABLE_ROWS not currently shown."""
        return self._hidden_count

    @property
    def sort_column(self) -> str:
        return self._sort_column

    @property
    def sort_reverse(self) -> bool:
        return self._sort_reverse

    def rebuild(self, engine: SiftEngine) -> None:
        """Rebuild rows from engine state; preserve cursor by identity."""
        prev_key = self._current_key()
        prev_row = self.cursor_row if self.row_count else 0
        prev_scroll = self.scroll_y

        length_width = 15 if not self._human_sizes else 9
        self.clear(columns=not self._columns_created)
        if not self._columns_created:
            self.add_column("Files", key="name")
            self.add_column("Length", key="length", width=length_width)
            self.add_column("Modified", key="mtime", width=17)
            self.add_column("Changed", key="ctime", width=17)
            self._columns_created = True
        else:
            try:
                self.columns["length"].width = length_width
            except Exception:
                pass

        self._row_to_file.clear()
        self._index_of.clear()

        visible = list(engine.visible_files())
        if self._sort_column == "length":
            key = lambda f: (f.size, str(f.root).casefold(), f.relative_path.casefold())
        elif self._sort_column == "mtime":
            key = lambda f: (
                f.mtime_ns,
                str(f.root).casefold(),
                f.relative_path.casefold(),
            )
        elif self._sort_column == "ctime":
            key = lambda f: (
                f.ctime_ns,
                str(f.root).casefold(),
                f.relative_path.casefold(),
            )
        else:
            key = lambda f: (str(f.root).casefold(), f.relative_path.casefold())
        visible.sort(key=key, reverse=self._sort_reverse)

        to_show = visible[:MAX_TABLE_ROWS]
        self._hidden_count = len(visible) - len(to_show)

        for idx, f in enumerate(to_show):
            selected = engine.selection.is_selected(f)
            row = styled_selection_row(
                file_marker(selected),
                f.relative_path,
                "bold" if selected else "dim",
            )
            self.add_row(
                row,
                format_size(f.size, self._human_sizes),
                format_datetime(f.mtime_ns),
                format_datetime(f.ctime_ns),
                key=f.identity,
            )
            self._row_to_file[f.identity] = f
            self._index_of[f.identity] = idx

        if self.row_count == 0:
            return

        if prev_key is not None and prev_key in self._index_of:
            target = self._index_of[prev_key]
        else:
            target = min(prev_row, self.row_count - 1)

        viewport_offset = max(0, prev_row - prev_scroll)
        self._pending_cursor = (target, viewport_offset)
        self.call_after_refresh(self._apply_cursor)

    def current_file(self) -> SourceFile | None:
        key = self._current_key()
        return self._row_to_file.get(key) if key else None

    def refresh_markers(self, selection: SelectionModel) -> None:
        for row_key, f in self._row_to_file.items():
            selected = selection.is_selected(f)
            row = styled_selection_row(
                file_marker(selected),
                f.relative_path,
                "bold" if selected else "dim",
            )
            self.update_cell(row_key, "name", row)

    def set_human_sizes(self, human: bool) -> None:
        """Reformat Length cells without touching row order or cursor."""
        if human == self._human_sizes:
            return
        self._human_sizes = human
        try:
            self.columns["length"].width = 15 if not human else 9
        except Exception:
            pass
        for row_key, f in self._row_to_file.items():
            self.update_cell(row_key, "length", format_size(f.size, human))

    def apply_sort(self, column: str) -> None:
        if column not in {"name", "length", "mtime", "ctime"}:
            return
        if column == self._sort_column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = column in {
                "length",
                "mtime",
                "ctime",
            }  # large/recent first
        self.post_message(self.SortChanged(self._sort_column, self._sort_reverse))

    # --- events -----------------------------------------------------

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table is not self:
            return
        f = self.current_file()
        if f is not None:
            self.post_message(FileToggleRequested(f))

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        if event.data_table is not self:
            return
        column_key = str(event.column_key.value) if event.column_key else ""
        self.apply_sort(column_key)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table is not self:
            return
        self.post_message(CurrentFileChanged(self.current_file()))

    # --- private ----------------------------------------------------

    def _current_key(self) -> str | None:
        if self.row_count == 0:
            return None
        try:
            rk, _ = self.coordinate_to_cell_key(self.cursor_coordinate)
        except Exception:
            return None
        return getattr(rk, "value", str(rk))

    def _apply_cursor(self) -> None:
        pending = self._pending_cursor
        self._pending_cursor = None
        if pending is None:
            return
        target, viewport_offset = pending
        if target >= self.row_count:
            target = max(0, self.row_count - 1)
        max_scroll = max(0, self.virtual_size.height - self.size.height)
        try:
            self.scroll_to(
                y=min(max(0, target - viewport_offset), max_scroll),
                animate=False,
            )
            self.move_cursor(row=target, column=0, animate=False, scroll=False)
        except Exception:
            pass
