from __future__ import annotations

import pytest

from sift.tui.format import (
    SELECTION_FULL,
    SELECTION_NONE,
    SELECTION_PARTIAL,
    file_marker,
    format_size,
    format_datetime,
    selection_marker,
    selection_style,
    styled_extension_row,
)


@pytest.mark.parametrize(
    "selected,total,expected",
    [
        (0, 0, SELECTION_NONE),
        (0, 10, SELECTION_NONE),
        (1, 1, SELECTION_FULL),
        (10, 10, SELECTION_FULL),
        (1, 10, SELECTION_PARTIAL),
        (9, 10, SELECTION_PARTIAL),
    ],
)
def test_selection_marker(selected, total, expected):
    assert selection_marker(selected, total) == expected


@pytest.mark.parametrize(
    "selected,total,expected_style",
    [
        (0, 0, "dim"),
        (0, 10, "dim"),
        (1, 10, ""),
        (10, 10, "bold"),
    ],
)
def test_selection_style(selected, total, expected_style):
    assert selection_style(selected, total) == expected_style


def test_file_marker():
    assert file_marker(True) == SELECTION_FULL
    assert file_marker(False) == SELECTION_NONE


def test_styled_extension_row_visible_partial():
    text, width = styled_extension_row(".py", enabled=True, total=10, selected=3)
    assert text.plain == "◐ .py  (3/10)"
    assert width == len(text.plain)


def test_styled_extension_row_hidden_has_empty_circle():
    text, _ = styled_extension_row(".py", enabled=False, total=10, selected=10)
    assert text.plain == "○ .py"
    assert text.style == "dim"


@pytest.mark.parametrize(
    "size", [0, 1, 42, 999, 1023, 1024, 1025, 1_048_576, 10**10, 10**12]
)
def test_exact_has_minimum_width(size: int) -> None:
    result = format_size(size, human=False)
    assert len(result) >= 14
    assert result.endswith(" B")


@pytest.mark.parametrize(
    "size", [0, 1, 42, 999, 1023, 1024, 1025, 10 * 1024, 1024 * 1024, 10**10]
)
def test_human_width_is_exactly_8(size: int) -> None:
    result = format_size(size, human=True)
    assert len(result) == 8, f"{size} → {result!r} (len={len(result)})"


def test_human_uses_correct_unit() -> None:
    assert "B" in format_size(1023, human=True)
    assert "KiB" in format_size(1024, human=True)
    assert "MiB" in format_size(1024 * 1024, human=True)
    assert "GiB" in format_size(1024**3, human=True)


def test_exact_thousand_separator() -> None:
    assert "1,234" in format_size(1234, human=False)


def test_format_datetime_zero() -> None:
    assert format_datetime(0) == "—"


def test_format_datetime_valid() -> None:
    # 2025-01-15 12:34:56 UTC
    ns = 1_736_939_696_000_000_000
    result = format_datetime(ns)
    assert len(result) == 16
    assert result[4] == "-" and result[7] == "-"
    assert result[10] == " " and result[13] == ":"
