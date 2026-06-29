"""Tests for full-text search over document bodies (substring + regex).

Searches each doc's ``label.typ``; pages come from ``== Page N`` markers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from evid.core import fulltext
from evid.core.fulltext import search_fulltext

if TYPE_CHECKING:
    from pathlib import Path


def _typ(pages: list[str]) -> str:
    """Build a minimal label.typ body with one ``== Page N`` block per page."""
    parts = [
        '#import "@preview/labtyp:0.1.0": lablist, lab, mset\n',
        "= Title\n",
    ]
    for i, body in enumerate(pages, 1):
        parts.append(f"#mset(values: (opage: {i}))\n== Page {i}\n{body}\n")
    return "\n".join(parts)


def _doc(set_path: Path, uuid: str, pages: list[str], title: str = "Doc") -> Path:
    d = set_path / "docs" / uuid
    d.mkdir(parents=True)
    with (d / "info.yml").open("w", encoding="utf-8") as f:
        yaml.safe_dump({"uuid": uuid, "title": title}, f)
    (d / "label.typ").write_text(_typ(pages), encoding="utf-8")
    return d


def test_literal_finds_matching_doc(tmp_path):
    sp = tmp_path / "set"
    _doc(
        sp,
        "u1",
        ["The defendant was responsible for the safety inspections."],
        "Judgment",
    )
    _doc(
        sp, "u2", ["Weather report: heavy rainfall over the northern coast."], "Weather"
    )
    hits = search_fulltext(sp, "safety inspections", n=5)
    assert len(hits) == 1
    assert hits[0].uuid == "u1"
    assert hits[0].score is None
    assert hits[0].page == 1
    assert "safety inspections" in hits[0].snippet.lower()
    assert hits[0].label == "Judgment"


def test_literal_is_case_insensitive(tmp_path):
    sp = tmp_path / "set"
    _doc(sp, "u1", ["Highly Confidential Memorandum about the merger."])
    hits = search_fulltext(sp, "CONFIDENTIAL memorandum", n=5)
    assert len(hits) == 1
    assert hits[0].uuid == "u1"


def test_literal_no_match_returns_empty(tmp_path):
    sp = tmp_path / "set"
    _doc(sp, "u1", ["A short note about gardening tools and soil."])
    assert search_fulltext(sp, "quantum chromodynamics") == []


def test_page_reported_for_later_page(tmp_path):
    sp = tmp_path / "set"
    _doc(sp, "u1", ["Introduction and overview.", "The needle is on the second page."])
    hits = search_fulltext(sp, "needle", n=5)
    assert len(hits) == 1
    assert hits[0].page == 2


def test_regex_returns_each_match(tmp_path):
    sp = tmp_path / "set"
    _doc(
        sp, "u1", ["Section 12. The term lasted. Section 13 follows. Section 14 ends."]
    )
    hits = search_fulltext(sp, r"Section \d+", regex=True, n=10)
    assert len(hits) == 3
    assert all(h.score is None for h in hits)
    assert all("Section" in h.snippet for h in hits)


def test_regex_respects_n_cap(tmp_path):
    sp = tmp_path / "set"
    _doc(sp, "u1", ["x x x x x x"])
    hits = search_fulltext(sp, "x", regex=True, n=2)
    assert len(hits) == 2


def test_regex_invalid_pattern_raises(tmp_path):
    sp = tmp_path / "set"
    _doc(sp, "u1", ["some text"])
    with pytest.raises(ValueError, match="Invalid regex"):
        search_fulltext(sp, "(unclosed", regex=True)


def test_literal_n_cap(tmp_path):
    sp = tmp_path / "set"
    for i in range(5):
        _doc(sp, f"u{i}", ["the common keyword appears here"])
    hits = search_fulltext(sp, "keyword", n=3)
    assert len(hits) == 3


def test_python_fallback_matches_grepper(tmp_path, monkeypatch):
    sp = tmp_path / "set"
    _doc(sp, "u1", ["The defendant was responsible for the safety inspections."])
    _doc(sp, "u2", ["Weather report: heavy rainfall over the northern coast."])
    # Force the no-grepper path.
    monkeypatch.setattr(fulltext, "_grepper", lambda: None)
    hits = search_fulltext(sp, "safety inspections", n=5)
    assert len(hits) == 1
    assert hits[0].uuid == "u1"
    assert hits[0].page == 1


def test_docs_without_label_typ_are_skipped(tmp_path):
    sp = tmp_path / "set"
    d = sp / "docs" / "u1"
    d.mkdir(parents=True)
    with (d / "info.yml").open("w", encoding="utf-8") as f:
        yaml.safe_dump({"uuid": "u1", "title": "No body"}, f)
    # No label.typ → nothing to search.
    assert search_fulltext(sp, "anything") == []
    assert search_fulltext(sp, "anything", regex=True) == []


def test_empty_set(tmp_path):
    assert search_fulltext(tmp_path / "set", "anything") == []
