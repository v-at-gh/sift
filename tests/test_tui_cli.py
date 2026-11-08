from __future__ import annotations

import pytest

from sift.tui.cli import build_parser


def test_parser_no_flags() -> None:
    parser = build_parser()
    args = parser.parse_args([])
    assert args.directories == []
    assert args.include is None
    assert args.exclude is None
    assert args.exclude_dir is None


def test_parser_positional_and_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(["src", "--include", "*.py,*.pyi"])
    assert args.directories == ["src"]
    assert args.include == ["*.py,*.pyi"]


def test_parser_repeatable_include() -> None:
    parser = build_parser()
    args = parser.parse_args(["--include", "*.py", "--include", "*.pyi"])
    assert args.include == ["*.py", "*.pyi"]


def test_parser_repeatable_exclude_dir() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["--exclude-dir", ".venv", "--exclude-dir", "node_modules"]
    )
    assert args.exclude_dir == [".venv", "node_modules"]
