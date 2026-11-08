"""SIFT dump marker construction and parsing."""

from __future__ import annotations

import re
import secrets
from typing import Iterator

NONCE_LEN = 8

OPENER_PATTERN = re.compile(
    r"^<<<SIFT:(?P<path>[^\n]+?)(?::(?P<nonce>[0-9a-f]{%d}))?>>>\r?\n" % NONCE_LEN,
    re.MULTILINE,
)

BASE_OPEN = "<<<SIFT:{path}>>>"
BASE_CLOSE = "<<<END-SIFT>>>"
NONCED_OPEN = "<<<SIFT:{path}:{nonce}>>>"
NONCED_CLOSE = "<<<END-SIFT:{nonce}>>>"


def make_markers(path: str, content: str) -> tuple[str, str]:
    """Return (opener, closer) that cannot collide with *content*.

    The default form is human-readable::

        <<<SIFT:src/main.py>>>
        ...
        <<<END-SIFT>>>

    If *content* contains either default marker (for example, dumping SIFT
    itself), a per-file 8-hex-digit nonce is appended to both markers::

        <<<SIFT:src/sift/core.py:a3f2b1c5>>>
        ...
        <<<END-SIFT:a3f2b1c5>>>
    """
    default_open = BASE_OPEN.format(path=path)
    if default_open not in content and BASE_CLOSE not in content:
        return default_open, BASE_CLOSE
    for _ in range(64):
        nonce = secrets.token_hex(NONCE_LEN // 2)
        opener = NONCED_OPEN.format(path=path, nonce=nonce)
        closer = NONCED_CLOSE.format(nonce=nonce)
        if opener not in content and closer not in content:
            return opener, closer
    raise ValueError(
        f"cannot construct collision-free markers for {path}: "
        "content references every attempted nonce"
    )


def iter_dump_files(text: str) -> Iterator[tuple[str, str]]:
    """Yield (relative_path, content) pairs from a SIFT dump."""
    pos = 0
    while True:
        match = OPENER_PATTERN.search(text, pos)
        if match is None:
            return
        path = match.group("path")
        nonce = match.group("nonce")
        closer = NONCED_CLOSE.format(nonce=nonce) if nonce else BASE_CLOSE
        body_start = match.end()
        body_end = text.find(closer, body_start)
        if body_end == -1:
            raise ValueError(f"unterminated dump entry for {path}")
        yield path, text[body_start:body_end]
        pos = body_end + len(closer)
        if pos < len(text) and text[pos] == "\r":
            pos += 1
        if pos < len(text) and text[pos] == "\n":
            pos += 1
