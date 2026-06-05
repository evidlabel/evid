"""Tests for unified doc tagging."""

import yaml
from evid.services.doc_tags import (
    assign_doc_tag,
    format_tags_field,
    parse_tags_field,
    remove_doc_tag,
    resolve_doc_pdf,
)
from evid.services.tag_service import TagService


def test_parse_and_format_tags():
    assert parse_tags_field("b, a, b") == ["a", "b"]
    assert format_tags_field(["b", "a"]) == "a, b"


def test_assign_updates_both_stores(tmp_path):
    set_slug = "case"
    doc_dir = tmp_path / "sets" / set_slug / "docs" / "uuid-1"
    doc_dir.mkdir(parents=True)
    info_path = doc_dir / "info.yml"
    info_path.write_text(
        yaml.safe_dump({"uuid": "uuid-1", "tags": ""}), encoding="utf-8"
    )

    ts = TagService(tmp_path)
    assert assign_doc_tag(ts, set_slug, "uuid-1", info_path, "case.priority") is True
    assert assign_doc_tag(ts, set_slug, "uuid-1", info_path, "case.priority") is False

    tag = ts.get_tag("case.priority")
    assert len(tag.items) == 1
    with info_path.open(encoding="utf-8") as f:
        assert "case.priority" in yaml.safe_load(f)["tags"]


def test_remove_updates_both_stores(tmp_path):
    set_slug = "case"
    doc_dir = tmp_path / "sets" / set_slug / "docs" / "uuid-1"
    doc_dir.mkdir(parents=True)
    info_path = doc_dir / "info.yml"
    info_path.write_text(
        yaml.safe_dump({"uuid": "uuid-1", "tags": "case.priority"}),
        encoding="utf-8",
    )

    ts = TagService(tmp_path)
    ts.create_tag("case.priority", set_slug)
    from evid.models import TagItem

    ts.add_items(
        "case.priority",
        [TagItem(set_slug=set_slug, doc_uuid="uuid-1")],
    )

    assert remove_doc_tag(ts, set_slug, "uuid-1", info_path, "case.priority") is True
    assert ts.get_tag("case.priority").items == []
    with info_path.open(encoding="utf-8") as f:
        assert yaml.safe_load(f)["tags"] == ""


def test_resolve_doc_pdf_original_name(tmp_path):
    doc_dir = tmp_path / "doc"
    doc_dir.mkdir()
    (doc_dir / "report.pdf").write_bytes(b"%PDF")
    (doc_dir / "info.yml").write_text(
        yaml.safe_dump({"original_name": "report.pdf"}), encoding="utf-8"
    )
    assert resolve_doc_pdf(doc_dir) == doc_dir / "report.pdf"


def test_resolve_doc_pdf_fallback_original(tmp_path):
    doc_dir = tmp_path / "doc"
    doc_dir.mkdir()
    (doc_dir / "original.pdf").write_bytes(b"%PDF")
    assert resolve_doc_pdf(doc_dir) == doc_dir / "original.pdf"
