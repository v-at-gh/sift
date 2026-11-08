from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from sift import cache as cache_mod
from sift.cache import Cache, compute_checksum, default_cache_path


def test_lookup_matches_recorded_stat(isolated_home: Path, tmp_path: Path) -> None:
    path = tmp_path / "f.txt"
    path.write_text("hello", encoding="utf-8")
    key, st = str(path), os.stat(path)
    with Cache() as c:
        c.record_stat(key, st)
        c.commit()
        entry = c.lookup(key, st.st_size, st.st_mtime_ns)
    assert entry is not None
    assert entry.size == st.st_size
    assert entry.ctime_ns == st.st_ctime_ns
    assert entry.checksum is None


def test_lookup_size_mismatch_returns_none(isolated_home: Path, tmp_path: Path) -> None:
    path = tmp_path / "f.txt"
    path.write_text("hello", encoding="utf-8")
    key, st = str(path), os.stat(path)
    with Cache() as c:
        c.record_stat(key, st)
        c.commit()
        assert c.lookup(key, st.st_size + 1, st.st_mtime_ns) is None


def test_record_stat_preserves_checksum_when_unchanged(
    isolated_home: Path, tmp_path: Path,
) -> None:
    path = tmp_path / "f.txt"
    path.write_text("hello", encoding="utf-8")
    key, st = str(path), os.stat(path)
    with Cache() as c:
        c.record_stat(key, st)
        c.store_checksum(key, "abc")
        c.commit()
        c.record_stat(key, st)
        c.commit()
        assert c.lookup(key, st.st_size, st.st_mtime_ns).checksum == "abc"


def test_record_stat_invalidates_checksum_on_size_change(
    isolated_home: Path, tmp_path: Path,
) -> None:
    path = tmp_path / "f.txt"
    path.write_text("hello", encoding="utf-8")
    key = str(path)
    with Cache() as c:
        st1 = os.stat(path)
        c.record_stat(key, st1)
        c.store_checksum(key, "abc")
        c.commit()
        path.write_text("hello world", encoding="utf-8")
        st2 = os.stat(path)
        c.record_stat(key, st2)
        c.commit()
        assert c.lookup(key, st2.st_size, st2.st_mtime_ns).checksum is None


def test_prune_removes_unseen_entries(isolated_home: Path, tmp_path: Path) -> None:
    stale = tmp_path / "stale.txt"
    stale.write_text("x", encoding="utf-8")
    with Cache() as c:
        c.record_stat(str(stale), os.stat(stale))
        c.commit()
        c.begin_scan()
        fresh = tmp_path / "fresh.txt"
        fresh.write_text("y", encoding="utf-8")
        c.record_stat(str(fresh), os.stat(fresh))
        c.commit()
        removed = c.prune()
    assert removed == 1


def test_schema_version_mismatch_raises(isolated_home: Path) -> None:
    cache_path = default_cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(cache_path))
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta VALUES('schema_version', '999')")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="schema version"):
        Cache()


def test_checksum_for_caches_result(
    isolated_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "f.txt"
    path.write_text("hello", encoding="utf-8")
    calls: list[Path] = []
    original = cache_mod.compute_checksum

    def counting(p: Path) -> str:
        calls.append(p)
        return original(p)

    monkeypatch.setattr(cache_mod, "compute_checksum", counting)
    with Cache() as c:
        st = path.stat()
        d1 = c.checksum_for(path, st)
        d2 = c.checksum_for(path, st)
    assert d1 == d2
    assert len(calls) == 1


def test_compute_checksum_known_value(tmp_path: Path) -> None:
    path = tmp_path / "f.txt"
    path.write_bytes(b"hello")
    # sha256("hello")
    assert compute_checksum(path) == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )
