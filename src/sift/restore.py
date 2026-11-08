"""Restore files from a SIFT dump."""

from __future__ import annotations

from pathlib import Path

from .markers import iter_dump_files


def restore_dump(
    dump_path: Path,
    target_root: Path,
    *,
    overwrite: bool = False,
) -> int:
    """Write every file from a SIFT dump under *target_root*.

    Paths are validated against *target_root* to prevent traversal. Refuses
    to replace existing files unless *overwrite* is true. Returns the number
    of files written.
    """
    dump_path = Path(dump_path).expanduser()
    if not dump_path.is_file():
        raise ValueError(f"dump is not a file: {dump_path}")
    target_root = Path(target_root).expanduser().resolve()

    text = dump_path.read_text(encoding="utf-8")

    pending: list[tuple[Path, str]] = []
    for relative_path, content in iter_dump_files(text):
        destination = (target_root / relative_path).resolve()
        if not destination.is_relative_to(target_root):
            raise ValueError(f"path escapes target root: {relative_path}")
        pending.append((destination, content))

    if not overwrite:
        conflicts = [str(destination) for destination, _ in pending if destination.exists()]
        if conflicts:
            raise ValueError(
                f"refusing to overwrite {len(conflicts)} existing file(s); "
                f"use --force to replace (first: {conflicts[0]})"
            )

    for destination, content in pending:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8", newline="")
    return len(pending)
