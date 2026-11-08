"""Built-in presets. Each is a pure dict; composition is in config.py."""

_BASE_EXCLUDES = [
    ".git", ".hg", ".svn", ".idea", ".gradle",
    ".venv", "venv", "env",
    "node_modules",
    "build", "dist", "target",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "site-packages",
]

PRESETS: dict[str, dict] = {
    "base":       {"exclude_dirs": _BASE_EXCLUDES},
    "python":     {"include": ["*.py", "*.pyi"]},
    "javascript": {"include": ["*.js", "*.mjs", "*.cjs"]},
    "typescript": {"include": ["*.ts", "*.tsx"]},
    "android":    {"include": ["*.kt", "*.kts", "*.java", "*.xml"]},
    "go":         {"include": ["*.go", "go.mod", "go.sum"]},
    "swift":      {"include": ["*.swift"]},
    "csharp":     {"include": ["*.cs", "*.csproj"]},
}
