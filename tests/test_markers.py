from __future__ import annotations

import re

import pytest

from sift.markers import BASE_CLOSE, iter_dump_files, make_markers

NONCED_OPEN = re.compile(r"<<<SIFT:[^:>]+:[0-9a-f]{8}>>>")
NONCED_CLOSE = re.compile(r"<<<END-SIFT:[0-9a-f]{8}>>>")


def test_base_markers_when_no_collision() -> None:
    opener, closer = make_markers("a.py", "print('a')\n")
    assert opener == "<<<SIFT:a.py>>>"
    assert closer == BASE_CLOSE


def test_nonce_when_content_has_closer() -> None:
    opener, closer = make_markers("a.py", f"S = '{BASE_CLOSE}'\n")
    assert NONCED_OPEN.match(opener)
    assert NONCED_CLOSE.match(closer)


def test_base_markers_when_content_has_embedded_opener() -> None:
    """Another file's opener in content is safe: parser only matches at pos >= 0."""
    content = "X = '<<<SIFT:other.py>>>'\n"
    opener, closer = make_markers("a.py", content)
    assert opener == "<<<SIFT:a.py>>>"
    assert closer == BASE_CLOSE
    dump = f"{opener}\n{content}{closer}\n"
    assert list(iter_dump_files(dump)) == [("a.py", content)]


def test_nonce_when_content_has_own_opener() -> None:
    """Content that literally contains this file's opener forces nonce form."""
    opener, closer = make_markers("a.py", "print('<<<SIFT:a.py>>>')\n")
    assert NONCED_OPEN.match(opener)
    assert NONCED_CLOSE.match(closer)


def test_roundtrip_single() -> None:
    content = "print('hi')\nline2\n"
    opener, closer = make_markers("a.py", content)
    dump = f"{opener}\n{content}{closer}\n"
    assert list(iter_dump_files(dump)) == [("a.py", content)]


def test_roundtrip_mixed_nonce_and_base() -> None:
    a_content = "plain\n"
    b_content = f"S = '{BASE_CLOSE}'\n"
    a_open, a_close = make_markers("a.py", a_content)
    b_open, b_close = make_markers("b.py", b_content)
    dump = f"{a_open}\n{a_content}{a_close}\n{b_open}\n{b_content}{b_close}\n"
    result = list(iter_dump_files(dump))
    assert result == [("a.py", a_content), ("b.py", b_content)]


def test_empty_dump_yields_nothing() -> None:
    assert list(iter_dump_files("")) == []


def test_unterminated_raises() -> None:
    with pytest.raises(ValueError, match="unterminated"):
        list(iter_dump_files("<<<SIFT:a.py>>>\ncontent without closer"))


def test_content_preserves_crlf() -> None:
    content = "line1\r\nline2\r\n"
    opener, closer = make_markers("a.py", content)
    dump = f"{opener}\n{content}{closer}\n"
    assert list(iter_dump_files(dump)) == [("a.py", content)]
