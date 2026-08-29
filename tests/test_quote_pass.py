"""Tests for the machine-pass ledger (non-citable job records)."""

import json
from datetime import UTC, datetime

import yaml

from evid.core.quote_extract import (
    QuoteCandidate,
    extract_quotes,
    load_quotes_json,
)
from evid.core.quote_pass import (
    list_passes,
    load_pass,
    pass_summaries,
    record_pass,
    resolve_pass_meta,
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


def test_record_pass_writes_timestamped_json(tmp_path):
    doc = tmp_path / "doc"
    doc.mkdir()
    when = datetime(2026, 8, 14, 10, 22, 3, tzinfo=UTC)
    path = record_pass(
        doc,
        job="share of male vs female victims",
        model="grok-4.6",
        quotes=[QuoteCandidate(candidate="approx wording")],
        results=[],
        now=when,
    )
    assert path.parent == doc / "machine"
    assert path.name.startswith("2026-08-14T10-22-03Z_")
    assert path.suffix == ".json"

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["timestamp"] == "2026-08-14T10:22:03Z"
    assert data["id"] == path.stem
    assert data["job"] == "share of male vs female victims"
    assert isinstance(data["job"], str)
    assert data["model"] == "grok-4.6"
    assert data["schema"] == 1
    assert "evid_version" in data
    assert data["quotes"][0]["candidate"] == "approx wording"
    # Job is a description, not a structured kind/n/embedding blob.
    assert "kind" not in data
    assert "embedding_model" not in data
    assert not isinstance(data["job"], dict)


def test_record_pass_includes_skipped_results_without_haya(tmp_path):
    doc = tmp_path / "doc"
    doc.mkdir()
    from evid.core.quote_extract import QuoteResult

    path = record_pass(
        doc,
        job="unrelated astronomy",
        model=None,
        quotes=[QuoteCandidate(candidate="completely unrelated astronomy")],
        results=[
            QuoteResult(
                candidate="completely unrelated astronomy",
                matched=False,
                score=0.12,
            )
        ],
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["results"][0]["matched"] is False
    assert data["results"][0]["key"] is None
    assert data["results"][0]["score"] == 0.12
    assert not (doc / "machine.hayagriva").exists()
    # Verbatim quote body is not stored on the pass.
    assert "title" not in data["results"][0]
    assert "exact_quote" not in data["results"][0]


def test_extract_then_record_keeps_haya_citation_only(tmp_path):
    doc = _make_doc(tmp_path)
    cands = [QuoteCandidate(candidate="the appeal was dismissed in its entirety")]
    results = extract_quotes(doc, cands, min_ratio=0.6)
    record_pass(
        doc, job="appeal outcome", model="grok-4.6", quotes=cands, results=results
    )

    haya = yaml.safe_load((doc / "machine.hayagriva").read_text())
    dumped = yaml.safe_dump(haya)
    assert "grok-4.6" not in dumped
    assert "appeal outcome" not in dumped
    assert "job" not in haya
    assert "model" not in haya
    for item in haya.values():
        if isinstance(item, dict):
            assert "job" not in item
            assert "model" not in item

    passes = list_passes(doc)
    assert len(passes) == 1
    assert passes[0].job == "appeal outcome"
    assert passes[0].model == "grok-4.6"
    assert passes[0].results[0].matched is True
    assert passes[0].results[0].key == "1a2b:q1"


def test_list_passes_ordered_by_timestamp(tmp_path):
    doc = tmp_path / "doc"
    doc.mkdir()
    later = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)
    earlier = datetime(2026, 8, 14, 9, 0, 0, tzinfo=UTC)
    record_pass(doc, job="second", model=None, quotes=[], results=[], now=later)
    record_pass(doc, job="first", model=None, quotes=[], results=[], now=earlier)
    jobs = [p.job for p in list_passes(doc)]
    assert jobs == ["first", "second"]


def test_load_pass_roundtrip(tmp_path):
    doc = tmp_path / "doc"
    doc.mkdir()
    from evid.core.quote_extract import QuoteResult

    path = record_pass(
        doc,
        job="committee holding",
        model="grok-4.6",
        quotes=[QuoteCandidate(candidate="committee found", min_ratio=0.85)],
        results=[
            QuoteResult(
                candidate="committee found",
                matched=True,
                score=0.91,
                key="1a2b:q1",
                page=3,
            )
        ],
        now=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    )
    loaded = load_pass(path)
    assert loaded.job == "committee holding"
    assert loaded.model == "grok-4.6"
    assert loaded.quotes[0].min_ratio == 0.85
    assert loaded.results[0].key == "1a2b:q1"
    assert loaded.results[0].page == 3


def test_pass_file_is_valid_quotes_json_input(tmp_path):
    doc = tmp_path / "doc"
    doc.mkdir()
    path = record_pass(
        doc,
        job="replay me",
        model="grok-4.6",
        quotes=[
            QuoteCandidate(candidate="one"),
            QuoteCandidate(candidate="two", min_ratio=0.9),
        ],
        results=[],
    )
    qf = load_quotes_json(path)
    assert [c.candidate for c in qf.quotes] == ["one", "two"]
    assert qf.quotes[1].min_ratio == 0.9
    assert qf.job == "replay me"
    assert qf.model == "grok-4.6"


def test_load_quotes_json_accepts_job_and_model(tmp_path):
    p = tmp_path / "quotes.json"
    p.write_text(
        json.dumps(
            {
                "job": "find the committee holding",
                "model": "grok-4.6",
                "quotes": [{"candidate": "x"}],
            }
        ),
        encoding="utf-8",
    )
    qf = load_quotes_json(p)
    assert qf.job == "find the committee holding"
    assert qf.model == "grok-4.6"
    assert qf.quotes[0].candidate == "x"


def test_pass_summaries_omit_candidate_text(tmp_path):
    doc = tmp_path / "doc"
    doc.mkdir()
    record_pass(
        doc,
        job="victim share",
        model="grok-4.6",
        quotes=[QuoteCandidate(candidate="SECRET_CANDIDATE_TEXT")],
        results=[],
    )
    blob = json.dumps(pass_summaries(doc))
    assert "SECRET_CANDIDATE_TEXT" not in blob
    assert json.loads(blob)[0]["job"] == "victim share"
    assert json.loads(blob)[0]["matched"] == 0
    assert json.loads(blob)[0]["tried"] == 0


def test_resolve_pass_meta_flag_beats_search_beats_file(monkeypatch):
    monkeypatch.delenv("EVID_QUOTE_MODEL", raising=False)
    from evid.core.quote_extract import QuotesFile

    qf = QuotesFile(job="from file", model="file-model", quotes=[])
    job, model = resolve_pass_meta(
        job="from flag",
        model="flag-model",
        from_search="from search",
        quotes_file=qf,
    )
    assert job == "from flag"
    assert model == "flag-model"

    job, model = resolve_pass_meta(
        job=None, model=None, from_search="from search", quotes_file=qf
    )
    assert job == "from search"
    assert model == "file-model"

    job, model = resolve_pass_meta(
        job=None, model=None, from_search=None, quotes_file=qf
    )
    assert job == "from file"
    assert model == "file-model"


def test_resolve_pass_meta_env_model_last_resort(monkeypatch):
    monkeypatch.setenv("EVID_QUOTE_MODEL", "env-model")
    job, model = resolve_pass_meta(
        job=None, model=None, from_search=None, quotes_file=None
    )
    assert job is None
    assert model == "env-model"


def test_list_passes_empty_without_directory(tmp_path):
    assert list_passes(tmp_path / "missing") == []
    empty = tmp_path / "doc"
    empty.mkdir()
    assert list_passes(empty) == []


def test_extract_alone_does_not_write_a_pass(tmp_path):
    doc = _make_doc(tmp_path)
    extract_quotes(
        doc, [QuoteCandidate(candidate="the appeal was dismissed")], min_ratio=0.6
    )
    assert not (doc / "machine").exists()
