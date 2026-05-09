"""Tests for clean_text_for_typst — Typst-mode escaping of scraped text."""

import shutil
import subprocess
from pathlib import Path

import pytest

from evid.core.text_cleaning import clean_text_for_typst


def _typst_compiles(body: str, tmp_path: Path) -> tuple[bool, str]:
    """Wrap body in a minimal Typst doc, run `typst compile`, return (ok, stderr)."""
    typ = tmp_path / "doc.typ"
    pdf = tmp_path / "doc.pdf"
    typ.write_text(f"= Title\n\n{body}\n", encoding="utf-8")
    proc = subprocess.run(
        ["typst", "compile", str(typ), str(pdf)],
        capture_output=True,
    )
    return proc.returncode == 0, proc.stderr.decode()


needs_typst = pytest.mark.skipif(
    shutil.which("typst") is None, reason="typst binary not on PATH"
)


@needs_typst
def test_bare_slash_line_compiles(tmp_path):
    """A line containing only '/' must not break Typst compilation."""
    cleaned = clean_text_for_typst("before\n/\nafter")
    ok, err = _typst_compiles(cleaned, tmp_path)
    assert ok, f"typst compile failed: {err}"


@needs_typst
def test_slash_then_space_line_compiles(tmp_path):
    """'/ word' at line start would be parsed as term list and must be escaped."""
    cleaned = clean_text_for_typst("before\n/ word\nafter")
    ok, err = _typst_compiles(cleaned, tmp_path)
    assert ok, f"typst compile failed: {err}"


@needs_typst
def test_indented_bare_slash_compiles(tmp_path):
    """Whitespace-indented bare '/' also triggers the term-list parser."""
    cleaned = clean_text_for_typst("before\n   /\nafter")
    ok, err = _typst_compiles(cleaned, tmp_path)
    assert ok, f"typst compile failed: {err}"


def test_inline_slash_preserved():
    """'/' inside text (URLs, paths, fractions) must NOT be escaped."""
    out = clean_text_for_typst("see https://example.com/page and a/b")
    assert "https://example.com/page" in out
    assert "a/b" in out


def test_slash_followed_by_text_preserved():
    """'/text' at line start is not term-list syntax; leave it alone."""
    out = clean_text_for_typst("/path/to/file")
    assert "/path/to/file" in out


def test_url_split_after_slash_rejoined():
    """URL broken at a path '/' boundary is reassembled."""
    out = clean_text_for_typst("see https://example.com/\nvery/long/path here")
    assert "https://example.com/very/long/path" in out


def test_url_split_at_query_rejoined():
    """URL broken before/after query separators is reassembled."""
    out = clean_text_for_typst("https://example.com/foo?a=1\n&b=2 done")
    assert "https://example.com/foo?a=1&b=2" in out


def test_url_split_into_many_fragments_rejoined():
    """Multiple <wbr>-style fragments collapse into one URL."""
    fragmented = (
        "See\nhttps://example.com/\nvery/\nlong/\npath?x=1\nfor details."
    )
    out = clean_text_for_typst(fragmented)
    assert "https://example.com/very/long/path?x=1" in out


def test_url_then_sentence_not_merged():
    """A complete URL followed by ordinary prose must NOT be glued together."""
    out = clean_text_for_typst("Visit https://example.com\nfor more details.")
    assert "https://example.com" in out
    assert "for more details" in out
    assert "comfor" not in out


def test_url_with_trailing_dash_rejoined():
    """URL wrapped after a '-' (common in long path segments) is rejoined."""
    out = clean_text_for_typst("https://example.com/very-long-\nfilename.html done")
    assert "https://example.com/very-long-filename.html" in out


def test_url_intact_when_already_on_one_line():
    """Already-intact URLs pass through unchanged."""
    src = "Visit https://example.com/foo/bar?x=1&y=2 today"
    out = clean_text_for_typst(src)
    assert "https://example.com/foo/bar?x=1&y=2" in out
