"""Presentation-agnostic facade over scanning, dumping, and restoring."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, TextIO

from .cache import Cache, compute_checksum
from .core import (
    DEFAULT_FILE_FORMAT,
    SourceFile,
    DumpError,
    DumpResult,
    collect_files,
    write_dump_atomic,
    write_dump_stream,
)
from .filters import SelectionModel, ViewQuery
from .restore import restore_dump


@dataclass
class ScanOptions:
    """Concrete patterns. The engine applies them verbatim; no defaults."""
    include_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)
    exclude_dir_patterns: list[str] = field(default_factory=list)


@dataclass
class DumpOptions:
    absolute_paths: bool = False
    file_format: str = DEFAULT_FILE_FORMAT
    remove_comments: bool = False
    remove_docs: bool = False
    compact_json_files: bool = False
    strip_leading_whitespace: bool = False


class SiftEngine:
    """Stateless w.r.t. configuration; stateful only w.r.t. scan results."""

    def __init__(
        self,
        roots: Iterable[Path],
        *,
        cache_path: Path | None = None,
        use_cache: bool = True,
    ) -> None:
        self.roots = list(roots)
        self.cache_path = cache_path
        self.use_cache = use_cache
        self.files: list[SourceFile] = []
        self.view: ViewQuery | None = None
        self.selection: SelectionModel | None = None
        self._visible_cache: list[SourceFile] | None = None
        self._files_under_cache: dict[Path, list[SourceFile]] | None = None
        self._dir_counts: dict[Path, tuple[int, int]] | None = None
        self._dir_sizes: dict[Path, int] | None = None
        self._dirs_with_visible: set[Path] | None = None
        self._dir_children: dict[Path, set[Path]] | None = None
        self._dir_mtimes: dict[Path, int] | None = None
        self._dir_ctimes: dict[Path, int] | None = None

    # --- caches ------------------------------------------------------

    def _invalidate_view(self) -> None:
        self._visible_cache = None
        self._files_under_cache = None
        self._dir_counts = None
        self._dir_sizes = None
        self._dirs_with_visible = None
        self._dir_children = None
        self._dir_mtimes = None
        self._dir_ctimes = None

    def _invalidate_selection_counts(self) -> None:
        self._dir_counts = None

    def _rebuild_view_caches(self) -> None:
        visible = [f for f in self.files if self.view.is_visible(f)]
        self._visible_cache = visible

        files_under: dict[Path, list[SourceFile]] = {}
        dirs_with_visible: set[Path] = set()
        sizes: dict[Path, int] = {}
        mtimes: dict[Path, int] = {}
        ctimes: dict[Path, int] = {}

        for f in visible:
            cur = f.path.parent
            while True:
                files_under.setdefault(cur, []).append(f)
                dirs_with_visible.add(cur)
                sizes[cur] = sizes.get(cur, 0) + f.size
                mtimes[cur] = max(mtimes.get(cur, 0), f.mtime_ns)
                ctimes[cur] = max(ctimes.get(cur, 0), f.ctime_ns)
                if cur == f.root or cur.parent == cur:
                    break
                cur = cur.parent

        self._files_under_cache = files_under
        self._dirs_with_visible = dirs_with_visible
        self._dir_sizes = sizes
        self._dir_mtimes = mtimes
        self._dir_ctimes = ctimes

        dir_children: dict[Path, set[Path]] = {}
        for d in dirs_with_visible:
            if d.parent != d:
                dir_children.setdefault(d.parent, set()).add(d)
        self._dir_children = dir_children

        self._rebuild_dir_counts()

    def _rebuild_dir_counts(self) -> None:
        """Recompute per-directory (total, selected) from the cached visible list.

        Called on selection change: ``_visible_cache`` and the directory maps
        stay valid, only the selection-dependent counts need rebuilding.
        """
        counts: dict[Path, list[int]] = {}
        for f in self._visible_cache or ():
            sel = 1 if f.identity in self.selection.selected else 0
            cur = f.path.parent
            while True:
                entry = counts.setdefault(cur, [0, 0])
                entry[0] += 1
                entry[1] += sel
                if cur == f.root or cur.parent == cur:
                    break
                cur = cur.parent
        self._dir_counts = {k: tuple(v) for k, v in counts.items()}

    def scan(self, options: ScanOptions) -> list[SourceFile]:
        cache = None
        if self.use_cache:
            try:
                cache = Cache(self.cache_path)
                cache.begin_scan()
            except (OSError, RuntimeError):
                cache = None
        try:
            self.files = collect_files(
                self.roots,
                include_patterns=options.include_patterns,
                exclude_patterns=options.exclude_patterns,
                exclude_dir_patterns=options.exclude_dir_patterns,
                cache=cache,
            )
            if cache is not None:
                cache.prune()
                cache.commit()
        finally:
            if cache is not None:
                cache.close()
        self.view = ViewQuery.from_files(self.files)
        self.selection = SelectionModel(self.files)
        return self.files

    # --- view cache invalidation on mutations ------------------------

    def set_view_patterns(self, expr: str) -> None:
        self._require_scan("set_view_patterns").view.set_patterns(expr)
        self._invalidate_view()

    def set_extension_visible(self, ext: str, visible: bool) -> None:
        self._require_scan("set_extension_visible").view.set_extension_enabled(ext, visible)
        self._invalidate_view()

    # --- fast accessors ----------------------------------------------

    def visible_files(self) -> list[SourceFile]:
        if self._visible_cache is None:
            self._rebuild_view_caches()
        return self._visible_cache

    def visible_files_under(self, directory: Path) -> list[SourceFile]:
        self.visible_files()
        return self._files_under_cache.get(directory, [])

    def dir_counts(self, directory: Path) -> tuple[int, int]:
        if self._visible_cache is None:
            self._rebuild_view_caches()
        elif self._dir_counts is None:
            self._rebuild_dir_counts()
        return self._dir_counts.get(directory, (0, 0))

    def dir_size(self, directory: Path) -> int:
        if self._visible_cache is None:
            self._rebuild_view_caches()
        return self._dir_sizes.get(directory, 0)

    def dir_mtime(self, directory: Path) -> int:
        if self._visible_cache is None:
            self._rebuild_view_caches()
        return self._dir_mtimes.get(directory, 0)

    def dir_ctime(self, directory: Path) -> int:
        if self._visible_cache is None:
            self._rebuild_view_caches()
        return self._dir_ctimes.get(directory, 0)

    def has_visible_under(self, directory: Path) -> bool:
        self.visible_files()
        return directory in self._dirs_with_visible

    def children_of(self, directory: Path) -> tuple[list[Path], list[SourceFile]]:
        """(subdirs with visible content, visible files in *directory* directly)."""
        self.visible_files()
        subdirs = sorted(self._dir_children.get(directory, set()))
        files = [
            f for f in self._files_under_cache.get(directory, [])
            if f.path.parent == directory
        ]
        return subdirs, files

    # --- selection invalidation --------------------------------------

    def toggle_file(self, source_file: SourceFile) -> None:
        self._require_scan("toggle_file").selection.toggle_file(source_file)
        self._invalidate_selection_counts()

    def set_files_selected(
        self, files: Iterable[SourceFile], selected: bool,
    ) -> None:
        self._require_scan("set_files_selected").selection.set_files_selected(
            list(files), selected,
        )
        self._invalidate_selection_counts()

    # --- selection -------------------------------------------------------

    def apply_selection(self, mode: str, expr: str) -> int:
        n = self._require_scan("apply_selection").selection.apply_pattern(mode, expr)
        self._invalidate_selection_counts()
        return n

    def count_selection_matches(self, expr: str) -> int:
        if self.selection is None:
            return 0
        return self.selection.count_matches(expr)

    def set_file_selected(self, source_file: SourceFile, selected: bool) -> None:
        self._require_scan("set_file_selected").selection.set_files_selected(
            [source_file], selected,
        )
        self._invalidate_selection_counts()

    def selected_files(self) -> list[SourceFile]:
        if self.selection is None:
            return []
        return self.selection.selected_files()

    # --- helper ----------------------------------------------------------

    def _require_scan(self, operation: str) -> "SiftEngine":
        if self.view is None or self.selection is None:
            raise RuntimeError(f"scan() must be called before {operation}")
        return self

    def write_dump(
        self,
        files: Iterable[SourceFile],
        output: Path | None,
        options: DumpOptions,
        *,
        stream: TextIO | None = None,
        on_error: Callable[[DumpError], None] | None = None,
    ) -> DumpResult:
        kwargs = dict(
            absolute_paths=options.absolute_paths,
            file_format=options.file_format,
            remove_comments=options.remove_comments,
            remove_docs=options.remove_docs,
            compact_json_files=options.compact_json_files,
            strip_leading_whitespace=options.strip_leading_whitespace,
            on_error=on_error,
        )
        if stream is not None:
            return write_dump_stream(files, stream, **kwargs)
        if output is None:
            raise ValueError("output path is required when stream is not provided")
        return write_dump_atomic(files, output, **kwargs)

    @staticmethod
    def restore(dump: Path, target: Path, *, overwrite: bool = False) -> int:
        return restore_dump(dump, target, overwrite=overwrite)

    def checksum(self, source_file: SourceFile) -> str:
        if not self.use_cache:
            return compute_checksum(source_file.path)
        with Cache(self.cache_path) as cache:
            return cache.checksum_for(source_file.path)
