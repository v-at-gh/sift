# Test guide

## Running the suite

Run all tests or include verbose test names:

```bash
uv run pytest -q
uv run pytest -v
```

The dev group declares pytest and pytest-asyncio, but not pytest-cov
(`pyproject.toml:19-20`), so this guide does not include a coverage command.
The baseline result for this checkout was 201 passed in 25.84 seconds.

Async tests use `asyncio_mode = "auto"` and the Textual test pilot. The
configuration is in `pyproject.toml:29-34`; tests start apps with
`async with app.run_test() as pilot` and wait for workers with
`await pilot.pause()` (`test_tui_smoke.py:9-35`).

## Fixtures

`isolated_home` redirects `HOME`, `USERPROFILE`, `XDG_CONFIG_HOME`, and
`XDG_CACHE_HOME` into `tmp_path`. It clears `SIFT_SCAN_PRESETS`,
`SIFT_CACHE_PATH`, and `SIFT_NO_CACHE`, then changes the current directory
to `tmp_path` so project configuration and the developer's cache do not
affect the test (`conftest.py:11-27`).

`sample_tree` creates the following files (`conftest.py:30-44`):

```text
src/
  a.py
  b.py
  notes.txt
  sub/
    c.py
  ignored/
    d.py
```

There are two `.py` files directly under `src/`, one `.py` file under `sub/`,
one `.txt` file, and one `.py` file under `ignored/`. The fixture docstring
describes three root-level `.py` files, but the setup currently creates two
(`conftest.py:32-40`).

The autouse `_isolated_sift_logger` fixture removes logger handlers after
each test. `LogPane` registers a rotating file handler on mount, so the
fixture prevents those handlers from leaking between tests
(`conftest.py:47-63`).

## Test map

This table names the test files that exercise each implementation area. It
does not claim statement or branch coverage.

| Module or behavior | Test file | Covered behavior |
| --- | --- | --- |
| `cache.py` | `test_cache.py` | Schema version, stat lookup, checksum reuse/invalidation, pruning, and digest values. |
| `core.py` file collection | `test_collect.py` | Include/exclude matching, directory excludes, metadata, output exclusion, and symlinks. |
| `core.py` transforms | `test_strip.py` | Unsafe whitespace-strip formats and unchanged/stripped content cases. |
| `core.py` binary detection | `test_binary.py` | Empty/text/binary files, probe window, and missing-file result. |
| `cli.py`, `core.py`, restore dispatch | `test_cli.py` | Dump modes, invalid arguments, dry run, and CLI restore. |
| `config.py` | `test_config.py` | Presets, config merge, environment overrides, and CLI override behavior. |
| `engine.py` | `test_engine.py` | View/selection initialization, count invalidation, and directory mtimes. |
| `filters.py` | `test_filters.py` | Expression parsing, glob matching, visibility, and selection operations. |
| `markers.py` | `test_markers.py` | Default/nonced boundaries, parse errors, empty dumps, and line endings. |
| `restore.py` | `test_restore.py` | Round trip, traversal rejection, overwrite refusal, and forced replacement. |
| Dump/restore integration | `test_roundtrip.py` | Full round trip and marker-containing content. |
| `tui/bindings.py` | `test_tui_bindings.py` | Binding composition, priority quit binding, and configured key overrides. |
| `tui/cli.py` | `test_tui_cli.py` | Positional roots and repeatable filter arguments. |
| `tui/widgets/extensions.py` | `test_tui_extensions.py` | Extension rows, posted requests, cursor retention, and visibility. |
| `tui/widgets/file_table.py` | `test_tui_file_table.py` | Rows, selection markers, header sorting, timestamps, and messages. |
| `tui/widgets/file_tree.py` | `test_tui_file_tree.py` | Expansion, selection, navigation, sorting, and preview requests. |
| `tui/format.py` | `test_tui_format.py` | Selection circles/styles, date formatting, and size formatting. |
| `tui/widgets/log_pane.py` | `test_tui_log_pane.py` | Widget/file logging, error count, and handler behavior. |
| `tui/widgets/preview.py` | `test_tui_preview.py` | File loading, binary/size messages, target changes, and wrapping. |
| App integration | `test_tui_smoke.py` | App startup, tabs, preview flow, CLI filter use, and preview wrapping. |

## Gaps

TUI integration tests exercise app startup and selected interactions, while
the table, tree, extension, log, and preview widgets have dedicated tests.
There is no dedicated `test_tui_actions.py` or test file for
`DumpModalScreen`. `python_deps.py` and `deps_cli.py` are absent from the
source tree and have no tests. The source and test file lists are visible in
the repository tree; no deleted feature is inferred from an absent test.

## Adding a test

Use `tmp_path` for files and add `isolated_home` when a test touches config or
cache behavior. Import `SiftApp` from `sift.tui` for app tests. This example
shows a unit test and an async pilot test:

```python
def test_unit(tmp_path):
    path = tmp_path / "item.txt"; path.write_text("sample")
    assert path.read_text() == "sample"
async def test_app(sample_tree, isolated_home):
    app = SiftApp([sample_tree])
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#views") is not None
```
