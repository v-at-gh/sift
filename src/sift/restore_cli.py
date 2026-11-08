"""CLI for ``sift-restore``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .markers import iter_dump_files
from .restore import restore_dump


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sift-restore",
        description="Restore files from a SIFT dump into a target directory.",
    )
    parser.add_argument("dump", type=Path, help="SIFT dump file to read")
    parser.add_argument("target", type=Path, help="directory to write files into")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="list entries without writing anything",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="overwrite existing files (default: refuse)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.dry_run:
            text = args.dump.read_text(encoding="utf-8")
            count = 0
            for relative_path, _ in iter_dump_files(text):
                print(relative_path)
                count += 1
            print(
                f"Dry run: would restore {count} file(s) into {args.target}",
                file=sys.stderr,
            )
            return 0
        count = restore_dump(args.dump, args.target, overwrite=args.force)
        print(f"Restored {count} file(s) into {args.target}", file=sys.stderr)
        return 0
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
