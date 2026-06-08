"""Tests for machine quote extraction into machine.hayagriva."""

import json
from types import SimpleNamespace

import pytest
import yaml
from evid.core.quote_extract import (
    QuoteCandidate,
    candidates_from_search,
    extract_document_text,
    extract_quotes,
    load_quotes_json,
)

SOURCE = (
    "Page one introduction text about the dispute between the parties.\n"
    "After lengthy deliberation, the committee found that the evidence was "
    "conclusive and the defendant had acted in clear violation of the rules. "
    "The appeal was therefore dismissed in its entirety."
)


def _make_doc(tmp_path):
    doc = tmp_path / "1a2b3c4d5e6f"
    doc.mkdir()
    info = {
        "uuid": "1a2b3c4d5e6f",
        "title": "Test Judgment",
        "author": "Test Court",
        "dates": "1978-06-13",
        "url": "https://example.com/judgment",
    }
    (doc / "info.yml").write_text(yaml.safe_dump(info), encoding="utf-8")
    (doc / "source.txt").write_text(SOURCE, encoding="utf-8")
    return doc


def test_extract_writes_labquote_hayagriva(tmp_path):
    doc = _make_doc(tmp_path)
    cands = [
        QuoteCandidate(candidate="the committee found the evidence conclusive"),
        QuoteCandidate(candidate="the appeal was dismissed in its entirety"),
    ]
    results = extract_quotes(doc, cands, min_ratio=0.6)

    assert all(r.matched for r in results)
    assert [r.key for r in results] == ["1a2b:q1", "1a2b:q2"]

    mfile = doc / "machine.hayagriva"
    text = mfile.read_text(encoding="utf-8")
    assert "# verbatim, rapidfuzz-verified" in text
    assert "serial-number:" in text

    data = yaml.safe_load(text)
    assert "1a2b:main" in data
    assert "1a2b:q1" in data
    assert "1a2b:q2" in data
    # Verbatim quote lives in title and is a real substring of the source.
    q1 = data["1a2b:q1"]["title"]
    assert q1 in SOURCE
    # Page locator uses Hayagriva's standard `page-range` (a .txt source = page 1).
    assert data["1a2b:q1"]["page-range"] == "1"
    # text.txt cache was written.
    assert (doc / "text.txt").exists()


def test_extract_appends_monotonically(tmp_path):
    doc = _make_doc(tmp_path)
    extract_quotes(doc, [QuoteCandidate(candidate="the appeal was dismissed")], 0.6)
    extract_quotes(
        doc, [QuoteCandidate(candidate="committee found that the evidence")], 0.6
    )
    data = yaml.safe_load((doc / "machine.hayagriva").read_text())
    # main written once, q numbering continues.
    assert "1a2b:main" in data
    assert "1a2b:q1" in data
    assert "1a2b:q2" in data
    mains = [k for k in data if k.endswith(":main")]
    assert mains == ["1a2b:main"]


def test_low_confidence_candidate_skipped(tmp_path):
    doc = _make_doc(tmp_path)
    results = extract_quotes(
        doc,
        [QuoteCandidate(candidate="completely unrelated astronomy content")],
        min_ratio=0.95,
    )
    assert results[0].matched is False
    assert results[0].key is None
    assert not (doc / "machine.hayagriva").exists()


def test_load_quotes_json_rejects_yaml(tmp_path):
    yml = tmp_path / "quotes.yaml"
    yml.write_text("quotes:\n  - candidate: not json\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_quotes_json(yml)


def test_load_quotes_json_parses_json(tmp_path):
    p = tmp_path / "quotes.json"
    p.write_text(
        json.dumps(
            {"quotes": [{"candidate": "x"}, {"candidate": "y", "min_ratio": 0.9}]}
        ),
        encoding="utf-8",
    )
    qf = load_quotes_json(p)
    assert len(qf.quotes) == 2
    assert qf.quotes[1].min_ratio == 0.9


def test_extract_document_text_dehyphenates(tmp_path):
    doc = tmp_path / "1a2b3c4d5e6f"
    doc.mkdir()
    (doc / "info.yml").write_text(
        yaml.safe_dump({"uuid": "1a2b3c4d5e6f"}), encoding="utf-8"
    )
    (doc / "source.txt").write_text(
        "Tallene peger på en mar-\nkant frasortering af sager.", encoding="utf-8"
    )
    text, _ = extract_document_text(doc)
    assert "markant frasortering" in text
    # Cached text.txt is the de-hyphenated text (stable offsets for serial-number).
    assert "markant frasortering" in (doc / "text.txt").read_text(encoding="utf-8")


def _vr(uuid, chunk):
    return SimpleNamespace(doc=SimpleNamespace(uuid=uuid), chunk_text=chunk)


def test_candidates_from_search_filters_uuid_and_caps_n():
    results = [
        _vr("AAAA", "chunk a1"),
        _vr("BBBB", "other doc"),
        _vr("AAAA", "chunk a2"),
        _vr("AAAA", "chunk a3"),
    ]
    cands = candidates_from_search(results, "AAAA", n=2)
    assert [c.candidate for c in cands] == ["chunk a1", "chunk a2"]


def test_candidates_from_search_skips_empty_chunks():
    results = [_vr("AAAA", "   "), _vr("AAAA", "real chunk")]
    cands = candidates_from_search(results, "AAAA", n=5)
    assert [c.candidate for c in cands] == ["real chunk"]
