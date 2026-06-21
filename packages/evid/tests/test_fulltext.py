"""Tests for full-text search over document bodies (fuzzy + regex)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from evid.core.fulltext import search_fulltext

if TYPE_CHECKING:
    from pathlib import Path


def _doc(set_path: Path, uuid: str, body: str, title: str = "Doc") -> Path:
    d = set_path / "docs" / uuid
    d.mkdir(parents=True)
    with (d / "info.yml").open("w", encoding="utf-8") as f:
        yaml.safe_dump({"uuid": uuid, "title": title}, f)
    (d / "body.txt").write_text(body, encoding="utf-8")
    return d


def test_fuzzy_ranks_matching_doc_first(tmp_path):
    sp = tmp_path / "set"
    _doc(
        sp,
        "u1",
        "The defendant was responsible for the safety inspections.",
        "Judgment",
    )
    _doc(sp, "u2", "Weather report: heavy rainfall over the northern coast.", "Weather")
    hits = search_fulltext(sp, "responsible for the safety inspections", n=5)
    assert hits
    assert hits[0].uuid == "u1"
    assert hits[0].score is not None
    assert hits[0].page == 1
    assert "safety inspections" in hits[0].snippet.lower()
    assert hits[0].label == "Judgment"


def test_fuzzy_threshold_excludes_unrelated(tmp_path):
    sp = tmp_path / "set"
    _doc(sp, "u1", "A short note about gardening tools and soil.")
    hits = search_fulltext(
        sp, "quantum chromodynamics lagrangian density", min_ratio=0.9
    )
    assert hits == []


def test_regex_returns_each_match(tmp_path):
    sp = tmp_path / "set"
    _doc(sp, "u1", "Section 12. The term lasted. Section 13 follows. Section 14 ends.")
    hits = search_fulltext(sp, r"Section \d+", regex=True, n=10)
    assert len(hits) == 3
    assert all(h.score is None for h in hits)
    assert all("Section" in h.snippet for h in hits)


def test_regex_respects_n_cap(tmp_path):
    sp = tmp_path / "set"
    _doc(sp, "u1", "x x x x x x")
    hits = search_fulltext(sp, "x", regex=True, n=2)
    assert len(hits) == 2


def test_regex_invalid_pattern_raises(tmp_path):
    sp = tmp_path / "set"
    _doc(sp, "u1", "some text")
    with pytest.raises(ValueError, match="Invalid regex"):
        search_fulltext(sp, "(unclosed", regex=True)


def test_docs_without_source_are_skipped(tmp_path):
    sp = tmp_path / "set"
    d = sp / "docs" / "u1"
    d.mkdir(parents=True)
    with (d / "info.yml").open("w", encoding="utf-8") as f:
        yaml.safe_dump({"uuid": "u1", "title": "No body"}, f)
    # No PDF or .txt source → nothing to extract.
    assert search_fulltext(sp, "anything") == []


def test_empty_set(tmp_path):
    assert search_fulltext(tmp_path / "set", "anything") == []
