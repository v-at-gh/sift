# SIFT v0.0.1 (Alpha)

SIFT's Interactive File Trawler scans source trees, lets you select files, and writes them into a marked dump with optional content transformations.

## Installation

Use Python 3.11 or newer, as required by `pyproject.toml`.

```bash
uv sync
```

The `kotlin` extra installs `tree-sitter-kotlin` and enables `--remove-comments` for `.kt` and `.kts` files (`pyproject.toml:9-11`, `src/sift/core.py:47,687-703`). The code imports `tree_sitter` and `tree_sitter_kotlin`; if either import fails, it raises a `ValueError` with the message "Kotlin comment removal requires optional dependencies; run `uv sync --extra kotlin` in the project environment" (`src/sift/core.py:378-390`).

```bash
uv sync --extra kotlin
```

### Cache upgrade notice

The cache schema is now version 2. If you are upgrading from a development build, remove the old database before using the new cache:

```bash
rm ~/.cache/sift/index.sqlite3
```

An old schema can produce a `RuntimeError` with a schema version mismatch. `SiftEngine.scan` catches a cache initialization `RuntimeError` and scans without the cache, but deleting the old database avoids carrying a stale cache forward (`cache.py:74-89`, `engine.py:137-158`). The path honors `XDG_CACHE_HOME` when it is set.

## Quick start

Write a marked dump to standard output:

```bash
sift ./src --stdout
```

The command prints an entry for each matching file.

Open the interactive selector:

```bash
sift-tui ./src
```

The TUI opens the tree view and lets you select files before creating a dump.
Use a terminal with Unicode support to render the selection markers.

Restore a dump into a directory:

```bash
sift-restore bundle.txt restored/
```

The command writes each dump entry under `restored/` and reports the number of files written.

## Dump format

Each default entry has an opener, content, and closer:

```text
<<<SIFT:path>>>
<content><<<END-SIFT>>>
```

The default template inserts a newline after the opener and after the closer; a line break before the closer comes from the content. If file content contains the default opener for its path or the default closer, SIFT adds the same 8-hex-digit nonce to both markers. `make_markers` checks the resulting markers against the content (`src/sift/markers.py:22-50`).

```text
<<<SIFT:src/main.py>>>
print("hello")
<<<END-SIFT>>>

<<<SIFT:src/markers.py:1a2b3c4d>>>
BASE_CLOSE = "<<<END-SIFT>>>"
print("the closer occurs in this content")
<<<END-SIFT:1a2b3c4d>>>
```

Use `--file-format` to customize each entry. Its fields are `{path}`, `{content}`, `{opener}`, `{closer}`, and `{end}`; see the CLI help below.

## Configuration

Configuration cascades from built-in defaults to the user file, nearest project file, environment variables, and CLI values. The user file is `~/.config/sift/siftrc.toml`; the project file is the nearest `.sift.toml`. `load_config` defines the first four levels, and CLI overrides are applied by the entry point (`src/sift/config.py:166-184`, `src/sift/config.py:187-212`). `XDG_CONFIG_HOME` changes the base directory for the user file.

The example lists every field in the configuration dataclasses. Comments show the dataclass default from `ScanConfig`, `DumpConfig`, `CacheConfig`, `RestoreConfig`, and `KeysConfig` (`src/sift/config.py:13-68`). Because TOML has no `null`, fields whose defaults are `None` have concrete sample values here.

```toml
[scan]
roots = ["src"]                    # default: None
presets = ["base", "python"]       # default: None, resolved to ["base"]
include = ["*.py", "*.pyi"]        # default: None
include_add = []                   # default: []
exclude = []                       # default: None
exclude_add = []                   # default: []
exclude_dirs = [".git", ".hg", ".svn", ".idea", ".gradle", ".venv", "venv", "env", "node_modules", "build", "dist", "target", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "site-packages"] # default: None
exclude_dirs_add = []              # default: []

[dump]
file_format = "{opener}\n{content}{closer}\n" # default: same value
absolute_paths = false             # default: false
remove_comments = false            # default: false
remove_docs = false                # default: false
compact_json = false               # default: false
strip_leading_whitespace = false    # default: false

[cache]
enabled = true                     # default: true
path = "~/.cache/sift/index.sqlite3" # default: None, resolved from XDG

[restore]
force = false                      # default: false

[keys]
toggle = "x"                       # default: "x"
toggle_visibility = "X"            # default: "X"
toggle_extensions = "e"            # default: "e"
toggle_actions = "a"               # default: "a"
toggle_units = "u"                 # default: "u"
focus_view_filter = "f"            # default: "f"
focus_selection_filter = "s"       # default: "s"
next_view = "ctrl+tab"             # default: "ctrl+tab"
show_tree = "1"                    # default: "1"
show_table = "2"                   # default: "2"
show_preview = "3"                 # default: "3"
show_log = "4"                     # default: "4"
open_preview = "o"                 # default: "o"
down_vim = "j"                     # default: "j"
up_vim = "k"                       # default: "k"
down_emacs = "ctrl+n"              # default: "ctrl+n"
up_emacs = "ctrl+p"                # default: "ctrl+p"
tree_left = "h"                    # default: "h"
tree_right = "l"                   # default: "l"
tree_collapse_all = "H"            # default: "H"
preview_wrap = "w"                 # default: "w"
quit = "q"                         # default: "q"
```

The supported environment variables are `SIFT_SCAN_PRESETS`, `SIFT_CACHE_PATH`, and `SIFT_NO_CACHE=1` (`src/sift/config.py:177-183`).

`include_add`, `exclude_add`, and `exclude_dirs_add` append to the resolved preset or configured lists. They do not replace those lists (`src/sift/config.py:98-101`). A CLI include, exclude, or exclude-directory argument replaces its corresponding configured value (`src/sift/config.py:187-212`).

## Presets

The names and patterns below are read from `PRESETS` in `src/sift/presets.py:12-21`.

| Preset | Files or directories named by the preset |
| --- | --- |
| `base` | Excludes common version-control, environment, build, cache, dependency, and package directories. |
| `python` | Includes `*.py` and `*.pyi`. |
| `javascript` | Includes `*.js`, `*.mjs`, and `*.cjs`. |
| `typescript` | Includes `*.ts` and `*.tsx`. |
| `android` | Includes `*.kt`, `*.kts`, `*.java`, and `*.xml`. |
| `go` | Includes `*.go`, `go.mod`, and `go.sum`. |
| `swift` | Includes `*.swift`. |
| `csharp` | Includes `*.cs` and `*.csproj`. |

Compose presets by naming them in `.sift.toml`:

```toml
[scan]
presets = ["base", "python"]
```

Set `presets = []` to disable the default `base` preset. Add explicit patterns when disabling it:

```toml
[scan]
presets = []
include = ["*"]
exclude_dirs = []
```

## CLI reference

### `sift`

This is the verbatim output of `uv run sift --help`.

```text
usage: sift [-h] [-o FILE] [--dry-run | --stdout] [--exclude GLOB[,GLOB...]]
            [--exclude-dir GLOB[,GLOB...]] [--include GLOB[,GLOB...]]
            [--file-format TEMPLATE] [--absolute-paths] [--remove-comments]
            [--remove-docs] [--compact-json] [--strip-leading-whitespace]
            [--restore DUMP TARGET] [--force]
            [DIR ...]

SIFT -- SIFT's Interactive File Trawler. Concatenate selected source files.

positional arguments:
  DIR                   source directories

options:
  -h, --help            show this help message and exit
  -o, --output FILE     output file; required unless --stdout or --dry-run is
                        requested
  --dry-run             list matching files only
  --stdout              write the dump to stdout
  --exclude GLOB[,GLOB...]
  --exclude-dir GLOB[,GLOB...]
  --include GLOB[,GLOB...]
                        only include matching files (default from
                        config/presets)
  --file-format, --separator-format TEMPLATE
                        per-file template with {path}, {content}, {opener},
                        {closer}, and {end} fields
  --absolute-paths, --absolute-path
                        write absolute rather than root-relative file paths
  --remove-comments
  --remove-docs
  --compact-json
  --strip-leading-whitespace
  --restore DUMP TARGET
                        restore files from a SIFT dump into TARGET (ignores
                        DIR arguments)
  --force               with --restore: overwrite existing files (default:
                        refuse)
```

| Flag | Default | Use |
| --- | --- | --- |
| `DIR ...` | Required for scanning. | Names one or more source directories. |
| `-h`, `--help` | Not applicable. | Prints help and exits. |
| `-o`, `--output FILE` | None. | Writes a dump file; required unless `--stdout` or `--dry-run` is set. |
| `--dry-run` | Off. | Lists matches without writing a dump. |
| `--stdout` | Off. | Writes the dump to standard output. |
| `--exclude GLOB[,GLOB...]` | Config and resolved preset value. | Excludes matching files. |
| `--exclude-dir GLOB[,GLOB...]` | Config and resolved preset value. | Excludes matching directories. |
| `--include GLOB[,GLOB...]` | Config and resolved preset value. | Restricts output to matching files. |
| `--file-format`, `--separator-format TEMPLATE` | `DumpConfig.file_format`. | Sets the per-file output template. |
| `--absolute-paths`, `--absolute-path` | Off. | Uses absolute paths in entry markers. |
| `--remove-comments` | Off. | Removes comments for supported file types. |
| `--remove-docs` | Off. | Removes docstrings or documentation comments for supported file types. |
| `--compact-json` | Off. | Removes insignificant whitespace from JSON. |
| `--strip-leading-whitespace` | Off. | Strips leading whitespace except from formats treated as unsafe. |
| `--restore DUMP TARGET` | Not selected. | Restores entries and ignores source directory arguments. |
| `--force` | Off. | Allows overwriting files with `--restore`. |

The `store_true` flags default to false, and output/template parser defaults are `None` (`src/sift/cli.py:33-84`). The command requires a source directory for scanning and an output mode (`src/sift/cli.py:89-107`).

### `sift-tui`

The TUI also accepts `--include`, `--exclude`, and `--exclude-dir`. These repeatable options replace the corresponding config or preset values, as shown by `uv run sift-tui --help` and implemented in `tui/cli.py:23-43`.

```text
usage: sift-tui [-h] [--include GLOB[,GLOB...]] [--exclude GLOB[,GLOB...]]
                [--exclude-dir GLOB[,GLOB...]]
                [DIR ...]

SIFT -- SIFT's Interactive File Trawler.

positional arguments:
  DIR                   source roots (default: from config or current
                        directory)

options:
  -h, --help            show this help message and exit
  --include GLOB[,GLOB...]
                        only include matching files (repeatable; replaces
                        config/preset includes)
  --exclude GLOB[,GLOB...]
                        exclude matching files (repeatable; replaces
                        config/preset excludes)
  --exclude-dir GLOB[,GLOB...]
                        exclude matching directories (repeatable; replaces
                        config/preset excludes)
```

### `sift-restore`

This is the verbatim output of `uv run sift-restore --help`.

```text
usage: sift-restore [-h] [--dry-run] [--force] dump target

Restore files from a SIFT dump into a target directory.

positional arguments:
  dump        SIFT dump file to read
  target      directory to write files into

options:
  -h, --help  show this help message and exit
  --dry-run   list entries without writing anything
  --force     overwrite existing files (default: refuse)
```

| Argument or flag | Default | Use |
| --- | --- | --- |
| `dump` | Required. | Selects the dump to read. |
| `target` | Required. | Selects the directory to write into. |
| `-h`, `--help` | Not applicable. | Prints help and exits. |
| `--dry-run` | Off. | Prints paths without writing. |
| `--force` | Off. | Allows existing files to be overwritten. |

The restore parser defines both flags as `store_true`, so they are false when absent (`src/sift/restore_cli.py:18-27`).

## TUI guide

The UI has a left Extensions pane, center tabs for Tree, Table, Preview, and Log, and a right Actions pane with transformation checkboxes and a `DUMP` button (`src/sift/tui/app.py:93-121`, `src/sift/tui/widgets/actions.py:68-73`). The filter row contains compact view and selection inputs plus add, replace, and remove controls; its row height is one terminal line (`src/sift/tui/styles.tcss:11-15`).

Selection circles show `&#9711;` for none, `&#9684;` for partial, and `&#9679;` for full selection. None is dim, partial is normal brightness, and full is bold (`src/sift/tui/format.py:11-16`, `src/sift/tui/format.py:27-47`). A single selected file is bold; an unselected file is dim (`src/sift/tui/widgets/file_table.py:112-125`).

Click the Table headers `Length`, `Modified`, or `Changed` to sort the table; clicking the same header reverses the current order (`src/sift/tui/widgets/file_table.py:67-80`, `src/sift/tui/widgets/file_table.py:167-194`). Tree headers `Files`, `Length`, and `Modified` also sort their rows (`src/sift/tui/widgets/file_tree.py:160-164`, `src/sift/tui/widgets/file_tree.py:365-377`). Larger lengths and newer timestamps come first when those sort keys are first selected.

Press `DUMP` to open a modal for the output path. If the path already exists, a second modal asks whether to overwrite it (`src/sift/tui/app.py:547-559`, `src/sift/tui/app.py:599-605`, `src/sift/tui/screens/overwrite.py:66-111`).

The preview shows a binary-file message instead of contents when it detects a NUL byte in the first 8192 bytes. It also skips text files larger than 512 KiB and shows their sizes (`src/sift/core.py:107-119`, `src/sift/tui/widgets/preview.py:39-58`, `src/sift/tui/format.py:9`).

See the keybinding table under [TUI keybindings](#tui-keybindings).

## TUI keybindings

These defaults are fields of `KeysConfig` (`src/sift/config.py:45-68`). Configure a binding by its field name under `[keys]`.

| Key | Action | `KeysConfig` field |
| --- | --- | --- |
| `x` | Toggle the current tree file or directory. | `toggle` |
| `X` | Toggle visibility for the current extension. | `toggle_visibility` |
| `e` | Show or hide Extensions. | `toggle_extensions` |
| `a` | Show or hide Actions. | `toggle_actions` |
| `u` | Toggle human-readable size units. | `toggle_units` |
| `f` | Focus the view filter. | `focus_view_filter` |
| `s` | Focus the selection filter. | `focus_selection_filter` |
| `ctrl+tab` | Switch between Tree and Table. | `next_view` |
| `1` | Show Tree. | `show_tree` |
| `2` | Show Table. | `show_table` |
| `3` | Show Preview. | `show_preview` |
| `4` | Show Log. | `show_log` |
| `o` | Open Preview for the current file, or return to the prior tab. | `open_preview` |
| `j`, `ctrl+n` | Move down in a list. | `down_vim`, `down_emacs` |
| `k`, `ctrl+p` | Move up in a list. | `up_vim`, `up_emacs` |
| `h` | Collapse the current Tree directory, or move to its parent. | `tree_left` |
| `l` | Expand the current Tree directory. | `tree_right` |
| `H` | Collapse expanded Tree directories to the root. | `tree_collapse_all` |
| `w` | Toggle Preview line wrapping. | `preview_wrap` |
| `q` | Quit. | `quit` |

When Preview has focus, `j`, `k`, `ctrl+n`, `ctrl+p`, `ctrl+f`, `ctrl+b`, `g`, `G`, `h`, and `l` scroll it. The preview scroll handling is implemented in `PreviewPane.on_key` (`src/sift/tui/widgets/preview.py:64-90`). `enter` expands or collapses a Tree directory and toggles a file selection (`src/sift/tui/widgets/file_tree.py:345-358`). `ctrl+q` is a hard-coded ignored binding (`src/sift/tui/bindings.py:40`).

## Cache

The default database is `~/.cache/sift/index.sqlite3`; `XDG_CACHE_HOME` is used when set (`src/sift/cache.py:33-40`). Schema v2 stores path, size, `mtime_ns`, `ctime_ns`, inode, device, checksum, checksum algorithm, and `last_seen` (`src/sift/cache.py:12-30`). WAL mode is enabled to allow concurrent reader and writer connections (`src/sift/cache.py:55-71`).

The checksum is reused while size and `mtime_ns` match. A changed size or modification time clears the stored checksum, so the next request recomputes SHA-256 (`src/sift/cache.py:97-122`, `src/sift/cache.py:137-173`). `ctime_ns` is stored but is not part of that invalidation comparison.

Remove the database to reset the index, or set `SIFT_NO_CACHE=1` to disable the cache. The TUI writes its session log to `~/.cache/sift/session.log` by default, under the XDG-aware cache directory (`src/sift/tui/widgets/log_pane.py:42-79`).

## Development

Run the suite with:

```bash
uv run pytest -q
```

The observed result was 201 passed in 25.84 seconds. See [tests/README.md](tests/README.md) for fixtures and the test map. See [src/sift/README.md](src/sift/README.md) for architecture and module contracts.
