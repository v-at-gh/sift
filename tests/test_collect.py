from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sift.core import collect_files


def test_empty_include_returns_everything(sample_tree: Path) -> None:
    files = collect_files([sample_tree], include_patterns=[])
    names = {f.relative_path for f in files}
    assert names == {
        "a.py",
        "b.py",
        "notes.txt",
        "sub/c.py",
        "ignored/d.py",
    }


def test_include_filters_by_extension(sample_tree: Path) -> None:
    files = collect_files([sample_tree], include_patterns=["*.py"])
    names = {f.relative_path for f in files}
    assert "notes.txt" not in names
    assert "a.py" in names and "sub/c.py" in names


def test_exclude_dir(sample_tree: Path) -> None:
    files = collect_files(
        [sample_tree],
        include_patterns=["*.py"],
        exclude_dir_patterns=["ignored"],
    )
    assert not any("ignored/" in f.relative_path for f in files)


def test_output_path_excluded(sample_tree: Path, tmp_path: Path) -> None:
    out = sample_tree / "dump.txt"
    files = collect_files(
        [sample_tree],
        output_path=out,
        include_patterns=["*"],
    )
    assert all(f.path != out for f in files)


def test_size_populated(tmp_path: Path) -> None:
    root = tmp_path / "src"
    root.mkdir()
    payload = b"hello world\n"
    (root / "a.py").write_bytes(payload)
    files = collect_files([root], include_patterns=["*.py"])
    assert len(files) == 1 and files[0].size == len(payload)


def test_relative_path_is_posix(sample_tree: Path) -> None:
    files = collect_files([sample_tree], include_patterns=["*"])
    assert all("\\" not in f.relative_path for f in files)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges")
def test_symlink_not_followed(tmp_path: Path) -> None:
    root = tmp_path / "src"
    root.mkdir()
    (root / "real.py").write_text("x", encoding="utf-8")
    external = tmp_path / "external"
    external.mkdir()
    (external / "leak.py").write_text("y", encoding="utf-8")
    (root / "link").symlink_to(external, target_is_directory=True)
    files = collect_files([root], include_patterns=["*"])
    assert "real.py" in {f.relative_path for f in files}
    assert not any("leak" in f.relative_path for f in files)


def test_metadata_populated(tmp_path: Path) -> None:
    root = tmp_path / "src"
    root.mkdir()
    (root / "a.py").write_bytes(b"hello")
    files = collect_files([root], include_patterns=["*.py"])
    assert files[0].mtime_ns > 0
    assert files[0].ctime_ns > 0
