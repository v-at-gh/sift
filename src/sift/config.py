from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --- schema ---------------------------------------------------------------


@dataclass
class ScanConfig:
    roots: list[Path] | None = None
    presets: list[str] | None = None
    include: list[str] | None = None
    include_add: list[str] = field(default_factory=list)
    exclude: list[str] | None = None
    exclude_add: list[str] = field(default_factory=list)
    exclude_dirs: list[str] | None = None
    exclude_dirs_add: list[str] = field(default_factory=list)


@dataclass
class DumpConfig:
    file_format: str = "{opener}\n{content}{closer}\n"
    absolute_paths: bool = False
    remove_comments: bool = False
    remove_docs: bool = False
    compact_json: bool = False
    strip_leading_whitespace: bool = False


@dataclass
class CacheConfig:
    enabled: bool = True
    path: Path | None = None


@dataclass
class RestoreConfig:
    force: bool = False


@dataclass
class KeysConfig:
    toggle: str = "x"
    toggle_visibility: str = "X"
    toggle_extensions: str = "e"
    toggle_actions: str = "a"
    toggle_units: str = "u"
    focus_view_filter: str = "f"
    focus_selection_filter: str = "s"
    next_view: str = "ctrl+tab"
    show_tree: str = "1"
    show_table: str = "2"
    show_preview: str = "3"
    show_log: str = "4"
    open_preview: str = "o"
    down_vim: str = "j"
    up_vim: str = "k"
    down_emacs: str = "ctrl+n"
    up_emacs: str = "ctrl+p"
    tree_left: str = "h"
    tree_right: str = "l"
    tree_collapse_all: str = "H"
    preview_wrap: str = "w"
    quit: str = "q"


@dataclass
class SiftConfig:
    scan: ScanConfig = field(default_factory=ScanConfig)
    dump: DumpConfig = field(default_factory=DumpConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    restore: RestoreConfig = field(default_factory=RestoreConfig)
    keys: KeysConfig = field(default_factory=KeysConfig)


# --- preset resolution ----------------------------------------------------


def resolve_scan(scan: ScanConfig) -> tuple[list[str], list[str], list[str]]:
    from .presets import PRESETS

    names = scan.presets if scan.presets is not None else ["base"]
    preset_include, preset_exclude, preset_dirs = [], [], []
    for name in names:
        if name not in PRESETS:
            raise ValueError(f"unknown preset: {name!r}")
        p = PRESETS[name]
        preset_include.extend(p.get("include", []))
        preset_exclude.extend(p.get("exclude", []))
        preset_dirs.extend(p.get("exclude_dirs", []))
    include = scan.include if scan.include is not None else preset_include
    exclude = scan.exclude if scan.exclude is not None else preset_exclude
    exclude_dirs = scan.exclude_dirs if scan.exclude_dirs is not None else preset_dirs
    return (
        list(include) + list(scan.include_add),
        list(exclude) + list(scan.exclude_add),
        list(exclude_dirs) + list(scan.exclude_dirs_add),
    )


# --- loading / cascade ----------------------------------------------------


def _user_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "sift" / "siftrc.toml"


def _find_project_config(start: Path) -> Path | None:
    for candidate in [start, *start.parents]:
        path = candidate / ".sift.toml"
        if path.is_file():
            return path
    return None


def _parse_scan(section: dict[str, Any]) -> ScanConfig:
    raw_roots = section.get("roots")
    return ScanConfig(
        roots=(
            [Path(p).expanduser() for p in raw_roots] if raw_roots is not None else None
        ),
        presets=section.get("presets"),  # None iff absent
        include=section.get("include"),
        include_add=section.get("include_add", []),
        exclude=section.get("exclude"),
        exclude_add=section.get("exclude_add", []),
        exclude_dirs=section.get("exclude_dirs"),
        exclude_dirs_add=section.get("exclude_dirs_add", []),
    )


def _merge(into: SiftConfig, data: dict[str, Any]) -> None:
    if "scan" in data:
        new_scan = _parse_scan(data["scan"])
        for attr in ("roots", "presets", "include", "exclude", "exclude_dirs"):
            value = getattr(new_scan, attr)
            if value is not None:
                setattr(into.scan, attr, value)
        for attr in ("include_add", "exclude_add", "exclude_dirs_add"):
            if getattr(new_scan, attr):
                getattr(into.scan, attr).extend(getattr(new_scan, attr))
    if "dump" in data:
        for key in into.dump.__dataclass_fields__:
            if key in data["dump"]:
                setattr(into.dump, key, data["dump"][key])
    if "cache" in data:
        c = data["cache"]
        if "enabled" in c:
            into.cache.enabled = c["enabled"]
        if "path" in c:
            into.cache.path = Path(c["path"]).expanduser()
    if "restore" in data:
        if "force" in data["restore"]:
            into.restore.force = data["restore"]["force"]
    if "keys" in data:
        for key, value in data["keys"].items():
            if hasattr(into.keys, key):
                setattr(into.keys, key, value)


def load_config(*, cwd: Path | None = None) -> SiftConfig:
    """Cascade: built-in → ~/.config → nearest .sift.toml → env → (CLI applies last)."""
    config = SiftConfig()
    user = _user_config_path()
    if user.is_file():
        with user.open("rb") as f:
            _merge(config, tomllib.load(f))
    project = _find_project_config((cwd or Path.cwd()).resolve())
    if project is not None:
        with project.open("rb") as f:
            _merge(config, tomllib.load(f))
    # environment overrides
    if env_presets := os.environ.get("SIFT_SCAN_PRESETS"):
        config.scan.presets = [p.strip() for p in env_presets.split(",") if p.strip()]
    if env_cache := os.environ.get("SIFT_CACHE_PATH"):
        config.cache.path = Path(env_cache).expanduser()
    if os.environ.get("SIFT_NO_CACHE") == "1":
        config.cache.enabled = False
    return config


def apply_scan_cli_overrides(
    config: SiftConfig,
    *,
    include: list[str] | None,
    exclude: list[str] | None,
    exclude_dirs: list[str] | None,
) -> None:
    """Overlay CLI scan flags on the config; CLI values replace config/presets.

    Absent flags (``None``) leave the config untouched. Present flags
    override the resolved value entirely and clear the ``*_add`` companion
    list, matching the headless ``sift`` CLI. Callers that want "config
    plus extra" should set ``include_add``/``exclude_add``/``exclude_dirs_add``
    in the config file instead of passing the flag.
    """
    from .core import parse_patterns

    if include is not None:
        config.scan.include = parse_patterns(include)
        config.scan.include_add = []
    if exclude is not None:
        config.scan.exclude = parse_patterns(exclude)
        config.scan.exclude_add = []
    if exclude_dirs is not None:
        config.scan.exclude_dirs = parse_patterns(exclude_dirs)
        config.scan.exclude_dirs_add = []
