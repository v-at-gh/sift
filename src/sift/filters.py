"""View and selection filters over a scanned FileIndex.

Both filters share one expression grammar::

    *.py,*.json,!tests/**

comma-separated; ``!`` prefix marks an exclusion. A file matches if it
matches any include (or there are no includes) AND matches no exclude.

Matching uses gitignore-style ``**`` semantics for the filters, while
``collect_files(--include/--exclude)`` keeps plain fnmatch. For patterns
without ``**`` the behaviour is identical.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable

from .core import SourceFile


# --- expression parsing ---------------------------------------------------

def parse_filter_expression(expr: str) -> tuple[list[str], list[str]]:
    """Parse ``*.py,*.json,!tests/**`` into (``*.py``,``*.json``), (``tests/**``)."""
    includes: list[str] = []
    excludes: list[str] = []
    for raw in expr.split(","):
        token = raw.strip()
        if not token:
            continue
        if token.startswith("!"):
            target = token[1:].strip()
            if target:
                excludes.append(target)
        else:
            includes.append(token)
    return includes, excludes


# --- glob matching --------------------------------------------------------

def filter_matches(
    source_file: SourceFile,
    includes: list[str],
    excludes: list[str],
) -> bool:
    """True iff *source_file* matches includes AND matches no excludes."""
    name = source_file.path.name
    rel = source_file.relative_path
    if excludes and _matches_any(name, rel, excludes):
        return False
    if includes and not _matches_any(name, rel, includes):
        return False
    return True


def _matches_any(name: str, relative: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        candidate = relative if "/" in pattern else name
        if _glob_match(candidate, pattern):
            return True
    return False


def _glob_match(candidate: str, pattern: str) -> bool:
    if "**" in pattern:
        return _compile_doublestar(pattern).fullmatch(candidate) is not None
    return fnmatch.fnmatchcase(candidate, pattern)


@lru_cache(maxsize=1024)
def _compile_doublestar(pattern: str) -> re.Pattern[str]:
    """Translate a glob to a regex with gitignore-style ``**``.

    - ``**/`` at a segment boundary: zero or more leading path segments;
    - ``/**`` at the end: anything below;
    - ``**`` inside a segment: treated as a plain ``*`` (does not cross ``/``);
    - bare ``*``: any chars except ``/``;
    - bare ``?``: one char except ``/``;
    - ``[!...]``: negated character class.
    """
    parts: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        ch = pattern[i]
        if ch == "*" and i + 1 < n and pattern[i + 1] == "*":
            is_start = i == 0 or pattern[i - 1] == "/"
            is_end = (i + 2 == n) or pattern[i + 2] == "/"
            if is_start and is_end:
                i += 2
                if i < n and pattern[i] == "/":
                    parts.append("(?:[^/]+/)*")
                    i += 1
                else:
                    parts.append(".*")
                continue
            # `**` not on segment boundary: two plain stars -> one `[^/]*`
            parts.append("[^/]*")
            i += 2
        elif ch == "*":
            parts.append("[^/]*")
            i += 1
        elif ch == "?":
            parts.append("[^/]")
            i += 1
        elif ch == "[":
            j = i + 1
            if j < n and pattern[j] == "!":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j < n:
                body = pattern[i + 1:j]
                if body.startswith("!"):
                    body = "^" + body[1:]
                parts.append("[" + body + "]")
                i = j + 1
            else:
                parts.append(re.escape(ch))
                i += 1
        else:
            parts.append(re.escape(ch))
            i += 1
    return re.compile("".join(parts) + r"\Z")


# --- view query -----------------------------------------------------------

def _extension_sort_key(ext: str) -> tuple[int, str]:
    return (1, "") if not ext else (0, ext)


@dataclass
class ViewQuery:
    """What is *shown*. Independent of what is *selected*."""

    all_extensions: list[str] = field(default_factory=list)
    enabled_extensions: set[str] = field(default_factory=set)
    includes: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.enabled_extensions:
            self.enabled_extensions = set(self.all_extensions)

    @classmethod
    def from_files(cls, files: Iterable[SourceFile]) -> "ViewQuery":
        exts = sorted({f.extension for f in files}, key=_extension_sort_key)
        return cls(all_extensions=exts)

    def set_patterns(self, expr: str) -> None:
        self.includes, self.excludes = parse_filter_expression(expr)

    def set_extension_enabled(self, ext: str, enabled: bool) -> None:
        if enabled:
            self.enabled_extensions.add(ext)
        else:
            self.enabled_extensions.discard(ext)

    def is_extension_enabled(self, ext: str) -> bool:
        return ext in self.enabled_extensions

    def is_visible(self, source_file: SourceFile) -> bool:
        if source_file.extension not in self.enabled_extensions:
            return False
        return filter_matches(source_file, self.includes, self.excludes)

    def visible(self, files: Iterable[SourceFile]) -> list[SourceFile]:
        return [f for f in files if self.is_visible(f)]


# --- selection model ------------------------------------------------------

_APPLY_MODES = frozenset({"add", "replace", "remove"})


class SelectionModel:
    """Explicit set of selected file identities, independent of visibility."""

    def __init__(self, files: Iterable[SourceFile]) -> None:
        self.files = list(files)
        self.selected: set[str] = set()

    def is_selected(self, source_file: SourceFile) -> bool:
        return source_file.identity in self.selected

    def toggle_file(self, source_file: SourceFile) -> None:
        if source_file.identity in self.selected:
            self.selected.discard(source_file.identity)
        else:
            self.selected.add(source_file.identity)

    def set_files_selected(
        self, files: Iterable[SourceFile], selected: bool,
    ) -> None:
        for source_file in files:
            if selected:
                self.selected.add(source_file.identity)
            else:
                self.selected.discard(source_file.identity)

    def selected_files(self) -> list[SourceFile]:
        return [f for f in self.files if f.identity in self.selected]

    def selected_count(self) -> int:
        return len(self.selected)

    def count_matches(self, expr: str) -> int:
        """Count files matching *expr* across the whole index."""
        includes, excludes = parse_filter_expression(expr)
        if not includes and not excludes:
            return 0
        return sum(1 for f in self.files if filter_matches(f, includes, excludes))

    def apply_pattern(self, mode: str, expr: str) -> int:
        """Apply a selection filter across the whole index.

        *mode*: ``add`` (Select matches), ``replace`` (Replace selection),
        ``remove`` (Deselect matches). Returns the number of matching files.
        """
        if mode not in _APPLY_MODES:
            raise ValueError(f"unknown apply mode: {mode!r}")
        includes, excludes = parse_filter_expression(expr)
        if not includes and not excludes:
            return 0
        matches = [f for f in self.files if filter_matches(f, includes, excludes)]
        if mode == "replace":
            self.selected = {f.identity for f in matches}
        elif mode == "add":
            self.selected.update(f.identity for f in matches)
        else:
            self.selected.difference_update(f.identity for f in matches)
        return len(matches)

    def selection_state(self, files: Iterable[SourceFile]) -> str:
        files = list(files)
        if not files:
            return "none"
        n = sum(1 for f in files if f.identity in self.selected)
        if n == 0:
            return "none"
        if n == len(files):
            return "all"
        return "partial"
