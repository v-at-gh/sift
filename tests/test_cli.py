from __future__ import annotations

from pathlib import Path

import pytest

from sift import cli


def test_basic_dump(sample_tree: Path, tmp_path: Path, isolated_home: Path) -> None:
    out = tmp_path / "d.txt"
    rc = cli.main([str(sample_tree), "-o", str(out), "--include", "*.py"])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert text.count("<<<SIFT:") >= 4  # a.py, b.py, sub/c.py, ignored/d.py


def test_missing_output_raises(sample_tree: Path, isolated_home: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([str(sample_tree)])
    assert exc.value.code == 2


def test_stdout_and_output_conflict(
    sample_tree: Path, tmp_path: Path, isolated_home: Path,
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([str(sample_tree), "-o", str(tmp_path / "x"), "--stdout"])
    assert exc.value.code == 2


def test_force_requires_restore(
    sample_tree: Path, tmp_path: Path, isolated_home: Path,
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([str(sample_tree), "-o", str(tmp_path / "x"), "--force"])
    assert exc.value.code == 2


def test_bad_file_format_raises_before_scanning(
    sample_tree: Path, tmp_path: Path, isolated_home: Path,
) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main([str(sample_tree), "-o", str(tmp_path / "x"), "--file-format", "{bad}"])
    assert exc.value.code == 2


def test_dry_run_writes_nothing(
    sample_tree: Path, tmp_path: Path, isolated_home: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "d.txt"
    rc = cli.main([str(sample_tree), "--dry-run", "--include", "*.py"])
    assert rc == 0
    assert not out.exists()
    assert "Dry run:" in capsys.readouterr().err


def test_restore_roundtrip(sample_tree: Path, tmp_path: Path, isolated_home: Path) -> None:
    out = tmp_path / "d.txt"
    target = tmp_path / "restored"
    cli.main([str(sample_tree), "-o", str(out), "--include", "*.py"])
    rc = cli.main(["--restore", str(out), str(target)])
    assert rc == 0
    assert (target / "a.py").is_file()


def test_restore_refuses_without_force(
    sample_tree: Path, tmp_path: Path, isolated_home: Path,
) -> None:
    out = tmp_path / "d.txt"
    target = tmp_path / "restored"
    cli.main([str(sample_tree), "-o", str(out), "--include", "*.py"])
    cli.main(["--restore", str(out), str(target)])
    rc = cli.main(["--restore", str(out), str(target)])
    assert rc == 1
    rc = cli.main(["--force", "--restore", str(out), str(target)])
    assert rc == 0


def test_restore_conflicts_with_output(
    sample_tree: Path, tmp_path: Path, isolated_home: Path,
) -> None:
    out = tmp_path / "d.txt"
    cli.main([str(sample_tree), "-o", str(out), "--include", "*.py"])
    with pytest.raises(SystemExit) as exc:
        cli.main(["--restore", str(out), str(tmp_path / "t"), "-o", str(tmp_path / "x")])
    assert exc.value.code == 2
