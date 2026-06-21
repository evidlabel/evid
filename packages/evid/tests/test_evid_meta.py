"""Tests for evid_meta sidecar read/write/migration."""

import yaml
from evid.core.evid_meta import META_CURRENT, META_LEGACY, read_meta, write_meta


def test_write_creates_evid_meta(tmp_path):
    doc_dir = tmp_path / "uuid"
    doc_dir.mkdir()
    write_meta(doc_dir, {"notes": "test", "indexed": True})
    assert (doc_dir / META_CURRENT).exists()
    assert not (doc_dir / META_LEGACY).exists()
    meta = read_meta(doc_dir)
    assert meta["notes"] == "test"
    assert meta["indexed"] is True


def test_read_legacy_and_migrate_on_write(tmp_path):
    doc_dir = tmp_path / "uuid"
    doc_dir.mkdir()
    (doc_dir / META_LEGACY).write_text(
        yaml.safe_dump({"notes": "legacy", "indexed": False}),
        encoding="utf-8",
    )
    assert read_meta(doc_dir)["notes"] == "legacy"
    write_meta(doc_dir, {"notes": "migrated", "indexed": True})
    assert (doc_dir / META_CURRENT).exists()
    assert not (doc_dir / META_LEGACY).exists()
    assert read_meta(doc_dir)["notes"] == "migrated"
