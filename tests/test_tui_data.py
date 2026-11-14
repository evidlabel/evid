"""Headless tests for the TUI's data layer (the curses-less core).

Runs without a terminal: exercises set loading, quick addition (run_add) and
the curation mutations (metadata, tags, notes) against a temp data directory,
bypassing the GUI/CLI shell.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evid.tui import data


@pytest.fixture
def directory(tmp_path: Path) -> Path:
    return tmp_path / "db"


@pytest.fixture
def slug(directory: Path) -> str:
    from evid.services.set_manager import SetManager

    ev = SetManager(directory).create_set("Case Alpha", "normal")
    return ev.slug


def _pdf(path: Path, text: str = "Hello evid TUI test document.") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


def test_list_sets_empty(directory: Path):
    assert data.list_sets(directory) == []


def test_run_add_ok_and_lists(directory: Path, slug: str):
    pdf = _pdf(directory / "in" / "a.pdf")
    results = data.run_add(directory, slug, [str(pdf)])
    assert len(results) == 1
    assert results[0].ok is True, results[0].message
    assert results[0].uuid

    rows = data.list_docs(directory, slug)
    assert len(rows) == 1
    assert rows[0].uuid == results[0].uuid


def test_run_add_missing_file_fails_per_source(directory: Path, slug: str):
    results = data.run_add(directory, slug, [str(directory / "nope.pdf")])
    assert len(results) == 1
    assert results[0].ok is False


def test_batch_keeps_index_off_without_vec(directory: Path, slug: str):
    """Indexing is auto-off when evid[vec] is missing; batch must still succeed."""
    from evid import extras

    pdfs = [_pdf(directory / "in" / f"d{i}.pdf") for i in range(3)]
    if extras.has_vec():
        results = data.run_add(directory, slug, [str(p) for p in pdfs], do_index=False)
    else:
        results = data.run_add(directory, slug, [str(p) for p in pdfs])
    assert all(r.ok for r in results)
    assert len(data.list_docs(directory, slug)) == 3


def test_metadata_update_and_read(directory: Path, slug: str):
    pdf = _pdf(directory / "in" / "meta.pdf")
    res = data.run_add(directory, slug, [str(pdf)])
    uuid = res[0].uuid
    assert data.update_metadata(directory, uuid, {"title": "Ankerbrev"})[0]
    doc = data.list_docs(directory, slug)[0]
    assert doc.title == "Ankerbrev"


def test_assign_and_remove_tag(directory: Path, slug: str):
    pdf = _pdf(directory / "in" / "tag.pdf")
    uuid = data.run_add(directory, slug, [str(pdf)])[0].uuid
    ok, _ = data.assign_tag(directory, uuid, "court")
    assert ok
    tags = data.list_docs(directory, slug)[0].tags
    assert any(t.endswith(".court") for t in tags)
    ok2, _ = data.remove_tag(directory, uuid, "court")
    assert ok2
    assert not any(
        t.endswith(".court") for t in data.list_docs(directory, slug)[0].tags
    )


def test_set_note(directory: Path, slug: str):
    pdf = _pdf(directory / "in" / "note.pdf")
    uuid = data.run_add(directory, slug, [str(pdf)])[0].uuid
    assert data.set_note(directory, uuid, "Mød mig tirsdag.")[0]
    doc = data.list_docs(directory, slug)[0]
    assert "tirsdag" in doc.note


def test_metadata_on_add(directory: Path, slug: str):
    """doc-add metadata overrides are written over source-inferred values."""
    pdf = _pdf(directory / "in" / "meta2.pdf", "Evidence with metadata override.")
    res = data.run_add(
        directory,
        slug,
        [str(pdf)],
        title="Ankerbrev",
        authors="SKAT",
        dates="2026-01-02",
        url="https://e.dk/x",
    )
    assert res[0].ok and res[0].uuid
    doc = data.list_docs(directory, slug)[0]
    assert doc.title == "Ankerbrev"
    assert doc.authors == "SKAT"
    assert doc.dates == "2026-01-02"
    assert doc.url == "https://e.dk/x"


def test_cli_add_evidence_applies_metadata(directory: Path, slug: str):
    pdf = _pdf(directory / "in" / "meta3.pdf", "Another piece.")
    from evid.cli import evidence as evidence_mod

    evidence_mod.add_evidence(
        directory, slug, str(pdf), title="Klageskrivelse", authors="Borger X"
    )
    doc = data.list_docs(directory, slug)[0]
    assert doc.title == "Klageskrivelse"
    assert doc.authors == "Borger X"


def test_ambiguous_uuid_not_needed_for_full_uuid(directory: Path, slug: str):
    pdf = _pdf(directory / "in" / "full.pdf")
    uuid = data.run_add(directory, slug, [str(pdf)])[0].uuid
    assert data.uuid_dir(directory, uuid[:6]) is not None
