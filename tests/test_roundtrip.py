"""End-to-end: scan → write dump → restore → byte-identical files."""

from __future__ import annotations

from pathlib import Path

from sift.engine import DumpOptions, ScanOptions, SiftEngine


def test_full_roundtrip(sample_tree: Path, tmp_path: Path, isolated_home: Path) -> None:
    out = tmp_path / "d.txt"
    target = tmp_path / "restored"
    engine = SiftEngine([sample_tree], use_cache=False)
    files = engine.scan(ScanOptions(include_patterns=["*"]))

    result = engine.write_dump(files, out, DumpOptions())
    assert result.written == len(files)
    assert result.errors == ()

    n = SiftEngine.restore(out, target)
    assert n == result.written
    for sf in files:
        original = sf.path.read_bytes()
        restored = (target / sf.relative_path).read_bytes()
        assert restored == original


def test_self_dump_with_embedded_marker(
    sample_tree: Path, tmp_path: Path, isolated_home: Path,
) -> None:
    tricky = sample_tree / "tricky.py"
    tricky.write_text('S = "<<<END-SIFT>>>"\n', encoding="utf-8")
    out = tmp_path / "d.txt"
    target = tmp_path / "restored"

    engine = SiftEngine([sample_tree], use_cache=False)
    files = engine.scan(ScanOptions(include_patterns=["*.py"]))
    engine.write_dump(files, out, DumpOptions())

    text = out.read_text(encoding="utf-8")
    assert "<<<END-SIFT:" in text  # nonced form used

    SiftEngine.restore(out, target)
    assert (target / "tricky.py").read_text(encoding="utf-8") == tricky.read_text(encoding="utf-8")
