"""Tests for shared document loader / meta search."""

import yaml

from evid.core.doc_loader import load_document, search_meta_documents
from evid.core.evid_meta import write_meta


def test_search_meta_documents_substring(tmp_path):
    set_path = tmp_path / "sets" / "case"
    doc_dir = set_path / "docs" / "uuid-1"
    doc_dir.mkdir(parents=True)
    (doc_dir / "info.yml").write_text(
        yaml.safe_dump(
            {
                "uuid": "uuid-1",
                "title": "Wind turbine report",
                "label": "report",
                "tags": "",
                "url": "",
            }
        ),
        encoding="utf-8",
    )

    all_docs = search_meta_documents(set_path, "")
    assert len(all_docs) == 1

    hits = search_meta_documents(set_path, "turbine")
    assert len(hits) == 1
    assert hits[0].uuid == "uuid-1"

    misses = search_meta_documents(set_path, "solar")
    assert len(misses) == 0


def test_load_document_missing_info_yml(tmp_path):
    doc_dir = tmp_path / "docs" / "abc123"
    doc_dir.mkdir(parents=True)

    doc = load_document(doc_dir)
    assert doc.uuid == "abc123"
    assert doc.label == "abc123"
    assert doc.tags == []
    assert doc.path == doc_dir
    assert not doc.indexed


def test_load_document_label_and_tags(tmp_path):
    doc_dir = tmp_path / "docs" / "uuid-2"
    doc_dir.mkdir(parents=True)
    (doc_dir / "info.yml").write_text(
        yaml.safe_dump(
            {
                "uuid": "uuid-2",
                "label": "My Label",
                "tags": ["alpha", "beta"],
                "url": "https://example.com",
            }
        ),
        encoding="utf-8",
    )
    write_meta(doc_dir, {"notes": "hello", "indexed": True})

    doc = load_document(doc_dir, "uuid-2")
    assert doc.label == "My Label"
    assert doc.tags == ["alpha", "beta"]
    assert doc.source_url == "https://example.com"
    assert doc.indexed is True
    assert doc.notes == "hello"


def test_load_document_empty_label_falls_back_to_uuid(tmp_path):
    doc_dir = tmp_path / "docs" / "uuid-3"
    doc_dir.mkdir(parents=True)
    (doc_dir / "info.yml").write_text(
        yaml.safe_dump({"uuid": "uuid-3", "label": "", "tags": "a, b, c"}),
        encoding="utf-8",
    )

    doc = load_document(doc_dir)
    assert doc.label == "uuid-3"
    assert doc.tags == ["a", "b", "c"]
