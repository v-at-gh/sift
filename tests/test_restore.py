from __future__ import annotations

from pathlib import Path

import pytest

from sift.markers import make_markers
from sift.restore import restore_dump


def _write_dump(path: Path, entries: dict[str, str]) -> None:
    text = ""
    for rel, content in entries.items():
        opener, closer = make_markers(rel, content)
        text += f"{opener}\n{content}{closer}\n"
    path.write_text(text, encoding="utf-8")


def test_roundtrip_basic(tmp_path: Path) -> None:
    dump = tmp_path / "d.txt"
    _write_dump(dump, {"a.py": "print('a')\n", "sub/b.py": "print('b')\n"})
    target = tmp_path / "out"
    n = restore_dump(dump, target)
    assert n == 2
    assert (target / "a.py").read_text(encoding="utf-8") == "print('a')\n"
    assert (target / "sub/b.py").read_text(encoding="utf-8") == "print('b')\n"


def test_path_traversal_rejected(tmp_path: Path) -> None:
    dump = tmp_path / "evil.txt"
    dump.write_text(
        "<<<SIFT:../escape.py>>>\nx\n<<<END-SIFT>>>\n",
        encoding="utf-8",
    )
    target = tmp_path / "t"
    target.mkdir()
    with pytest.raises(ValueError, match="escapes target root"):
        restore_dump(dump, target)
    assert not (target.parent / "escape.py").exists()


def test_refuses_overwrite_without_force(tmp_path: Path) -> None:
    dump = tmp_path / "d.txt"
    _write_dump(dump, {"a.py": "new\n"})
    target = tmp_path / "out"
    target.mkdir()
    (target / "a.py").write_text("old\n", encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to overwrite"):
        restore_dump(dump, target)
    assert (target / "a.py").read_text(encoding="utf-8") == "old\n"


def test_force_overwrites(tmp_path: Path) -> None:
    dump = tmp_path / "d.txt"
    _write_dump(dump, {"a.py": "new\n"})
    target = tmp_path / "out"
    target.mkdir()
    (target / "a.py").write_text("old\n", encoding="utf-8")
    restore_dump(dump, target, overwrite=True)
    assert (target / "a.py").read_text(encoding="utf-8") == "new\n"


def test_empty_dump(tmp_path: Path) -> None:
    dump = tmp_path / "d.txt"
    dump.write_text("", encoding="utf-8")
    target = tmp_path / "out"
    assert restore_dump(dump, target) == 0


def test_missing_dump_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a file"):
        restore_dump(tmp_path / "nope.txt", tmp_path / "t")
