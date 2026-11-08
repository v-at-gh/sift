from __future__ import annotations

from pathlib import Path

import pytest

from sift.core import SourceFile
from sift.filters import (
    SelectionModel,
    ViewQuery,
    filter_matches,
    parse_filter_expression,
)


def _sf(rel: str) -> SourceFile:
    root = Path("/repo")
    return SourceFile(path=root / rel, root=root, relative_path=rel)


# --- parse_filter_expression ---------------------------------------------

def test_parse_empty() -> None:
    assert parse_filter_expression("") == ([], [])
    assert parse_filter_expression("  ,  ") == ([], [])


def test_parse_includes() -> None:
    assert parse_filter_expression("*.py, *.kt") == (["*.py", "*.kt"], [])


def test_parse_mixed() -> None:
    assert parse_filter_expression("*.py,*.json,!tests/**") == (
        ["*.py", "*.json"], ["tests/**"],
    )


def test_parse_excludes_only() -> None:
    assert parse_filter_expression("!*.py") == ([], ["*.py"])


def test_parse_ignores_empty_after_bang() -> None:
    assert parse_filter_expression("!,!*.py") == ([], ["*.py"])


# --- filter_matches -------------------------------------------------------

def test_no_patterns_matches_everything() -> None:
    assert filter_matches(_sf("src/a.py"), [], [])


def test_include_basename() -> None:
    assert filter_matches(_sf("src/a.py"), ["*.py"], [])
    assert not filter_matches(_sf("src/a.kt"), ["*.py"], [])


def test_include_relative_path() -> None:
    assert filter_matches(_sf("src/a.py"), ["src/**/*.py"], [])       # **/ = zero segs
    assert filter_matches(_sf("src/a/b.py"), ["src/**/*.py"], [])
    assert not filter_matches(_sf("tests/a.py"), ["src/**/*.py"], [])


def test_doublestar_end() -> None:
    assert filter_matches(_sf("tests/a.py"), ["tests/**"], [])
    assert filter_matches(_sf("tests/sub/b.py"), ["tests/**"], [])


def test_doublestar_inside_segment_collapses_to_star() -> None:
    assert filter_matches(_sf("aXXb.py"), ["a**b.py"], [])
    assert not filter_matches(_sf("a/x/b.py"), ["a**b.py"], [])


def test_exclude_overrides_include() -> None:
    assert not filter_matches(_sf("tests/a.py"), ["*.py"], ["tests/**"])
    assert filter_matches(_sf("src/a.py"), ["*.py"], ["tests/**"])


def test_exclude_only() -> None:
    assert not filter_matches(_sf("tests/a.py"), [], ["tests/**"])
    assert filter_matches(_sf("src/a.py"), [], ["tests/**"])


def test_question_mark() -> None:
    assert filter_matches(_sf("a.py"), ["?.py"], [])
    assert not filter_matches(_sf("ab.py"), ["?.py"], [])


def test_character_class() -> None:
    assert filter_matches(_sf("a.py"), ["[abc].py"], [])
    assert not filter_matches(_sf("d.py"), ["[abc].py"], [])
    assert filter_matches(_sf("d.py"), ["[!abc].py"], [])


# --- ViewQuery ------------------------------------------------------------

def test_view_all_extensions_visible_by_default() -> None:
    files = [_sf("a.py"), _sf("b.kt"), _sf("c.txt")]
    view = ViewQuery.from_files(files)
    assert view.visible(files) == files


def test_view_hide_extension() -> None:
    files = [_sf("a.py"), _sf("b.kt")]
    view = ViewQuery.from_files(files)
    view.set_extension_enabled(".py", False)
    assert [f.relative_path for f in view.visible(files)] == ["b.kt"]


def test_view_pattern_excludes() -> None:
    files = [_sf("src/a.py"), _sf("tests/a.py")]
    view = ViewQuery.from_files(files)
    view.set_patterns("!tests/**")
    assert [f.relative_path for f in view.visible(files)] == ["src/a.py"]


def test_view_combines_extension_and_pattern() -> None:
    files = [_sf("src/a.py"), _sf("src/b.kt"), _sf("tests/a.py")]
    view = ViewQuery.from_files(files)
    view.set_extension_enabled(".kt", False)
    view.set_patterns("!tests/**")
    assert [f.relative_path for f in view.visible(files)] == ["src/a.py"]


# --- SelectionModel -------------------------------------------------------

def test_selection_starts_empty() -> None:
    assert SelectionModel([_sf("a.py")]).selected_files() == []


def test_toggle_file() -> None:
    files = [_sf("a.py"), _sf("b.py")]
    model = SelectionModel(files)
    model.toggle_file(files[0])
    assert model.selected_files() == [files[0]]
    model.toggle_file(files[0])
    assert model.selected_files() == []


def test_apply_add() -> None:
    files = [_sf("a.py"), _sf("b.py"), _sf("c.kt")]
    model = SelectionModel(files)
    assert model.apply_pattern("add", "*.py") == 2
    assert {f.relative_path for f in model.selected_files()} == {"a.py", "b.py"}
    model.apply_pattern("add", "*.kt")
    assert {f.relative_path for f in model.selected_files()} == {"a.py", "b.py", "c.kt"}


def test_apply_replace() -> None:
    files = [_sf("a.py"), _sf("c.kt")]
    model = SelectionModel(files)
    model.apply_pattern("add", "*.py")
    model.apply_pattern("replace", "*.kt")
    assert {f.relative_path for f in model.selected_files()} == {"c.kt"}


def test_apply_remove() -> None:
    files = [_sf("a.py"), _sf("tests/x.py"), _sf("b.py")]
    model = SelectionModel(files)
    model.apply_pattern("add", "*.py")
    assert model.apply_pattern("remove", "tests/**") == 1
    assert {f.relative_path for f in model.selected_files()} == {"a.py", "b.py"}


def test_apply_empty_expression_is_noop() -> None:
    model = SelectionModel([_sf("a.py")])
    assert model.apply_pattern("add", "") == 0
    assert model.apply_pattern("replace", "") == 0
    assert model.apply_pattern("remove", "") == 0
    assert model.selected_files() == []


def test_apply_unknown_mode_raises() -> None:
    with pytest.raises(ValueError, match="unknown apply mode"):
        SelectionModel([_sf("a.py")]).apply_pattern("frobnicate", "*.py")


def test_count_matches() -> None:
    files = [_sf("a.py"), _sf("b.py"), _sf("c.kt")]
    model = SelectionModel(files)
    assert model.count_matches("*.py") == 2
    assert model.count_matches("") == 0


def test_selection_state() -> None:
    files = [_sf("a.py"), _sf("b.py")]
    model = SelectionModel(files)
    assert model.selection_state(files) == "none"
    model.toggle_file(files[0])
    assert model.selection_state(files) == "partial"
    model.toggle_file(files[1])
    assert model.selection_state(files) == "all"
    assert model.selection_state([]) == "none"


# --- spec scenario: view and selection are independent -------------------

def test_hiding_does_not_deselect() -> None:
    """Spec: 'Hiding a file from view must not deselect it.'"""
    files = [_sf(f"src/f{i}.py") for i in range(5)]
    files += [_sf(f"tests/f{i}.py") for i in range(5)]

    model = SelectionModel(files)
    view = ViewQuery.from_files(files)

    model.apply_pattern("replace", "*.py")
    view.set_patterns("!tests/**")

    assert len(model.selected_files()) == 10
    assert len(view.visible(files)) == 5


def test_selection_filter_ignores_visibility() -> None:
    """Selection filter applies to the whole index, not the visible subset."""
    files = [_sf(f"src/f{i}.py") for i in range(3)]
    files += [_sf(f"tests/f{i}.py") for i in range(3)]

    view = ViewQuery.from_files(files)
    view.set_patterns("src/**")
    model = SelectionModel(files)

    assert model.apply_pattern("replace", "*.py") == 6
    assert len(model.selected_files()) == 6
    assert len(view.visible(files)) == 3
