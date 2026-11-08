from __future__ import annotations

from pathlib import Path

import pytest

from sift.core import prepare_content, strip_is_unsafe


def test_python_is_unsafe(tmp_path: Path) -> None:
    assert strip_is_unsafe(tmp_path / "a.py")
    assert strip_is_unsafe(tmp_path / "a.pyi")
    assert strip_is_unsafe(tmp_path / "a.pyw")


def test_yaml_is_unsafe(tmp_path: Path) -> None:
    assert strip_is_unsafe(tmp_path / "a.yaml")
    assert strip_is_unsafe(tmp_path / "a.yml")


def test_makefile_is_unsafe(tmp_path: Path) -> None:
    assert strip_is_unsafe(tmp_path / "Makefile")
    assert strip_is_unsafe(tmp_path / "GNUmakefile")
    assert strip_is_unsafe(tmp_path / "a.mk")


def test_markdown_is_unsafe(tmp_path: Path) -> None:
    assert strip_is_unsafe(tmp_path / "a.md")
    assert strip_is_unsafe(tmp_path / "a.markdown")
    assert strip_is_unsafe(tmp_path / "a.rst")


def test_js_is_safe(tmp_path: Path) -> None:
    assert not strip_is_unsafe(tmp_path / "a.js")
    assert not strip_is_unsafe(tmp_path / "a.ts")
    assert not strip_is_unsafe(tmp_path / "a.go")


def test_python_content_unchanged_under_strip(tmp_path: Path) -> None:
    src = "def f():\n    return 1\n"
    path = tmp_path / "a.py"
    assert prepare_content(src, path, strip_leading_whitespace=True) == src


def test_yaml_content_unchanged_under_strip(tmp_path: Path) -> None:
    src = "root:\n  child: 1\n"
    path = tmp_path / "a.yaml"
    assert prepare_content(src, path, strip_leading_whitespace=True) == src


def test_js_content_is_stripped(tmp_path: Path) -> None:
    src = "function f() {\n    return 1;\n}\n"
    path = tmp_path / "a.js"
    assert prepare_content(src, path, strip_leading_whitespace=True) == (
        "function f() {\nreturn 1;\n}\n"
    )
