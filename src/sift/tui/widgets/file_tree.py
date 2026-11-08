"""Flat DataTable rendering a hierarchical file tree.

Uses a DataTable instead of Textual's Tree widget so that the Length column
is a real column (per-row width, right-aligned) and so that row keys can be
stable — both are requirements of cursor preservation across rebuilds.
"""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import ContextManager

from rich.text import Text
from textual.binding import Binding
from textual.widgets import DataTable

from ...core import SourceFile
from ...engine import SiftEngine
from ..format import (
    file_marker,
    format_datetime,
    format_size,
    selection_marker,
    selection_style,
)
from ..messages import (
    CurrentFileChanged,
    DirectoryToggleRequested,
    FileToggleRequested,
)


def _tree_sort_key(engine: SiftEngine, column: str):
    """Compose a sort key closure for entries under a directory."""

    def key(entry: tuple[str, Path | SourceFile]) -> tuple:
        kind, item = entry
        if column == "length":
            primary = engine.dir_size(item) if kind == "dir" else item.size
        elif column == "mtime":
            primary = engine.dir_mtime(item) if kind == "dir" else item.mtime_ns
        else:
            return (0, _entry_name(kind, item))
        return (primary, _entry_name(kind, item))

    return key


def _entry_name(kind: str, item: Path | SourceFile) -> str:
    if kind == "dir":
        return item.name.casefold()
    return item.path.name.casefold()


class FileTreeView(DataTable):
    """Hierarchical file view with per-row Length column.

    Expansion state lives inside the widget (a set of directories), so
    (un)collapsing is a rebuild — which is cheap once ``_update_scope``
    batches row mutations into a single refresh.

    File/directory toggles are posted as domain messages; the widget
    never mutates the engine itself.
    """

    BINDINGS = [
        Binding("enter", "select_cursor", "Select", show=False),
    ]

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(
            id=id,
            cursor_type="row",
            show_row_labels=False,
        )
        self._columns_created = False
        self._expanded: set[Path] = set()
        self._columns_created = False
        self._expanded: set[Path] = set()
        self._row_keys: dict[str, tuple[str, Path | SourceFile]] = {}
        self._row_prefixes: dict[str, str] = {}
        self._row_sizes: dict[str, int] = {}
        self._human_sizes = False
        self._engine: SiftEngine | None = None
        self._pending_scroll: tuple[int, int] | None = None
        self._index_of: dict[str, int] = {}
        self._sort_column: str = "name"  # "name" | "length" | "mtime"
        self._sort_reverse: bool = False

    # --- public API --------------------------------------------------

    def rebuild(
        self,
        engine: SiftEngine,
        *,
        cursor_target_key: str | None = None,
    ) -> None:
        self._engine = engine
        prev_key = (
            cursor_target_key if cursor_target_key is not None else self._current_key()
        )
        prev_row = self.cursor_row if self.row_count else 0
        prev_scroll = self.scroll_y

        length_width = 15 if not self._human_sizes else 9
        # (key, Text label, prefix, size, mtime_ns, (kind, item))
        rows: list[tuple[str, Text, str, int, int, tuple[str, Path | SourceFile]]] = []

        def emit(prefix: str, d: Path, branch: str) -> None:
            key = f"dir:{d}"
            total, selected = engine.dir_counts(d)
            size = engine.dir_size(d)
            mtime = engine.dir_mtime(d)
            style = selection_style(selected, total)
            text = Text()
            text.append(f"{prefix}{branch}", style="dim")
            text.append(selection_marker(selected, total), style=style)
            text.append(f" {d.name or str(d)}/", style=style)
            rows.append((key, text, prefix + branch, size, mtime, ("dir", d)))

        def emit_file(prefix: str, f: SourceFile) -> None:
            key = f"file:{f.identity}"
            selected = engine.selection.is_selected(f)
            style = "bold" if selected else "dim"
            text = Text()
            text.append(prefix, style="dim")
            text.append(file_marker(selected), style=style)
            text.append(f" {f.path.name}", style=style)
            rows.append((key, text, prefix, f.size, f.mtime_ns, ("file", f)))

        def walk(directory: Path, prefix: str) -> None:
            subdirs, files = engine.children_of(directory)
            entries = [("dir", x) for x in subdirs] + [("file", x) for x in files]
            entries.sort(
                key=_tree_sort_key(engine, self._sort_column),
                reverse=self._sort_reverse,
            )
            for i, (kind, item) in enumerate(entries):
                is_last = i == len(entries) - 1
                branch = "└── " if is_last else "├── "
                if kind == "dir":
                    emit(prefix, item, branch)
                    if item in self._expanded:
                        walk(item, prefix + ("    " if is_last else "│   "))
                else:
                    emit_file(prefix + branch, item)

        for root in engine.roots:
            emit("", root, "")
            if root in self._expanded:
                walk(root, "")

        self._row_keys.clear()
        self._row_prefixes.clear()
        self._row_sizes.clear()

        with self._update_scope():
            self.clear(columns=not self._columns_created)
            if not self._columns_created:
                self.add_column("Files", key="name")
                self.add_column("Length", key="length", width=length_width)
                self.add_column("Modified", key="mtime", width=17)
                self._columns_created = True
            else:
                try:
                    self.columns["length"].width = length_width
                except Exception:
                    pass
            for key, label, prefix, size, mtime, kind_item in rows:
                self.add_row(
                    label,
                    format_size(size, self._human_sizes),
                    format_datetime(mtime),
                    key=key,
                )
                self._row_prefixes[key] = prefix
                self._row_sizes[key] = size
                self._row_keys[key] = kind_item

        if self.row_count == 0:
            return

        # Compute cursor target and viewport offset from pre-rebuild state.
        self._index_of = {rows[i][0]: i for i in range(len(rows))}
        if prev_key is not None and prev_key in self._index_of:
            target = self._index_of[prev_key]
        else:
            target = min(prev_row, max(0, len(rows) - 1))
        viewport_offset = max(0, prev_row - prev_scroll)

        with self._update_scope():
            self.clear(columns=not self._columns_created)
            if not self._columns_created:
                self.add_column("Files", key="name")
                self.add_column("Length", key="length", width=length_width)
                self.add_column("Modified", key="mtime", width=17)
                self._columns_created = True
            else:
                try:
                    self.columns["length"].width = length_width
                except Exception:
                    pass
            for key, label, prefix, size, mtime, kind_item in rows:
                self.add_row(
                    label,
                    format_size(size, self._human_sizes),
                    format_datetime(mtime),
                    key=key,
                )
                self._row_prefixes[key] = prefix
                self._row_sizes[key] = size
                self._row_keys[key] = kind_item

            # Restore cursor and scroll synchronously inside the batch so the
            # single render reflects the final state (no flicker to row 0).
            if self.row_count > 0:
                clamped = min(target, self.row_count - 1)
                try:
                    self.move_cursor(row=clamped, column=0, animate=False, scroll=False)
                except Exception:
                    pass
                try:
                    self.scroll_to(y=max(0, clamped - viewport_offset), animate=False)
                except Exception:
                    pass

        if self.row_count == 0:
            return

        # Safety net: if the synchronous scroll_to clamped against a stale
        # virtual_size, correct it after the layout pass.
        self._pending_scroll = (target, viewport_offset)
        self.call_after_refresh(self._apply_scroll)

    def refresh_markers(self, engine: SiftEngine) -> None:
        for key, (kind, item) in self._row_keys.items():
            prefix = self._row_prefixes.get(key, "")
            if kind == "file":
                selected = engine.selection.is_selected(item)
                text = Text()
                text.append(prefix, style="dim")
                text.append(file_marker(selected), style="bold" if selected else "dim")
                text.append(f" {item.path.name}", style="bold" if selected else "dim")
                self.update_cell(key, "name", text)
            else:
                total, selected = engine.dir_counts(item)
                style = selection_style(selected, total)
                text = Text()
                text.append(prefix, style="dim")
                text.append(selection_marker(selected, total), style=style)
                text.append(f" {item.name or str(item)}/", style=style)
                self.update_cell(key, "name", text)

    def set_human_sizes(self, human: bool) -> None:
        if human == self._human_sizes:
            return
        self._human_sizes = human
        try:
            self.columns["length"].width = 15 if not human else 9
        except Exception:
            pass
        for key, size in self._row_sizes.items():
            self.update_cell(key, "length", format_size(size, human))

    def current_key(self) -> str | None:
        return self._current_key()

    def current_kind_and_item(self) -> tuple[str | None, Path | SourceFile | None]:
        key = self._current_key()
        if not key:
            return None, None
        return self._row_keys.get(key, (None, None))

    def current_file(self) -> SourceFile | None:
        kind, item = self.current_kind_and_item()
        return item if kind == "file" else None

    def current_extension(self) -> str | None:
        f = self.current_file()
        return f.extension if f else None

    def toggle_current(self) -> None:
        """Post the appropriate toggle for the current row (x key)."""
        kind, item = self.current_kind_and_item()
        if kind == "file":
            self.post_message(FileToggleRequested(item))
        elif kind == "dir":
            self.post_message(DirectoryToggleRequested(item))

    def collapse_current(self) -> None:
        """Vim-tree ``h``: collapse dir, or jump to parent for file/leaf."""
        if self._engine is None:
            return
        kind, item = self.current_kind_and_item()
        if kind == "dir" and item in self._expanded:
            self._expanded.remove(item)
            self.rebuild(self._engine)
            return
        if kind is None:
            return
        parent_key = self._parent_dir_key(kind, item)
        if parent_key is None:
            return
        idx = self._index_of.get(parent_key)
        if idx is None:
            return
        self.move_cursor(row=idx, column=0, animate=False, scroll=True)

    def collapse_to_root(self) -> None:
        """Collapse every expanded directory; cursor goes to the first root."""
        if self._engine is None or not self._engine.roots:
            return
        self._expanded.clear()
        self.rebuild(
            self._engine,
            cursor_target_key=f"dir:{self._engine.roots[0]}",
        )

    def _parent_dir_key(self, kind: str, item) -> str | None:
        if self._engine is None:
            return None
        if kind == "file":
            parent = item.path.parent
        elif kind == "dir":
            parent = item.parent
        else:
            return None
        for root in self._engine.roots:
            if parent == root or parent.is_relative_to(root):
                return f"dir:{parent}"
        return None

    def expand_current(self) -> None:
        """Expand current directory if collapsed (l key)."""
        if self._engine is None:
            return
        kind, item = self.current_kind_and_item()
        if kind == "dir" and item not in self._expanded:
            self._expanded.add(item)
            self.rebuild(self._engine)

    # --- events ----------------------------------------------------

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter (or double-click): expand/collapse directory, toggle file."""
        if event.data_table is not self:
            return
        kind, item = self.current_kind_and_item()
        if kind == "dir":
            if item in self._expanded:
                self._expanded.remove(item)
            else:
                self._expanded.add(item)
            if self._engine is not None:
                self.rebuild(self._engine)
        elif kind == "file":
            self.post_message(FileToggleRequested(item))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table is not self:
            return
        self.post_message(CurrentFileChanged(self.current_file()))

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        if event.data_table is not self:
            return
        column_key = str(event.column_key.value) if event.column_key else ""
        if column_key not in {"name", "length", "mtime"}:
            return
        if column_key == self._sort_column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column_key
            self._sort_reverse = column_key in {"length", "mtime"}
        if self._engine is not None:
            self.rebuild(self._engine)

    # --- private ---------------------------------------------------

    def _current_key(self) -> str | None:
        if self.row_count == 0:
            return None
        try:
            rk, _ = self.coordinate_to_cell_key(self.cursor_coordinate)
        except Exception:
            return None
        return getattr(rk, "value", str(rk))

    def _update_scope(self) -> ContextManager:
        """Batch UI refreshes when available; fall back to no-op."""
        try:
            return self.app.batch_update()
        except (AttributeError, RuntimeError):
            return nullcontext()

    ## new version
    def _apply_scroll(self) -> None:
        pending = getattr(self, "_pending_scroll", None)
        self._pending_scroll = None
        if pending is None:
            return
        target, viewport_offset = pending
        max_scroll = max(0, self.virtual_size.height - self.size.height)
        desired = min(max(0, target - viewport_offset), max_scroll)
        try:
            self.scroll_to(y=desired, animate=False)
        except Exception:
            pass
