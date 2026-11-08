"""Pure formatting helpers for the TUI (no Textual imports)."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

MAX_PREVIEW_SIZE = 512 * 1024

SELECTION_NONE = "○"
SELECTION_PARTIAL = "◐"
SELECTION_FULL = "●"

_SELECTION_STYLES = ("dim", "", "bold")


def format_datetime(ns: int) -> str:
    if ns <= 0:
        return "—"
    try:
        return datetime.fromtimestamp(ns / 1_000_000_000).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return "—"


def selection_marker(selected: int, total: int) -> str:
    """Circle glyph for aggregate selection state."""
    if total == 0 or selected == 0:
        return SELECTION_NONE
    if selected == total:
        return SELECTION_FULL
    return SELECTION_PARTIAL


def file_marker(selected: bool) -> str:
    """Circle glyph for a single file (never partial)."""
    return SELECTION_FULL if selected else SELECTION_NONE


def selection_style(selected: int, total: int) -> str:
    """Rich style name: dim/normal/bold by selection intensity."""
    if total == 0 or selected == 0:
        return _SELECTION_STYLES[0]
    if selected == total:
        return _SELECTION_STYLES[2]
    return _SELECTION_STYLES[1]


def styled_selection_row(circle: str, label: str, style: str) -> Text:
    return Text(f"{circle} {label}", style=style or None)


def styled_extension_row(
    ext: str,
    *,
    enabled: bool,
    total: int,
    selected: int,
) -> tuple[Text, int]:
    """Row for the extensions pane; returns (Text, plain_width).

    When hidden (``enabled=False``), the row is dimmed and the circle is
    always ``○`` — matching the previous ``☐`` semantics but with the new
    glyph family. When visible, circle reflects aggregate selection and
    the label shows the ``(selected/total)`` suffix.
    """
    if not enabled:
        plain = f"{SELECTION_NONE} {ext or '(none)'}"
        return Text(plain, style="dim"), len(plain)
    circle = selection_marker(selected, total)
    if total:
        plain = f"{circle} {ext or '(none)'}  ({selected}/{total})"
    else:
        plain = f"{circle} {ext or '(none)'}"
    return Text(plain), len(plain)


def format_size(size: int, human: bool) -> str:
    """Right-aligned size for the Length column.

    Human mode is always 8 chars: ``'  64 B  '``, ``' 300 KiB'``.
    Exact mode is at least 14 chars; grows to 19 for sizes ≥ 1 TB
    (rare for source files, harmless for display: the column clips).
    """
    if not human:
        return f"{size:>12,} B"
    if size < 1024:
        return f"{size:>4} {'B':<3}"
    value = float(size)
    for unit in ("KiB", "MiB", "GiB", "TiB", "PiB"):
        value /= 1024
        if value < 1024 or unit == "PiB":
            num = f"{value:.1f}" if value < 10 else f"{value:.0f}"
            return f"{num:>4} {unit:<3}"
    return f"{value:>4.1f} PiB"  # unreachable
