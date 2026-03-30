"""Tests for import_service — importing existing evid directories."""

from pathlib import Path

import yaml
import pytest

from evidmgr.services.import_service import (
    _is_uuid_dir,
    _scan_evid_dir,
    import_evid_dir,
    import_evid_dir_single,
)
from evidmgr.services.set_manager import SetManager


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_evid_doc(base: Path, uuid: str, label: str = "Test doc") -> Path:
    """Write a minimal evid UUID directory at base/uuid/."""
    doc_dir = base / uuid
    doc_dir.mkdir(parents=True)
    info = {
        "original_name": "test.pdf",
        "uuid": uuid,
        "time_added": "2024-01-01",
        "dates": "2024",
        "title": label,
        "authors": "Author A",
        "tags": "",
        "label": label,
        "url": "",
    }
    with (doc_dir / "info.yml").open("w") as f:
        yaml.safe_dump(info, f)
    # Dummy "original" file
    (doc_dir / "test.pdf").write_bytes(b"%PDF-1.4 fake")
    return doc_dir


def _make_evid_db(tmp_path: Path) -> Path:
    """Build a minimal evid db root with two datasets."""
    db = tmp_path / "evid_db"
    db.mkdir()
    # dataset1 with 2 docs
    ds1 = db / "dataset1"
    ds1.mkdir()
    _make_evid_doc(ds1, "aaa" + "0" * 29)
    _make_evid_doc(ds1, "bbb" + "0" * 29)
    # dataset2 with 1 doc
    ds2 = db / "dataset2"
    ds2.mkdir()
    _make_evid_doc(ds2, "ccc" + "0" * 29)
    return db


# ── tests ─────────────────────────────────────────────────────────────────────


def test_is_uuid_dir_positive(tmp_path):
    doc_dir = _make_evid_doc(tmp_path, "aaaa" + "0" * 28)
    assert _is_uuid_dir(doc_dir)


def test_is_uuid_dir_negative(tmp_path):
    plain_dir = tmp_path / "notadoc"
    plain_dir.mkdir()
    assert not _is_uuid_dir(plain_dir)


def test_scan_evid_dir(tmp_path):
    db = _make_evid_db(tmp_path)
    datasets = _scan_evid_dir(db)
    assert set(datasets.keys()) == {"dataset1", "dataset2"}
    assert len(datasets["dataset1"]) == 2
    assert len(datasets["dataset2"]) == 1


def test_import_evid_dir_creates_sets(tmp_path):
    db = _make_evid_db(tmp_path)
    sm = SetManager(tmp_path / "evidmgr")
    sets = import_evid_dir(db, sm)
    assert len(sets) == 2
    slugs = {s.slug for s in sets}
    assert "dataset1" in slugs
    assert "dataset2" in slugs


def test_import_evid_dir_copies_docs(tmp_path):
    db = _make_evid_db(tmp_path)
    sm = SetManager(tmp_path / "evidmgr")
    import_evid_dir(db, sm)
    docs = sm.list_documents("dataset1")
    assert len(docs) == 2


def test_import_evid_dir_writes_meta(tmp_path):
    db = _make_evid_db(tmp_path)
    sm = SetManager(tmp_path / "evidmgr")
    import_evid_dir(db, sm)
    docs = sm.list_documents("dataset1")
    for doc_dir in docs:
        meta_path = doc_dir / "evidmgr_meta.yml"
        assert meta_path.exists(), f"evidmgr_meta.yml missing in {doc_dir}"
        with meta_path.open() as f:
            meta = yaml.safe_load(f)
        assert "source_type" in meta
        assert meta["indexed"] is False


def test_import_evid_dir_preserves_info_yml(tmp_path):
    db = _make_evid_db(tmp_path)
    sm = SetManager(tmp_path / "evidmgr")
    import_evid_dir(db, sm)
    docs = sm.list_documents("dataset2")
    assert len(docs) == 1
    info_path = docs[0] / "info.yml"
    assert info_path.exists()
    with info_path.open() as f:
        info = yaml.safe_load(f)
    assert info["uuid"] == "ccc" + "0" * 29


def test_import_evid_dir_idempotent(tmp_path):
    """Importing the same dir twice should not raise and not duplicate docs."""
    db = _make_evid_db(tmp_path)
    sm = SetManager(tmp_path / "evidmgr")
    import_evid_dir(db, sm)
    import_evid_dir(db, sm)  # second import should be a no-op
    docs = sm.list_documents("dataset1")
    assert len(docs) == 2  # no duplicates


def test_import_evid_dir_single(tmp_path):
    db = _make_evid_db(tmp_path)
    sm = SetManager(tmp_path / "evidmgr")
    evidence_set = import_evid_dir_single(
        db / "dataset1", "My Dataset", sm, set_type="normal"
    )
    assert evidence_set.slug == "my-dataset"
    docs = sm.list_documents("my-dataset")
    assert len(docs) == 2


def test_import_evid_dir_single_no_docs_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    sm = SetManager(tmp_path / "evidmgr")
    with pytest.raises(ValueError, match="No evid document"):
        import_evid_dir_single(empty, "Empty", sm)


def test_import_evid_dir_empty_db_returns_empty(tmp_path):
    empty_db = tmp_path / "empty_db"
    empty_db.mkdir()
    sm = SetManager(tmp_path / "evidmgr")
    result = import_evid_dir(empty_db, sm)
    assert result == []


def test_import_anon_set_marks_anon_pending(tmp_path):
    db = _make_evid_db(tmp_path)
    sm = SetManager(tmp_path / "evidmgr")
    import_evid_dir(db, sm, set_type="anon")
    docs = sm.list_documents("dataset1")
    for doc_dir in docs:
        with (doc_dir / "evidmgr_meta.yml").open() as f:
            meta = yaml.safe_load(f)
        assert meta["anon_pending"] is True


def test_import_progress_callback_called(tmp_path):
    db = _make_evid_db(tmp_path)
    sm = SetManager(tmp_path / "evidmgr")
    calls = []
    import_evid_dir(db, sm, progress=lambda d, t, m: calls.append((d, t, m)))
    assert len(calls) > 0
