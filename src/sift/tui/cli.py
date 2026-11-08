"""Entry point for ``sift-tui``."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..config import apply_scan_cli_overrides, load_config
from ..core import validate_roots
from .app import SiftApp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SIFT -- SIFT's Interactive File Trawler."
    )
    parser.add_argument(
        "directories",
        nargs="*",
        metavar="DIR",
        help="source roots (default: from config or current directory)",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=None,
        metavar="GLOB[,GLOB...]",
        help="only include matching files (repeatable; replaces config/preset includes)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=None,
        metavar="GLOB[,GLOB...]",
        help="exclude matching files (repeatable; replaces config/preset excludes)",
    )
    parser.add_argument(
        "--exclude-dir",
        action="append",
        default=None,
        metavar="GLOB[,GLOB...]",
        help="exclude matching directories (repeatable; replaces config/preset excludes)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        roots = validate_roots(args.directories) if args.directories else None
    except ValueError as exc:
        parser.error(str(exc))

    config = load_config()
    apply_scan_cli_overrides(
        config,
        include=args.include,
        exclude=args.exclude,
        exclude_dirs=args.exclude_dir,
    )

    SiftApp(roots, config=config).run()
    return 0
