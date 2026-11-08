"""Core file discovery and dump-writing logic, independent of CLI and TUI."""

from __future__ import annotations

import ast
import fnmatch
import io
import json
import os
import re
import sys
import tempfile
import tokenize
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, TextIO

import stat as _stat
from .cache import Cache
from .markers import make_markers

DEFAULT_FILE_FORMAT = "{opener}\n{content}{closer}\n"
DEFAULT_EXCLUDE_DIRS = [
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".gradle",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "build",
    "dist",
    "target",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "site-packages",
]
DEFAULT_TUI_EXCLUDE_DIRS = DEFAULT_EXCLUDE_DIRS
LEADING_WHITESPACE_RE = re.compile(r"^[^\S\r\n]+", re.MULTILINE)

PYTHON_EXTENSIONS = {".py", ".pyi", ".pyw"}
KOTLIN_EXTENSIONS = {".kt", ".kts"}
C_STYLE_COMMENT_OPTIONS: dict[str, dict[str, object]] = {}
for _extension in (".dart",):
    C_STYLE_COMMENT_OPTIONS[_extension] = {
        "nested_block_comments": False,
        "triple_quotes": {'"', "'"},
        "raw_triple_quotes": False,
        "raw_prefixes": True,
        "cpp_raw_strings": False,
        "backtick_mode": None,
    }
for _extension in (".java", ".c", ".h", ".cc", ".hh", ".cpp", ".hpp", ".cxx", ".hxx"):
    C_STYLE_COMMENT_OPTIONS[_extension] = {
        "nested_block_comments": False,
        "triple_quotes": {'"'} if _extension == ".java" else set(),
        "raw_triple_quotes": False,
        "raw_prefixes": False,
        "cpp_raw_strings": _extension in {".cc", ".hh", ".cpp", ".hpp", ".cxx", ".hxx"},
        "backtick_mode": None,
    }
C_STYLE_COMMENT_OPTIONS[".go"] = {
    "nested_block_comments": False,
    "triple_quotes": set(),
    "raw_triple_quotes": False,
    "raw_prefixes": False,
    "cpp_raw_strings": False,
    "backtick_mode": "raw",
}

# Formats where leading whitespace is semantic. --strip-leading-whitespace
# silently skips files with these extensions / names, leaving them untouched.
STRIP_UNSAFE_EXTENSIONS = frozenset(
    {
        ".py",
        ".pyi",
        ".pyw",
        ".yaml",
        ".yml",
        ".mk",
        ".md",
        ".markdown",
        ".rst",
    }
)
STRIP_UNSAFE_FILENAMES = frozenset(
    {
        "makefile",
        "gnumakefile",
        "bsdmakefile",
    }
)


def strip_is_unsafe(path: Path) -> bool:
    """True if leading-whitespace stripping would change file semantics."""
    if path.suffix.lower() in STRIP_UNSAFE_EXTENSIONS:
        return True
    return path.name.lower() in STRIP_UNSAFE_FILENAMES


def is_binary(path: Path, probe_size: int = 8192) -> bool:
    """Heuristic: a NUL byte in the first *probe_size* bytes marks binary.

    Matches the convention used by git and ripgrep. A missing or
    unreadable file returns False (the caller's own read will surface
    the real error).
    """
    try:
        with path.open("rb") as handle:
            chunk = handle.read(probe_size)
    except OSError:
        return False
    return b"\x00" in chunk


@dataclass(frozen=True, slots=True)
class SourceFile:
    """A discovered file and its path relative to the root that found it."""

    path: Path
    root: Path
    relative_path: str
    size: int = 0
    mtime_ns: int = 0
    ctime_ns: int = 0

    @property
    def extension(self) -> str:
        """Lowercase suffix, or an empty string for extensionless files."""
        return self.path.suffix.lower()

    @property
    def identity(self) -> str:
        """Stable identity used by selection models; does not resolve symlinks."""
        return os.path.abspath(self.path)


@dataclass(frozen=True, slots=True)
class DumpError:
    """A per-file problem encountered while writing a dump.

    ``kind="read"``     — file could not be read; it is skipped.
    ``kind="transform"`` — a content transform failed; original content is kept.
    """

    path: Path
    message: str
    kind: str  # "read" | "transform"


@dataclass(frozen=True, slots=True)
class DumpResult:
    written: int
    errors: tuple[DumpError, ...] = ()


def validate_roots(raw_roots: Iterable[str | Path]) -> list[Path]:
    """Expand and validate all root paths, failing if any are not directories."""
    roots: list[Path] = []
    for raw_root in raw_roots:
        root = Path(raw_root).expanduser().absolute()
        if not root.exists():
            raise ValueError(f"source path does not exist: {root}")
        if not root.is_dir():
            raise ValueError(f"source path is not a directory: {root}")
        roots.append(root)
    if not roots:
        raise ValueError("at least one source directory is required")
    return roots


def parse_patterns(values: list[str] | None) -> list[str]:
    """Parse repeated glob arguments and comma/brace-separated pattern lists."""
    patterns: list[str] = []
    for value in values or []:
        value = value.strip()
        if value.startswith("{") and value.endswith("}"):
            value = value[1:-1]
        patterns.extend(item.strip() for item in value.split(",") if item.strip())
    return patterns


def expand_format_escapes(value: str) -> str:
    """Expand common backslash escapes without damaging non-ASCII text."""
    replacements = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\"}
    result: list[str] = []
    i = 0
    while i < len(value):
        if value[i] == "\\" and i + 1 < len(value) and value[i + 1] in replacements:
            result.append(replacements[value[i + 1]])
            i += 2
        else:
            result.append(value[i])
            i += 1
    return "".join(result)


def glob_matches(name: str, relative_path: str, patterns: Iterable[str]) -> bool:
    """Match glob against basename, or root-relative path when pattern has '/'."""
    for pattern in patterns:
        candidate = relative_path if "/" in pattern else name
        if fnmatch.fnmatchcase(candidate, pattern):
            return True
    return False


def collect_files(
    roots: list[Path],
    output_path: Path | None = None,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    exclude_dir_patterns: list[str] | None = None,
    cache: Cache | None = None,
) -> list[SourceFile]:
    """Discover files matching glob rules without following symlinks.

    Discovery preserves the native `os.scandir` order, which is broadly similar to
    the old `find`-based script. Callers can sort a separate presentation copy.
    """
    if not include_patterns:
        include_patterns = ["*"]
    exclude_patterns = exclude_patterns or []
    exclude_dir_patterns = exclude_dir_patterns or []

    files: list[SourceFile] = []
    seen: set[str] = set()
    output_absolute = os.path.abspath(output_path) if output_path is not None else None
    try:
        output_resolved = output_path.resolve() if output_path is not None else None
    except OSError:
        output_resolved = output_path

    def walk(root: Path, directory: Path) -> None:
        try:
            with os.scandir(directory) as iterator:
                entries = list(iterator)
        except OSError as exc:
            raise OSError(f"cannot read directory {directory}: {exc}") from exc

        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise OSError(f"cannot stat {path}: {exc}") from exc

            if _stat.S_ISDIR(st.st_mode):
                if not glob_matches(entry.name, relative, exclude_dir_patterns):
                    walk(root, path)
                continue

            if not _stat.S_ISREG(st.st_mode):
                continue
            if glob_matches(entry.name, relative, exclude_patterns):
                continue
            if not glob_matches(entry.name, relative, include_patterns):
                continue

            absolute = os.path.abspath(path)
            if output_absolute is not None and absolute == output_absolute:
                continue
            if output_resolved is not None:
                try:
                    if path.resolve() == output_resolved:
                        continue
                except OSError:
                    pass

            if absolute not in seen:
                seen.add(absolute)
                if cache is not None:
                    cache.record_stat(absolute, st)
                files.append(
                    SourceFile(
                        path=path,
                        root=root,
                        relative_path=relative,
                        size=st.st_size,
                        mtime_ns=st.st_mtime_ns,
                        ctime_ns=st.st_ctime_ns,
                    )
                )

    for root in roots:
        if glob_matches(root.name, ".", exclude_dir_patterns):
            continue
        walk(root, root)
    return files


def blank_comment_spans(source: str, spans: list[tuple[int, int]]) -> str:
    """Blank comment spans while preserving all line endings and source offsets."""
    chars = list(source)
    for start, end in spans:
        for index in range(start, end):
            if chars[index] not in "\r\n":
                chars[index] = "\t" if chars[index] == "\t" else " "
    return "".join(chars)


def remove_python_comments(source: str) -> str:
    """Remove Python COMMENT tokens while preserving strings and source positions."""
    line_starts = [0]
    for line in source.splitlines(keepends=True):
        line_starts.append(line_starts[-1] + len(line))

    spans: list[tuple[int, int]] = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type != tokenize.COMMENT:
                continue
            start_row, start_col = token.start
            end_row, end_col = token.end
            # A Unix shebang is lexed as a Python COMMENT, but is operational
            # metadata for direct execution rather than prose to strip.
            if start_row == 1 and start_col == 0 and token.string.startswith("#!"):
                continue
            start = line_starts[start_row - 1] + start_col
            end = line_starts[end_row - 1] + end_col
            spans.append((start, end))
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        raise ValueError(f"cannot safely tokenize Python source: {exc}") from exc
    return blank_comment_spans(source, spans)


def remove_python_docstrings(source: str) -> str:
    """Blank module, class, and function docstrings without touching other strings."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(f"cannot safely locate Python docstrings: {exc}") from exc

    encoded_lines = source.encode("utf-8").splitlines(keepends=True)
    line_starts = [0]
    for line in encoded_lines:
        line_starts.append(line_starts[-1] + len(line))

    owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, owners) or not node.body:
            continue
        first = node.body[0]
        if not (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
            and first.end_lineno is not None
            and first.end_col_offset is not None
        ):
            continue
        start = line_starts[first.lineno - 1] + first.col_offset
        end = line_starts[first.end_lineno - 1] + first.end_col_offset
        spans.append((start, end))
    return blank_comment_byte_spans(source, spans)


def blank_comment_byte_spans(source: str, spans: list[tuple[int, int]]) -> str:
    """Blank UTF-8 byte spans, preserving byte offsets and line endings."""
    encoded = bytearray(source.encode("utf-8"))
    for start, end in spans:
        for index in range(start, end):
            if encoded[index] not in (0x0A, 0x0D, 0x09):
                encoded[index] = 0x20
    return encoded.decode("utf-8")


_KOTLIN_PARSER = None


def get_kotlin_parser():
    """Return a cached Tree-sitter Kotlin parser or an actionable install error."""
    global _KOTLIN_PARSER
    if _KOTLIN_PARSER is not None:
        return _KOTLIN_PARSER
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_kotlin
    except ImportError as exc:
        raise ValueError(
            "Kotlin comment removal requires optional dependencies; run "
            "`uv sync --extra kotlin` in the project environment"
        ) from exc

    language = Language(tree_sitter_kotlin.language())
    try:
        _KOTLIN_PARSER = Parser(language)
    except TypeError:
        _KOTLIN_PARSER = Parser()
        _KOTLIN_PARSER.set_language(language)
    return _KOTLIN_PARSER


def _kotlin_comment_spans(
    source: str,
    path: Path | None = None,
    *,
    doc_comments_only: bool = False,
) -> list[tuple[int, int]]:
    """Use Tree-sitter to locate Kotlin comments in an isolated file."""
    parser = get_kotlin_parser()
    encoded = source.encode("utf-8")
    tree = parser.parse(encoded)
    if tree.root_node.has_error:
        label = str(path) if path is not None else "Kotlin source"
        print(
            f"warning: Tree-sitter reported syntax errors in {label}; "
            "comment extraction may be incomplete",
            file=sys.stderr,
        )

    spans: list[tuple[int, int]] = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if "comment" in node.type.lower():
            comment = encoded[node.start_byte : node.end_byte]
            is_doc_comment = comment.startswith((b"/**", b"///", b"//!"))
            if not doc_comments_only or is_doc_comment:
                spans.append((node.start_byte, node.end_byte))
        else:
            stack.extend(reversed(node.children))
    return spans


def remove_kotlin_comments(source: str, path: Path | None = None) -> str:
    """Remove Kotlin comments using Tree-sitter's grammar."""
    return blank_comment_byte_spans(source, _kotlin_comment_spans(source, path))


def remove_kotlin_doc_comments(source: str, path: Path | None = None) -> str:
    """Remove KDoc comments while leaving ordinary Kotlin comments untouched."""
    return blank_comment_byte_spans(
        source, _kotlin_comment_spans(source, path, doc_comments_only=True)
    )


def _skip_rust_raw_string(source: str, start: int) -> int | None:
    """Skip a Rust raw/raw-byte string beginning at *start*, if present."""
    if start > 0 and (source[start - 1].isalnum() or source[start - 1] == "_"):
        return None
    prefix = next(
        (candidate for candidate in ("br", "r") if source.startswith(candidate, start)),
        None,
    )
    if prefix is None:
        return None
    quote = start + len(prefix)
    while quote < len(source) and source[quote] == "#":
        quote += 1
    if quote >= len(source) or source[quote] != '"':
        return None
    terminator = '"' + "#" * (quote - start - len(prefix))
    closing = source.find(terminator, quote + 1)
    return len(source) if closing == -1 else closing + len(terminator)


def _skip_rust_char_literal(source: str, start: int) -> int | None:
    """Skip a Rust char literal, while not mistaking lifetimes like `'a` for one."""
    if start + 2 >= len(source) or source[start] != "'":
        return None
    i = start + 1
    if source[i] in "\r\n":
        return None
    if source[i] == "\\":
        i += 1
        if i >= len(source) or source[i] in "\r\n":
            return None
        if source[i] == "x":
            i += 3  # x plus two hexadecimal digits
        elif source[i] == "u" and i + 1 < len(source) and source[i + 1] == "{":
            close_brace = source.find("}", i + 2)
            if close_brace == -1:
                return None
            i = close_brace + 1
        else:
            i += 1
    else:
        i += 1
    if i < len(source) and source[i] == "'":
        return i + 1
    return None


def remove_rust_doc_comments(source: str) -> str:
    """Remove Rustdoc comments without changing ordinary comments or string literals."""
    chars = list(source)
    i = 0
    length = len(source)

    while i < length:
        raw_end = _skip_rust_raw_string(source, i)
        if raw_end is not None:
            i = raw_end
            continue

        ch = source[i]
        if ch == '"':
            i = _skip_quoted_literal(source, i, triple_quotes=set())
            continue
        if ch == "'":
            char_end = _skip_rust_char_literal(source, i)
            if char_end is not None:
                i = char_end
                continue

        if source.startswith("//", i):
            start = i
            is_doc_comment = (
                source.startswith("///", start) and not source.startswith("////", start)
            ) or source.startswith("//!", start)
            while i < length and source[i] not in "\r\n":
                i += 1
            if is_doc_comment:
                for index in range(start, i):
                    chars[index] = "\t" if source[index] == "\t" else " "
            continue

        if source.startswith("/*", i):
            start = i
            is_doc_comment = (
                source.startswith("/**", start) and not source.startswith("/***", start)
            ) or source.startswith("/*!", start)
            i += 2
            depth = 1
            while i < length and depth:
                if source.startswith("/*", i):
                    depth += 1
                    i += 2
                elif source.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            if is_doc_comment:
                for index in range(start, i):
                    if chars[index] not in "\r\n":
                        chars[index] = "\t" if chars[index] == "\t" else " "
            continue
        i += 1

    return "".join(chars)


def _skip_quoted_literal(
    source: str,
    quote_index: int,
    *,
    triple_quotes: set[str],
    raw: bool = False,
    raw_triple_quotes: bool = False,
    backtick_mode: str | None = None,
) -> int:
    """Return index after a quoted literal, or len(source) if unterminated."""
    quote = source[quote_index]
    if quote == "`":
        i = quote_index + 1
        while i < len(source):
            if backtick_mode == "escaped" and source[i] == "\\":
                i += 2
                continue
            if source[i] == "`":
                return i + 1
            i += 1
        return len(source)

    is_triple = quote in triple_quotes and source.startswith(quote * 3, quote_index)
    delimiter = quote * (3 if is_triple else 1)
    i = quote_index + len(delimiter)
    while i < len(source):
        if source.startswith(delimiter, i):
            return i + len(delimiter)
        if not raw and not (is_triple and raw_triple_quotes) and source[i] == "\\":
            i += 2
            continue
        i += 1
    return len(source)


def _skip_cpp_raw_string(source: str, start: int) -> int | None:
    """Skip a C++ raw string literal beginning at a valid R-prefixed token."""
    prefixes = ('u8R"', 'uR"', 'UR"', 'LR"', 'R"')
    prefix = next((item for item in prefixes if source.startswith(item, start)), None)
    if prefix is None or (
        start > 0 and (source[start - 1].isalnum() or source[start - 1] == "_")
    ):
        return None
    quote_index = start + len(prefix) - 1
    open_paren = source.find("(", quote_index + 1, min(len(source), quote_index + 19))
    if open_paren == -1:
        return None
    delimiter = source[quote_index + 1 : open_paren]
    if len(delimiter) > 16 or any(ch.isspace() or ch in "()\\" for ch in delimiter):
        return None
    terminator = ")" + delimiter + '"'
    close = source.find(terminator, open_paren + 1)
    return len(source) if close == -1 else close + len(terminator)


def remove_c_style_comments(
    source: str,
    options: dict[str, object],
    *,
    doc_comments_only: bool = False,
) -> str:
    """Remove comments outside quoted literals, optionally doc-style comments only."""
    chars = list(source)
    i = 0
    length = len(source)
    nested_block_comments = bool(options["nested_block_comments"])
    triple_quotes = options["triple_quotes"]
    raw_prefixes = bool(options["raw_prefixes"])
    backtick_mode = options["backtick_mode"]
    raw_triple_quotes = bool(options.get("raw_triple_quotes", False))

    while i < length:
        ch = source[i]
        if bool(options.get("cpp_raw_strings", False)):
            raw_end = _skip_cpp_raw_string(source, i)
            if raw_end is not None:
                i = raw_end
                continue
        if (
            raw_prefixes
            and ch in "rR"
            and i + 1 < length
            and source[i + 1] in "'\""
            and (i == 0 or not (source[i - 1].isalnum() or source[i - 1] == "_"))
        ):
            i = _skip_quoted_literal(
                source,
                i + 1,
                triple_quotes=triple_quotes,
                raw=True,  # type: ignore[arg-type]
                raw_triple_quotes=raw_triple_quotes,
            )
            continue
        if ch in "'\"`":
            i = _skip_quoted_literal(
                source,
                i,
                triple_quotes=triple_quotes,  # type: ignore[arg-type]
                raw=False,
                raw_triple_quotes=raw_triple_quotes,
                backtick_mode=backtick_mode if ch == "`" else None,  # type: ignore[arg-type]
            )
            continue
        if source.startswith("//", i):
            start = i
            is_doc_comment = source.startswith(("///", "//!"), start)
            while i < length and source[i] not in "\r\n":
                i += 1
            if not doc_comments_only or is_doc_comment:
                for index in range(start, i):
                    chars[index] = "\t" if source[index] == "\t" else " "
            continue
        if source.startswith("/*", i):
            start = i
            is_doc_comment = source.startswith(("/**", "/*!"), start)
            i += 2
            depth = 1
            while i < length and depth:
                if nested_block_comments and source.startswith("/*", i):
                    depth += 1
                    i += 2
                elif source.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            if not doc_comments_only or is_doc_comment:
                for index in range(start, i):
                    if chars[index] not in "\r\n":
                        chars[index] = "\t" if chars[index] == "\t" else " "
            continue
        i += 1
    return "".join(chars)


def remove_comments_for_file(source: str, path: Path) -> str:
    """Select a comment-removal implementation from the file extension."""
    extension = path.suffix.lower()
    if extension in PYTHON_EXTENSIONS:
        return remove_python_comments(source)
    if extension in KOTLIN_EXTENSIONS:
        return remove_kotlin_comments(source, path)
    options = C_STYLE_COMMENT_OPTIONS.get(extension)
    if options is not None:
        return remove_c_style_comments(source, options)
    supported = sorted(
        PYTHON_EXTENSIONS | KOTLIN_EXTENSIONS | set(C_STYLE_COMMENT_OPTIONS)
    )
    raise ValueError(
        f"no comment-removal rules for {path} (extension {extension or '<none>'}); "
        f"supported extensions: {', '.join(supported)}"
    )


def remove_docs_for_file(source: str, path: Path) -> str:
    """Remove Python docstrings and explicit documentation-comment forms."""
    extension = path.suffix.lower()
    if extension in PYTHON_EXTENSIONS:
        return remove_python_docstrings(source)
    if extension in KOTLIN_EXTENSIONS:
        return remove_kotlin_doc_comments(source, path)
    if extension == ".rs":
        return remove_rust_doc_comments(source)
    options = C_STYLE_COMMENT_OPTIONS.get(extension)
    if options is not None and extension != ".go":
        return remove_c_style_comments(source, options, doc_comments_only=True)
    if extension == ".go":
        raise ValueError(
            f"documentation-only removal is not implemented for {path}: "
            "Go uses ordinary // comments for documentation, so identifying them "
            "requires syntax-aware declaration analysis"
        )
    raise ValueError(
        f"documentation removal does not support extension {extension or '<none>'}: {path}"
    )


def validate_comment_support(files: Iterable[SourceFile]) -> None:
    """Fail early if any file lacks a remover; initialise Kotlin dependencies."""
    files = list(files)
    supported = PYTHON_EXTENSIONS | KOTLIN_EXTENSIONS | set(C_STYLE_COMMENT_OPTIONS)
    unsupported = sorted(
        {item.extension for item in files if item.extension not in supported}
    )
    if unsupported:
        raise ValueError(
            "comment removal does not support extension(s): "
            + ", ".join(ext or "<none>" for ext in unsupported)
        )
    if any(item.extension in KOTLIN_EXTENSIONS for item in files):
        get_kotlin_parser()


def validate_doc_support(files: Iterable[SourceFile]) -> None:
    """Fail early if documentation stripping is unsupported for a selected file."""
    files = list(files)
    supported = (
        PYTHON_EXTENSIONS
        | KOTLIN_EXTENSIONS
        | (set(C_STYLE_COMMENT_OPTIONS) - {".go"})
        | {".rs"}
    )
    unsupported = sorted(
        {item.extension for item in files if item.extension not in supported}
    )
    if unsupported:
        raise ValueError(
            "documentation removal does not support extension(s): "
            + ", ".join(ext or "<none>" for ext in unsupported)
        )
    if any(item.extension in KOTLIN_EXTENSIONS for item in files):
        get_kotlin_parser()


def _reject_json_constant(value: str) -> None:
    """Reject JavaScript-style NaN/Infinity values accepted by Python's decoder."""
    raise ValueError(f"non-standard JSON constant: {value}")


def compact_json(source: str, path: Path | None = None) -> str:
    """Remove JSON insignificant whitespace without reserializing values.

    Parsing first validates strict JSON. The character pass then removes only
    whitespace outside strings, preserving number lexemes, key order, duplicate
    keys, escape spelling, and all string contents.
    """
    try:
        json.loads(
            source,
            parse_int=str,
            parse_float=str,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as exc:
        location = f" in {path}" if path is not None else ""
        raise ValueError(
            f"invalid JSON{location} at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    except ValueError as exc:
        location = f" in {path}" if path is not None else ""
        raise ValueError(f"invalid JSON{location}: {exc}") from exc

    output: list[str] = []
    in_string = False
    escaped = False
    for char in source:
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            output.append(char)
        elif char not in " \t\r\n":
            output.append(char)

    # Keep one original terminal newline (if present) for friendly text-file
    # behavior and clean separation from the following dump marker.
    if source.endswith("\r\n"):
        output.append("\r\n")
    elif source.endswith("\n"):
        output.append("\n")
    elif source.endswith("\r"):
        output.append("\r")
    return "".join(output)


def prepare_content(
    source: str,
    path: Path,
    *,
    remove_comments: bool = False,
    remove_docs: bool = False,
    compact_json_files: bool = False,
    strip_leading_whitespace: bool = False,
) -> str:
    """Apply content transformations without coupling them to an argument parser."""
    if remove_docs:
        source = remove_docs_for_file(source, path)
    if remove_comments:
        source = remove_comments_for_file(source, path)
    if compact_json_files and path.suffix.lower() == ".json":
        source = compact_json(source, path)
    if strip_leading_whitespace and not strip_is_unsafe(path):
        source = LEADING_WHITESPACE_RE.sub("", source)
    return source


def display_path(source_file: SourceFile, absolute_paths: bool = False) -> str:
    return str(source_file.path) if absolute_paths else source_file.relative_path


def _is_output_file(source_file: SourceFile, output_path: Path) -> bool:
    try:
        return source_file.path.resolve() == output_path.resolve()
    except OSError:
        return os.path.abspath(source_file.path) == os.path.abspath(output_path)


def write_dump_stream(
    files: Iterable[SourceFile],
    stream: TextIO,
    *,
    absolute_paths: bool = False,
    file_format: str = DEFAULT_FILE_FORMAT,
    remove_comments: bool = False,
    remove_docs: bool = False,
    compact_json_files: bool = False,
    strip_leading_whitespace: bool = False,
    output_path: Path | None = None,
    on_error: Callable[[DumpError], None] | None = None,
) -> DumpResult:
    """Write selected files to a stream; collect non-fatal per-file errors.

    Transform errors (invalid JSON when --compact-json, unparsable Python
    when --remove-comments) are recorded as ``kind="transform"`` and the
    file is written **unmodified**. Read errors skip the file.
    """
    written = 0
    errors: list[DumpError] = []

    def report(err: DumpError) -> None:
        errors.append(err)
        if on_error is not None:
            on_error(err)

    for source_file in files:
        if output_path is not None and _is_output_file(source_file, output_path):
            continue
        try:
            with source_file.path.open("r", encoding="utf-8", newline="") as source:
                original = source.read()
        except (OSError, UnicodeError) as exc:
            report(
                DumpError(
                    path=source_file.path,
                    message=f"cannot read source file: {exc}",
                    kind="read",
                )
            )
            continue

        try:
            content = prepare_content(
                original,
                source_file.path,
                remove_comments=remove_comments,
                remove_docs=remove_docs,
                compact_json_files=compact_json_files,
                strip_leading_whitespace=strip_leading_whitespace,
            )
        except ValueError as exc:
            report(
                DumpError(
                    path=source_file.path,
                    message=f"transform skipped: {exc}",
                    kind="transform",
                )
            )
            content = original

        display = display_path(source_file, absolute_paths)
        opener, closer = make_markers(display, content)
        stream.write(
            file_format.format(
                path=display,
                content=content,
                end="END-SIFT",
                opener=opener,
                closer=closer,
            )
        )
        written += 1

    return DumpResult(written=written, errors=tuple(errors))


def write_dump_atomic(
    files: Iterable[SourceFile],
    output_path: Path,
    *,
    absolute_paths: bool = False,
    file_format: str = DEFAULT_FILE_FORMAT,
    remove_comments: bool = False,
    remove_docs: bool = False,
    compact_json_files: bool = False,
    strip_leading_whitespace: bool = False,
    on_error: Callable[[DumpError], None] | None = None,
) -> DumpResult:
    output_path = output_path.expanduser().absolute()
    if output_path.exists() and output_path.is_dir():
        raise ValueError(f"output path is a directory: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = output.name
            result = write_dump_stream(
                files,
                output,
                absolute_paths=absolute_paths,
                file_format=file_format,
                remove_comments=remove_comments,
                remove_docs=remove_docs,
                compact_json_files=compact_json_files,
                strip_leading_whitespace=strip_leading_whitespace,
                output_path=output_path,
                on_error=on_error,
            )
        os.replace(temporary_path, output_path)
        return result
    except Exception:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
        raise
