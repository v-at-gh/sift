from __future__ import annotations

from pathlib import Path

import pytest

from sift.config import ScanConfig, load_config, resolve_scan


def _write_user_config(home: Path, text: str) -> None:
    path = home / ".config" / "sift" / "siftrc.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_default_presets_is_none(isolated_home: Path) -> None:
    cfg = load_config()
    assert cfg.scan.presets is None
    inc, exc, dirs = resolve_scan(cfg.scan)
    assert inc == []
    assert dirs  # base preset applied


def test_explicit_empty_presets_disables_base(
    isolated_home: Path,
    tmp_path: Path,
) -> None:
    (tmp_path / ".sift.toml").write_text(
        "[scan]\npresets = []\n",
        encoding="utf-8",
    )
    cfg = load_config()
    assert cfg.scan.presets == []
    inc, exc, dirs = resolve_scan(cfg.scan)
    assert inc == [] and exc == [] and dirs == []


def test_project_inherits_user_when_key_absent(
    isolated_home: Path,
    tmp_path: Path,
) -> None:
    _write_user_config(isolated_home, '[scan]\ninclude = ["*.py"]\n')
    (tmp_path / ".sift.toml").write_text(
        '[scan]\npresets = ["base"]\n',
        encoding="utf-8",
    )
    cfg = load_config()
    assert cfg.scan.include == ["*.py"]
    assert cfg.scan.presets == ["base"]


def test_project_overrides_user(isolated_home: Path, tmp_path: Path) -> None:
    _write_user_config(isolated_home, '[scan]\ninclude = ["*.py"]\n')
    (tmp_path / ".sift.toml").write_text(
        '[scan]\ninclude = ["*.kt"]\n',
        encoding="utf-8",
    )
    cfg = load_config()
    assert cfg.scan.include == ["*.kt"]


def test_env_var_overrides_presets(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIFT_SCAN_PRESETS", "python,typescript")
    cfg = load_config()
    assert cfg.scan.presets == ["python", "typescript"]


def test_env_var_disables_cache(
    isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIFT_NO_CACHE", "1")
    assert load_config().cache.enabled is False


def test_unknown_preset_raises() -> None:
    with pytest.raises(ValueError, match="unknown preset"):
        resolve_scan(ScanConfig(presets=["nonexistent"]))


def test_include_overrides_preset_include() -> None:
    inc, _, _ = resolve_scan(
        ScanConfig(presets=["python"], include=["*.rs"]),
    )
    assert inc == ["*.rs"]


def test_include_add_appends_to_preset_include() -> None:
    inc, _, _ = resolve_scan(
        ScanConfig(presets=["python"], include_add=["*.pyi"]),
    )
    assert "*.py" in inc and "*.pyi" in inc


def test_apply_scan_cli_overrides_include() -> None:
    from sift.config import SiftConfig, apply_scan_cli_overrides

    cfg = SiftConfig()
    cfg.scan.presets = ["python"]
    cfg.scan.include_add = ["*.pyi"]
    apply_scan_cli_overrides(cfg, include=["*.rs"], exclude=None, exclude_dirs=None)
    assert cfg.scan.include == ["*.rs"]
    assert cfg.scan.include_add == []


def test_apply_scan_cli_overrides_none_is_noop() -> None:
    from sift.config import SiftConfig, apply_scan_cli_overrides

    cfg = SiftConfig()
    cfg.scan.include = ["*.py"]
    cfg.scan.exclude_dirs = [".git"]
    apply_scan_cli_overrides(cfg, include=None, exclude=None, exclude_dirs=None)
    assert cfg.scan.include == ["*.py"]
    assert cfg.scan.exclude_dirs == [".git"]


def test_apply_scan_cli_overrides_comma_splits() -> None:
    from sift.config import SiftConfig, apply_scan_cli_overrides

    cfg = SiftConfig()
    apply_scan_cli_overrides(
        cfg,
        include=["*.py,*.pyi"],
        exclude=None,
        exclude_dirs=None,
    )
    assert cfg.scan.include == ["*.py", "*.pyi"]
