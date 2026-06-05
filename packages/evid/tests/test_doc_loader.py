"""Tests for shared document loader / meta search."""

import yaml
from evid.core.doc_loader import search_meta_documents


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
