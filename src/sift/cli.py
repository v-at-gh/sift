"""Non-interactive command-line interface for SIFT."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import (
    SiftConfig,
    apply_scan_cli_overrides,
    load_config,
    resolve_scan,
)
from .core import (
    expand_format_escapes,
    validate_comment_support,
    validate_doc_support,
    validate_roots,
)
from .engine import DumpOptions, ScanOptions, SiftEngine

_HANDLED_ERRORS = (OSError, UnicodeError, ValueError, KeyError, IndexError)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="SIFT -- SIFT's Interactive File Trawler. Concatenate selected source files."
    )
    parser.add_argument(
        "directories", nargs="*", metavar="DIR", help="source directories"
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help="output file; required unless --stdout or --dry-run is requested",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--dry-run", action="store_true", help="list matching files only"
    )
    modes.add_argument("--stdout", action="store_true", help="write the dump to stdout")
    parser.add_argument(
        "--exclude", action="append", default=None, metavar="GLOB[,GLOB...]"
    )
    parser.add_argument(
        "--exclude-dir", action="append", default=None, metavar="GLOB[,GLOB...]"
    )
    parser.add_argument(
        "--include",
        action="append",
        default=None,
        metavar="GLOB[,GLOB...]",
        help="only include matching files (default from config/presets)",
    )
    parser.add_argument(
        "--file-format",
        "--separator-format",
        dest="file_format",
        default=None,
        metavar="TEMPLATE",
        help="per-file template with {path}, {content}, {opener}, {closer}, and {end} fields",
    )
    parser.add_argument(
        "--absolute-paths",
        "--absolute-path",
        dest="absolute_paths",
        action="store_true",
        help="write absolute rather than root-relative file paths",
    )
    parser.add_argument("--remove-comments", action="store_true")
    parser.add_argument("--remove-docs", action="store_true")
    parser.add_argument("--compact-json", action="store_true")
    parser.add_argument("--strip-leading-whitespace", action="store_true")
    parser.add_argument(
        "--restore",
        nargs=2,
        metavar=("DUMP", "TARGET"),
        help="restore files from a SIFT dump into TARGET (ignores DIR arguments)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="with --restore: overwrite existing files (default: refuse)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_mode(parser, args)
    try:
        if args.restore is not None:
            return _run_restore(args)
        return _run_dump(args, parser)
    except _HANDLED_ERRORS as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


# --- dispatch ------------------------------------------------------------


def _validate_mode(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Reject impossible flag combinations before any I/O."""
    if args.force and args.restore is None:
        parser.error("--force requires --restore")
    if args.restore is not None:
        if args.output or args.stdout or args.dry_run:
            parser.error(
                "--restore cannot be combined with --output/--stdout/--dry-run"
            )
        return
    if not args.directories:
        parser.error("at least one source directory is required (or use --restore)")
    if not args.stdout and not args.dry_run and not args.output:
        parser.error("--output is required unless --stdout or --dry-run is used")
    if args.stdout and args.output:
        parser.error("--output cannot be used together with --stdout")


# --- restore -------------------------------------------------------------


def _run_restore(args: argparse.Namespace) -> int:
    config = load_config()
    overwrite = config.restore.force or args.force
    target = Path(args.restore[1])
    count = SiftEngine.restore(Path(args.restore[0]), target, overwrite=overwrite)
    print(f"Restored {count} file(s) into {target}", file=sys.stderr)
    return 0


# --- dump ----------------------------------------------------------------


def _run_dump(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    config = _merged_config(args)
    _validate_file_format(parser, config.dump.file_format)

    roots = validate_roots(args.directories)
    output_path = _resolve_output_path(parser, args.output)

    include, exclude, exclude_dirs = resolve_scan(config.scan)
    engine = SiftEngine(
        roots,
        cache_path=config.cache.path,
        use_cache=config.cache.enabled,
    )
    files = engine.scan(ScanOptions(include, exclude, exclude_dirs))

    if args.dry_run:
        return _print_dry_run(files, output_path, config.dump.absolute_paths)

    if config.dump.remove_comments:
        validate_comment_support(files)
    if config.dump.remove_docs:
        validate_doc_support(files)

    return _write_dump(
        engine,
        files,
        output_path,
        _dump_options_from(config.dump),
        use_stdout=args.stdout,
    )


# --- config + CLI overrides ----------------------------------------------


def _merged_config(args: argparse.Namespace) -> SiftConfig:
    config = load_config()
    _apply_cli_overrides(config, args)
    return config


def _apply_cli_overrides(config: SiftConfig, args: argparse.Namespace) -> None:
    """Overlay CLI values on the cascade; absent flags leave config intact."""
    apply_scan_cli_overrides(
        config,
        include=args.include,
        exclude=args.exclude,
        exclude_dirs=args.exclude_dir,
    )
    if args.file_format:
        config.dump.file_format = expand_format_escapes(args.file_format)
    config.dump.absolute_paths |= args.absolute_paths
    config.dump.remove_comments |= args.remove_comments
    config.dump.remove_docs |= args.remove_docs
    config.dump.compact_json |= args.compact_json
    config.dump.strip_leading_whitespace |= args.strip_leading_whitespace


# --- helpers -------------------------------------------------------------


def _validate_file_format(parser: argparse.ArgumentParser, template: str) -> None:
    try:
        template.format(
            path="example.py",
            content="",
            end="END-SIFT",
            opener="",
            closer="",
        )
    except (KeyError, ValueError, IndexError) as exc:
        parser.error(f"invalid --file-format template: {exc}")


def _resolve_output_path(
    parser: argparse.ArgumentParser,
    raw: str | None,
) -> Path | None:
    if not raw:
        return None
    path = Path(raw).expanduser().absolute()
    if path.exists() and path.is_dir():
        parser.error(f"output path is a directory: {path}")
    return path


def _print_dry_run(files, output_path: Path | None, absolute: bool) -> int:
    for source_file in files:
        print(source_file.path if absolute else source_file.relative_path)
    suffix = f" into {output_path}" if output_path else ""
    print(
        f"Dry run: would concatenate {len(files)} file(s){suffix}",
        file=sys.stderr,
    )
    return 0


def _dump_options_from(dump) -> DumpOptions:
    return DumpOptions(
        absolute_paths=dump.absolute_paths,
        file_format=dump.file_format,
        remove_comments=dump.remove_comments,
        remove_docs=dump.remove_docs,
        compact_json_files=dump.compact_json,
        strip_leading_whitespace=dump.strip_leading_whitespace,
    )


def _write_dump(
    engine: SiftEngine,
    files,
    output_path: Path | None,
    options: DumpOptions,
    *,
    use_stdout: bool,
) -> int:
    if use_stdout:
        result = engine.write_dump(files, None, options, stream=sys.stdout)
        sys.stdout.flush()
        print(f"Wrote {result.written} file(s) to stdout", file=sys.stderr)
    else:
        assert output_path is not None
        result = engine.write_dump(files, output_path, options)
        print(f"Wrote {result.written} file(s) to {output_path}", file=sys.stderr)
    for err in result.errors:
        kind = "warning" if err.kind == "transform" else "error"
        print(f"{kind}: {err.path}: {err.message}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
