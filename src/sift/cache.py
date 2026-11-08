"""SQLite-backed metadata cache for SIFT file scanning."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    path          TEXT PRIMARY KEY,
    size          INTEGER NOT NULL,
    mtime_ns      INTEGER NOT NULL,
    ctime_ns      INTEGER NOT NULL DEFAULT 0,
    inode         INTEGER NOT NULL DEFAULT 0,
    device        INTEGER NOT NULL DEFAULT 0,
    checksum      TEXT,
    checksum_algo TEXT NOT NULL DEFAULT 'sha256',
    last_seen     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS files_by_mtime ON files(mtime_ns);
"""

def default_cache_path() -> Path:
    """Compute the cache path fresh from the current environment.

    Must be a function, not a constant: tests and long-running processes
    rely on XDG_CACHE_HOME being honoured at call time, not at import time.
    """
    base = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))
    return (base / "sift" / "index.sqlite3").expanduser()


@dataclass(frozen=True, slots=True)
class CachedEntry:
    path: str
    size: int
    mtime_ns: int
    ctime_ns: int
    inode: int
    device: int
    checksum: str | None
    checksum_algo: str


class Cache:
    """Per-user SQLite cache.

    A connection is not shareable between threads: create one ``Cache`` per
    thread (the TUI worker creates its own). WAL mode allows the TUI thread
    to read while the scan thread writes.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = (Path(path) if path is not None else default_cache_path()).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._ensure_schema()
        self._scan_started = time.time()

    def _ensure_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._conn.commit()
        elif int(row["value"]) != SCHEMA_VERSION:
            raise RuntimeError(
                f"cache schema version {row['value']} != {SCHEMA_VERSION}; "
                f"delete {self.path} to rebuild"
            )

    # -- scan lifecycle ---------------------------------------------------

    def begin_scan(self) -> None:
        """Mark the start of a scan; ``prune()`` removes entries not touched."""
        self._scan_started = time.time()

    def record_stat(self, path: str, st: os.stat_result) -> None:
        self._conn.execute(
            "INSERT INTO files(path, size, mtime_ns, ctime_ns, inode, device, "
            "                  checksum, checksum_algo, last_seen) "
            "VALUES(?, ?, ?, ?, ?, ?, NULL, 'sha256', ?) "
            "ON CONFLICT(path) DO UPDATE SET "
            "  size      = excluded.size, "
            "  mtime_ns  = excluded.mtime_ns, "
            "  ctime_ns  = excluded.ctime_ns, "
            "  inode     = excluded.inode, "
            "  device    = excluded.device, "
            "  checksum  = CASE "
            "    WHEN files.size = excluded.size "
            "     AND files.mtime_ns = excluded.mtime_ns "
            "    THEN files.checksum ELSE NULL END, "
            "  last_seen = excluded.last_seen",
            (
                path,
                st.st_size,
                st.st_mtime_ns,
                st.st_ctime_ns,
                getattr(st, "st_ino", 0),
                getattr(st, "st_dev", 0),
                time.time(),
            ),
        )

    def commit(self) -> None:
        self._conn.commit()

    def prune(self) -> int:
        """Delete entries not seen since ``begin_scan()``. Returns row count."""
        cur = self._conn.execute(
            "DELETE FROM files WHERE last_seen < ?", (self._scan_started,)
        )
        self._conn.commit()
        return cur.rowcount

    # -- lookups ----------------------------------------------------------

    def lookup(self, path: str, size: int, mtime_ns: int) -> CachedEntry | None:
        row = self._conn.execute(
            "SELECT path, size, mtime_ns, ctime_ns, inode, device, "
            "       checksum, checksum_algo "
            "FROM files WHERE path = ?",
            (path,),
        ).fetchone()
        if row is None:
            return None
        entry = CachedEntry(**dict(row))
        if entry.size != size or entry.mtime_ns != mtime_ns:
            return None
        return entry

    def store_checksum(self, path: str, checksum: str, algo: str = "sha256") -> None:
        self._conn.execute(
            "UPDATE files SET checksum = ?, checksum_algo = ? WHERE path = ?",
            (checksum, algo, path),
        )

    def checksum_for(self, path: Path, st: os.stat_result | None = None) -> str:
        """Return the SHA-256 for *path*, using the cache when stat matches."""
        key = str(Path(path).absolute())
        if st is None:
            try:
                st = path.stat()
            except OSError:
                st = None
        if st is not None:
            entry = self.lookup(key, st.st_size, st.st_mtime_ns)
            if entry is not None and entry.checksum is not None:
                return entry.checksum
        digest = compute_checksum(Path(path))
        if st is not None:
            self.record_stat(key, st)
            self.store_checksum(key, digest)
            self.commit()
        return digest

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Cache":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def compute_checksum(path: Path, algo: str = "sha256") -> str:
    """Stream *path* through *algo* without loading it fully into memory."""
    digest = hashlib.new(algo)
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
