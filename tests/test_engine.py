from __future__ import annotations

from pathlib import Path

from sift.engine import ScanOptions, SiftEngine


def test_engine_integrates_view_and_selection(
    sample_tree: Path,
    isolated_home: Path,
) -> None:
    engine = SiftEngine([sample_tree], use_cache=False)
    engine.scan(ScanOptions(include_patterns=["*"]))
    assert engine.visible_files() == engine.files

    engine.set_view_patterns("!*.txt")
    assert all(f.extension != ".txt" for f in engine.visible_files())

    n = engine.apply_selection("replace", "*.py")
    assert n == 4  # a, b, sub/c, ignored/d
    assert len(engine.selected_files()) == 4
    assert engine.count_selection_matches("tests/**") == 0


def test_engine_view_after_scan_required() -> None:
    engine = SiftEngine([], use_cache=False)
    try:
        engine.visible_files()
    except Exception:
        pass
    # visible_files on unscanned engine returns [] (defensive)
    assert engine.visible_files() == []


def test_set_file_selected_invalidates_dir_counts(
    sample_tree: Path,
    isolated_home: Path,
) -> None:
    engine = SiftEngine([sample_tree], use_cache=False)
    engine.scan(ScanOptions(include_patterns=["*.py"]))
    root = sample_tree
    before = engine.dir_counts(root)
    engine.set_file_selected(engine.visible_files()[0], True)
    after = engine.dir_counts(root)
    assert after[1] == before[1] + 1


def test_dir_mtime_is_max_of_children(
    sample_tree: Path,
    isolated_home: Path,
) -> None:
    e = SiftEngine([sample_tree], use_cache=False)
    e.scan(ScanOptions(include_patterns=["*"]))
    root = sample_tree
    mtimes = [f.mtime_ns for f in e.visible_files() if f.root == root]
    assert e.dir_mtime(root) == max(mtimes)
