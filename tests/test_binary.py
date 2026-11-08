from __future__ import annotations

from pathlib import Path

from sift.core import is_binary


def test_empty_file_is_not_binary(tmp_path: Path) -> None:
    path = tmp_path / "empty"
    path.write_bytes(b"")
    assert not is_binary(path)


def test_text_file_is_not_binary(tmp_path: Path) -> None:
    path = tmp_path / "a.py"
    path.write_text("print('hi')\n", encoding="utf-8")
    assert not is_binary(path)


def test_utf8_multibyte_text_is_not_binary(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("привет, 世界\n", encoding="utf-8")
    assert not is_binary(path)


def test_png_is_binary(tmp_path: Path) -> None:
    path = tmp_path / "img.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 100)
    assert is_binary(path)


def test_nul_after_probe_size_is_not_detected(tmp_path: Path) -> None:
    path = tmp_path / "weird"
    path.write_bytes(b"a" * 9000 + b"\x00")
    # Probe reads only first 8192 bytes; NUL at 9000 is out of reach.
    assert not is_binary(path)
    # Full read finds it:
    assert is_binary(path, probe_size=10000)


def test_missing_file_returns_false(tmp_path: Path) -> None:
    assert not is_binary(tmp_path / "nope")
