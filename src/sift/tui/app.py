"""Textual interface for interactive file selection and dump creation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Static,
    TabbedContent,
    TabPane,
)
from ..core import (
    SourceFile,
    validate_comment_support,
    validate_doc_support,
)
from ..engine import DumpOptions, ScanOptions, SiftEngine
from ..config import SiftConfig, load_config, resolve_scan
from .bindings import build_bindings
from .screens import OverwriteConfirmationScreen
from .screens.overwrite import DumpModalScreen
from .messages import (
    CurrentFileChanged,
    DirectoryToggleRequested,
    ExtensionToggleRequested,
    FileToggleRequested,
)
from .widgets import (
    ActionsPane,
    ExtensionsPane,
    FileTableView,
    FileTreeView,
    LogErrorCountChanged,
    LogPane,
    PreviewPane,
)
from .widgets.file_table import MAX_TABLE_ROWS

# --- main app -------------------------------------------------------------

VIEW_FILTER_DEBOUNCE = 0.25
SELECTION_COUNT_DEBOUNCE = 0.15


@dataclass(frozen=True, slots=True)
class NodePayload:
    kind: str  # "directory" | "file"
    path: Path
    root: Path
    source_file: SourceFile | None = None


class SiftApp(App[None]):
    TITLE = "SIFT · SIFT's Interactive File Trawler"
    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = "styles.tcss"

    def __init__(
        self, roots: list[Path] | None = None, config: SiftConfig | None = None
    ) -> None:
        self._config = config or load_config()
        super().__init__()
        self._default_output = ""
        for b in build_bindings(self._config.keys):
            self._bindings.bind(
                b.key, b.action, b.description or "", show=b.show, priority=b.priority
            )
        self._roots = roots or []
        self.engine: SiftEngine | None = None
        self._human_sizes = False
        self._dirty_views: set[str] = set()

        # preview state
        self._view_filter_pending: str | None = None
        self._view_filter_timer = None
        self._match_count_timer = None
        self._previous_tab = "tree-tab"

    # --- composition -------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Scanning directories…", id="title-bar")

        with Horizontal(id="filters-row"):
            yield Label("View", classes="filter-label")
            yield Input(id="view-filter", placeholder="*.py,!tests/**")
            yield Label("Selection", classes="filter-label")
            yield Input(id="selection-filter", placeholder="src/**")
            yield Label("Matches: —", id="match-count")
            yield Button("+", id="apply-add", compact=True)
            yield Button("↻", id="apply-replace", compact=True)
            yield Button("−", id="apply-remove", compact=True)

        with Horizontal(id="main-area"):
            yield ExtensionsPane(id="extensions-pane")
            with TabbedContent(initial="tree-tab", id="views"):
                with TabPane("Tree", id="tree-tab"):
                    yield FileTreeView(id="file-tree")
                with TabPane("Table", id="table-tab"):
                    yield FileTableView(id="file-table")
                with TabPane("Preview", id="preview-tab"):
                    yield PreviewPane(id="preview-view")
                with TabPane("Log", id="log-tab"):
                    yield LogPane(id="log-view")
            yield ActionsPane(id="actions-pane")

        yield Static("", id="status")
        yield Footer()

    # --- lifecycle ----------------------------------------------------

    def on_mount(self) -> None:
        roots = list(self._roots) or list(self._config.scan.roots or []) or [Path.cwd()]
        self._default_output = self._default_output_path(roots)
        include, exclude, exclude_dirs = resolve_scan(self._config.scan)
        self._scan_worker(
            roots,
            include,
            exclude,
            exclude_dirs,
            self._config.cache.path,
            self._config.cache.enabled,
        )
        if self.size.width < 80:
            self.query_one("#extensions-pane").add_class("-hidden")
        if self.size.width < 100:
            self.query_one(ActionsPane).set_hidden(True)
        self.query_one(LogPane).log_message("session started", level="info")

    def _default_output_path(self, roots: list[Path]) -> str:
        name = f"{roots[0].name}.sift.txt"
        if Path.cwd() in roots:
            return str(Path.cwd().parent / name)
        return str(Path.cwd() / name)

    @work(thread=True, exclusive=True, name="scan-files")
    def _scan_worker(
        self, roots, include, exclude, exclude_dirs, cache_path, use_cache
    ):
        try:
            engine = SiftEngine(roots, cache_path=cache_path, use_cache=use_cache)
            engine.scan(ScanOptions(include, exclude, exclude_dirs))
        except (OSError, ValueError) as exc:
            self.call_from_thread(self._scan_failed, str(exc))
            return
        self.call_from_thread(self._scan_finished, engine)

    def _scan_failed(self, message: str) -> None:
        self.query_one("#title-bar", Static).update(f"Scan failed: {message}")
        self.query_one("#status", Static).update(
            "Could not scan the source directories."
        )
        self.query_one(LogPane).log_message(f"scan failed: {message}", level="error")
        self.notify(message, title="Scan error", severity="error", timeout=8)

    def _scan_finished(self, engine: SiftEngine) -> None:
        self.engine = engine
        self.query_one("#title-bar", Static).update(
            "Roots: " + " · ".join(str(r) for r in engine.roots)
        )
        self.query_one(ExtensionsPane).rebuild(engine)
        self.query_one(FileTreeView).rebuild(engine)
        self.query_one(FileTableView).rebuild(engine)
        self._update_summary()
        self.query_one("#file-tree", DataTable).focus()

    # --- extension toggle -------------------------------------------

    def _toggle_extension(self, ext: str) -> None:
        if self.engine is None:
            return
        new_state = not self.engine.view.is_extension_enabled(ext)
        self.engine.set_extension_visible(ext, new_state)
        self._invalidate_views()
        self.query_one(ExtensionsPane).rebuild(self.engine)
        self._update_summary()

    # --- selection apply -------------------------------------------

    def _apply_selection(self, mode: str) -> None:
        if self.engine is None:
            return
        expr = self.query_one("#selection-filter", Input).value
        if not expr:
            self.notify("Enter a selection filter first.", severity="warning")
            return
        try:
            n = self.engine.apply_selection(mode, expr)
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        self._refresh_selection_labels()
        self.notify(f"{mode.capitalize()}: {n} file(s)", timeout=3)

    # --- actions ----------------------------------------------------

    def action_toggle_current(self) -> None:
        if isinstance(self.focused, Input):
            return
        wid = self.focused.id if self.focused else ""
        if wid == "extensions-table":
            ext = self.query_one(ExtensionsPane).current_extension()
        if wid == "file-tree":
            self.query_one(FileTreeView).toggle_current()
            return

    def action_toggle_visibility(self) -> None:
        if isinstance(self.focused, Input):
            return
        ext = None
        wid = self.focused.id if self.focused else ""
        if wid == "extensions-table":
            ext = self.query_one(ExtensionsPane).current_extension()
        elif wid == "file-table":
            if (f := self.query_one(FileTableView).current_file()) is not None:
                ext = f.extension
        elif wid == "file-tree":
            ext = self.query_one(FileTreeView).current_extension()
        if ext is not None:
            self._toggle_extension(ext)

    def action_toggle_extensions(self) -> None:
        if isinstance(self.focused, Input):
            return
        pane = self.query_one(ExtensionsPane)
        pane.set_hidden(not pane.is_hidden())
        self.call_after_refresh(self._focus_active_view)

    def action_toggle_actions(self) -> None:
        if isinstance(self.focused, Input):
            return
        pane = self.query_one(ActionsPane)
        pane.set_hidden(not pane.is_hidden())
        self.call_after_refresh(self._focus_active_view)

    def action_toggle_units(self) -> None:
        if isinstance(self.focused, Input):
            return
        self._human_sizes = not self._human_sizes
        self.query_one(FileTreeView).set_human_sizes(self._human_sizes)
        self.query_one(FileTableView).set_human_sizes(self._human_sizes)

    def action_next_view(self) -> None:
        if isinstance(self.focused, Input):
            return
        tabs = self.query_one("#views", TabbedContent)
        tabs.active = "table-tab" if tabs.active == "tree-tab" else "tree-tab"

    def action_show_tree(self) -> None:
        if isinstance(self.focused, Input):
            return
        self.query_one("#views", TabbedContent).active = "tree-tab"

    def action_show_table(self) -> None:
        if isinstance(self.focused, Input):
            return
        self.query_one("#views", TabbedContent).active = "table-tab"

    def action_show_preview(self) -> None:
        if isinstance(self.focused, Input):
            return
        self.query_one("#views", TabbedContent).active = "preview-tab"

    def action_show_log(self) -> None:
        if isinstance(self.focused, Input):
            return
        self.query_one("#views", TabbedContent).active = "log-tab"

    def action_cursor_down(self) -> None:
        self._move_cursor(down=True)

    def action_cursor_up(self) -> None:
        self._move_cursor(down=False)

    def _move_cursor(self, *, down: bool) -> None:
        if isinstance(self.focused, Input) or not self.focused:
            return
        wid = self.focused.id
        if wid == "extensions-list":
            table = self.query_one(ExtensionsPane).query_one(DataTable)
        elif wid == "file-table":
            table = self.query_one(FileTableView)
        elif wid == "file-tree":
            table = self.query_one(FileTreeView)
        else:
            return
        if table.row_count == 0:
            return
        row = max(0, min(table.cursor_row + (1 if down else -1), table.row_count - 1))
        table.move_cursor(row=row, column=0)

    def action_tree_left(self) -> None:
        if (
            isinstance(self.focused, Input)
            or not self.focused
            or self.focused.id != "file-tree"
        ):
            return
        self.query_one(FileTreeView).collapse_current()

    def action_tree_right(self) -> None:
        if (
            isinstance(self.focused, Input)
            or not self.focused
            or self.focused.id != "file-tree"
        ):
            return
        self.query_one(FileTreeView).expand_current()

    def action_tree_collapse_all(self) -> None:
        if (
            isinstance(self.focused, Input)
            or not self.focused
            or self.focused.id != "file-tree"
        ):
            return
        self.query_one(FileTreeView).collapse_to_root()

    def action_focus_view_filter(self) -> None:
        if not isinstance(self.focused, Input):
            self.query_one("#view-filter", Input).focus()

    def action_focus_selection_filter(self) -> None:
        if not isinstance(self.focused, Input):
            self.query_one("#selection-filter", Input).focus()

    def action_open_preview(self) -> None:
        if isinstance(self.focused, Input):
            return
        tabs = self.query_one("#views", TabbedContent)
        if tabs.active == "preview-tab":
            tabs.active = self._previous_tab
            return
        self._previous_tab = tabs.active

        if tabs.active == "tree-tab":
            f = self.query_one(FileTreeView).current_file()
        elif tabs.active == "table-tab":
            f = self.query_one(FileTableView).current_file()
        else:
            f = None
        if f:
            self.query_one(PreviewPane).load(f)
            tabs.active = "preview-tab"

    def action_toggle_preview_wrap(self) -> None:
        if isinstance(self.focused, Input):
            return
        if not self.focused or self.focused.id != "preview-view":
            return
        self.query_one(PreviewPane).toggle_soft_wrap()

    def action_quit_app(self) -> None:
        if isinstance(self.focused, Input):
            return
        self.exit()

    def action_ignore_ctrl_q(self) -> None:
        pass

    # --- tab / input events -----------------------------------------

    @on(TabbedContent.TabActivated)
    def on_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.tabbed_content.id != "views" or self.engine is None:
            return
        tab_id = event.tab.id if event.tab else ""
        if tab_id == "tree-tab" and "tree" in self._dirty_views:
            self.query_one(FileTreeView).rebuild(self.engine)
            self._dirty_views.discard("tree")
        elif tab_id == "table-tab" and "table" in self._dirty_views:
            self.query_one(FileTableView).rebuild(self.engine)
            self._dirty_views.discard("table")
        self.call_after_refresh(self._focus_active_view)

    def _focus_active_view(self) -> None:
        tabs = self.query_one("#views", TabbedContent)
        if tabs.active == "tree-tab":
            self.query_one(FileTreeView).focus()
        elif tabs.active == "table-tab":
            self.query_one(FileTableView).focus()
        elif tabs.active == "preview-tab":
            self.query_one(PreviewPane).focus()
        elif tabs.active == "log-tab":
            self.query_one(LogPane).focus()

    @on(Input.Submitted)
    def on_filter_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "selection-filter":
            self._apply_selection("replace")
        elif event.input.id == "output-path":
            self._build_dump()

    def on_extension_toggle_requested(self, msg: ExtensionToggleRequested) -> None:
        self._toggle_extension(msg.extension)

    def on_file_toggle_requested(self, msg: FileToggleRequested) -> None:
        self._toggle_file(msg.source_file)

    def on_directory_toggle_requested(self, msg: DirectoryToggleRequested) -> None:
        if self.engine is None:
            return
        files = self.engine.visible_files_under(msg.directory)
        if not files:
            return
        all_selected = all(self.engine.selection.is_selected(f) for f in files)
        self.engine.set_files_selected(files, not all_selected)
        self._refresh_selection_labels()

    def on_current_file_changed(self, msg: CurrentFileChanged) -> None:
        self.query_one(PreviewPane).load(msg.source_file)
        self._update_summary()

    def on_file_table_view_sort_changed(self, msg: FileTableView.SortChanged) -> None:
        if self.engine is None:
            return
        self.query_one(FileTableView).rebuild(self.engine)
        order = "↓" if msg.reverse else "↑"
        self.notify(f"Sort: {msg.column} {order}", timeout=2)

    def on_log_error_count_changed(self, msg: LogErrorCountChanged) -> None:
        try:
            pane = self.query_one("#log-tab", TabPane)
        except Exception:
            return
        n = msg.count
        pane.title = f"Log ({n})" if n else "Log"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply-add":
            self._apply_selection("add")
        elif event.button.id == "apply-replace":
            self._apply_selection("replace")
        elif event.button.id == "apply-remove":
            self._apply_selection("remove")
        elif event.button.id == "dump-btn":
            self._build_dump()
        elif event.button.id == "quit-button":
            self.exit()

    # --- coordinated refresh -------------------------------------

    def _refresh_selection_labels(self) -> None:
        if self.engine is None:
            return
        self.query_one(FileTableView).refresh_markers(self.engine.selection)
        self.query_one(FileTreeView).refresh_markers(self.engine)
        self.query_one(ExtensionsPane).rebuild(self.engine)
        self._update_summary()

    def _invalidate_views(self) -> None:
        self._dirty_views = {"tree", "table"}
        self._rebuild_active_view()

    def _rebuild_active_view(self) -> None:
        if self.engine is None:
            return
        tabs = self.query_one("#views", TabbedContent)
        if tabs.active == "tree-tab" and "tree" in self._dirty_views:
            self.query_one(FileTreeView).rebuild(self.engine)
            self._dirty_views.discard("tree")
        elif tabs.active == "table-tab" and "table" in self._dirty_views:
            self.query_one(FileTableView).rebuild(self.engine)
            self._dirty_views.discard("table")

    # --- directory toggle in tree --------------------------------

    def _toggle_file(self, f: SourceFile) -> None:
        try:
            self.engine.toggle_file(f)
        except RuntimeError:
            return
        self._refresh_selection_labels()

    # --- debounced filters ---------------------------------------

    @on(Input.Changed)
    def on_filter_changed(self, event: Input.Changed) -> None:
        if self.engine is None:
            return
        if event.input.id == "view-filter":
            self._view_filter_pending = event.value
            if self._view_filter_timer is not None:
                self._view_filter_timer.stop()
            self._view_filter_timer = self.set_timer(
                VIEW_FILTER_DEBOUNCE,
                self._commit_view_filter,
            )
        elif event.input.id == "selection-filter":
            if self._match_count_timer is not None:
                self._match_count_timer.stop()
            self._match_count_timer = self.set_timer(
                SELECTION_COUNT_DEBOUNCE,
                self._commit_match_count,
            )

    def _commit_view_filter(self) -> None:
        expr = self._view_filter_pending
        self._view_filter_pending = None
        if expr is None or self.engine is None:
            return
        self.engine.set_view_patterns(expr)
        self._invalidate_views()
        self._update_summary()

    def _commit_match_count(self) -> None:
        if self.engine is None:
            return
        expr = self.query_one("#selection-filter", Input).value
        count = self.engine.count_selection_matches(expr)
        label = f"Matches: {count}" if expr else "Matches: —"
        self.query_one("#match-count", Label).update(label)

    # --- status bar ----------------------------------------------

    def _update_summary(self) -> None:
        if self.engine is None:
            return
        d = len(self.engine.files)
        v = len(self.engine.visible_files())
        s = len(self.engine.selected_files())
        expr = self.query_one("#selection-filter", Input).value
        matches = self.engine.count_selection_matches(expr) if expr else "—"
        visible_label = f"{v}"
        if v > MAX_TABLE_ROWS:
            visible_label += f" (showing {MAX_TABLE_ROWS})"
        current = self.query_one(PreviewPane).target
        path = f" · {current.path}" if current else ""
        self.query_one("#status", Static).update(
            f"Discovered: {d} · Visible: {visible_label} · "
            f"Matches: {matches} · Selected: {s}{path}"
        )

    def _build_dump(self) -> None:
        if self.engine is None:
            self.notify("Scan not complete.", severity="warning")
            return
        selected = list(self.engine.selected_files())
        if not selected:
            self.notify("No files selected.", severity="warning")
            return

        self.push_screen(
            DumpModalScreen(self._default_output),
            lambda output: self._on_dump_path(output, selected),
        )

    def _on_dump_path(self, output: Path | None, selected: list[SourceFile]) -> None:
        if output is None:
            return

        if output.exists() and output.is_dir():
            self.notify(f"Output is a directory: {output}", severity="error")
            return

        try:
            dest = output.resolve()
            selected = [f for f in selected if f.path.resolve() != dest]
        except OSError:
            pass

        if not selected:
            self.notify("No files to write (output file excluded).", severity="warning")
            return

        opts = DumpOptions(
            absolute_paths=self._config.dump.absolute_paths,
            file_format=self._config.dump.file_format,
            remove_comments=self.query_one("#remove-comments", Checkbox).value,
            remove_docs=self.query_one("#remove-docs", Checkbox).value,
            compact_json_files=self.query_one("#compact-json", Checkbox).value,
            strip_leading_whitespace=self.query_one(
                "#strip-whitespace", Checkbox
            ).value,
        )

        try:
            if opts.remove_comments:
                validate_comment_support(selected)
            if opts.remove_docs:
                validate_doc_support(selected)
        except (OSError, ValueError) as exc:
            self.notify(str(exc), title="Could not create dump", severity="error")
            return

        if output.exists() or output.is_symlink():
            self.push_screen(
                OverwriteConfirmationScreen(output),
                lambda ok: self._on_overwrite_confirmation(ok, selected, output, opts),
            )
            return
        self._write_dump(selected, output, opts)

    def _execute_dump(self, path: Path, selected: list[SourceFile]) -> None:
        if path.exists() and path.is_dir():
            self.notify(f"Output is a directory: {path}", severity="error")
            return

        try:
            dest = path.resolve()
            selected = [f for f in selected if f.path.resolve() != dest]
        except OSError:
            pass

        if not selected:
            self.notify("No files to write (output file excluded).", severity="warning")
            return

        opts = DumpOptions(
            absolute_paths=self._config.dump.absolute_paths,
            file_format=self._config.dump.file_format,
            remove_comments=self.query_one("#remove-comments", Checkbox).value,
            remove_docs=self.query_one("#remove-docs", Checkbox).value,
            compact_json_files=self.query_one("#compact-json", Checkbox).value,
            strip_leading_whitespace=self.query_one(
                "#strip-whitespace", Checkbox
            ).value,
        )
        try:
            if opts.remove_comments:
                validate_comment_support(selected)
            if opts.remove_docs:
                validate_doc_support(selected)
        except (OSError, ValueError) as exc:
            self.notify(str(exc), title="Could not create dump", severity="error")
            return
        if path.exists() or path.is_symlink():
            self.push_screen(
                OverwriteConfirmationScreen(path),
                lambda ok: self._on_overwrite_confirmation(ok, selected, path, opts),
            )
            return
        self._write_dump(selected, path, opts)

    def _on_overwrite_confirmation(self, ok, selected, output, opts) -> None:
        if ok:
            self._write_dump(selected, output, opts)
        else:
            self.notify("Cancelled.", timeout=3)

    def _write_dump(self, selected, output, opts) -> None:
        self.notify(f"Writing {len(selected)} file(s)…", timeout=2)
        self.query_one(LogPane).log_message(
            f"dump requested: {len(selected)} file(s) → {output}", level="info"
        )
        self._write_dump_worker(selected, output, opts)

    @work(thread=True, exclusive=True, name="write-dump")
    def _write_dump_worker(self, selected, output, opts) -> None:
        try:
            result = self.engine.write_dump(selected, output, opts)
        except (OSError, UnicodeError, ValueError) as exc:
            self.call_from_thread(self._on_dump_error, str(exc))
            return
        self.call_from_thread(self._on_dump_complete, result, output)

    def _on_dump_error(self, message: str) -> None:
        self.query_one(LogPane).log_message(f"dump failed: {message}", level="error")
        self.notify(
            message, title="Could not create dump", severity="error", timeout=10
        )

    def _on_dump_complete(self, result, output: Path) -> None:
        n = result.written
        issues = len(result.errors)
        for err in result.errors:
            level = "error" if err.kind == "read" else "warn"
            self.query_one(LogPane).log_message(
                f"{err.path}: {err.message}", level=level
            )
        if issues:
            self.notify(
                f"Wrote {n} file(s); {issues} issue(s) — see Log tab",
                title="Dump complete (with warnings)",
                timeout=8,
            )
        else:
            self.notify(
                f"Wrote {n} file(s) to {output}", title="Dump complete", timeout=8
            )
        self.query_one(LogPane).log_message(
            f"dump written: {n} file(s) → {output}", level="info"
        )


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
