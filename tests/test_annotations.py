"""Annotations on a document and the files in its folder (evid.core.annotations)."""

from __future__ import annotations

import pytest
import yaml

from evid.core.annotations import (
    ANNOTATIONS_FILE,
    doc_note,
    missing_targets,
    read_annotations,
    write_annotation,
)
from evid.core.evid_meta import read_meta, write_meta


@pytest.fixture
def doc(tmp_path):
    d = tmp_path / "doc"
    (d / "sub").mkdir(parents=True)
    (d / "original.pdf").write_bytes(b"%PDF")
    (d / "sub" / "scan.pdf").write_bytes(b"%PDF")
    write_meta(d, {"notes": "", "indexed": True})
    return d


def test_write_read_and_remove(doc):
    write_annotation(doc, "original.pdf", "Signed copy.")
    write_annotation(doc, ".", "Key exhibit.\nSecond line.")
    write_annotation(doc, "sub/scan.pdf", "Page 2 missing.")
    notes = read_annotations(doc)
    assert list(notes) == [".", "original.pdf", "sub/scan.pdf"]  # document first
    assert doc_note(doc) == "Key exhibit.\nSecond line."
    on_disk = yaml.safe_load((doc / ANNOTATIONS_FILE).read_text())
    assert on_disk["original.pdf"] == "Signed copy."
    write_annotation(doc, "original.pdf", "")
    write_annotation(doc, ".", "  ")
    assert read_annotations(doc) == {"sub/scan.pdf": "Page 2 missing."}
    write_annotation(doc, "sub/scan.pdf", "")
    assert not (doc / ANNOTATIONS_FILE).exists()  # no notes, no file


def test_paths_are_checked(doc):
    for bad in ("../x", "/etc/passwd", "sub/../../x"):
        with pytest.raises(ValueError, match="outside"):
            write_annotation(doc, bad, "x")
    with pytest.raises(FileNotFoundError):
        write_annotation(doc, "nope.pdf", "x")
    with pytest.raises(ValueError, match="annotations"):
        write_annotation(doc, ANNOTATIONS_FILE, "x")
    assert write_annotation(doc, "./original.pdf", "ok")["original.pdf"] == "ok"


def test_stale_notes_are_listed_and_removable(doc):
    write_annotation(doc, "sub/scan.pdf", "Old scan.")
    (doc / "sub" / "scan.pdf").unlink()
    notes = read_annotations(doc)
    assert missing_targets(doc, notes) == ["sub/scan.pdf"]
    assert write_annotation(doc, "sub/scan.pdf", "") == {}


def test_legacy_notes_string_is_the_document_note(doc):
    write_meta(doc, {"notes": "From the old notes field.", "indexed": True})
    assert read_annotations(doc) == {".": "From the old notes field."}
    write_annotation(doc, ".", "Rewritten.")
    assert read_meta(doc)["notes"] == ""  # the legacy string does not come back
    assert doc_note(doc) == "Rewritten."
    write_annotation(doc, ".", "")
    assert doc_note(doc) == ""


def test_multiline_notes_are_yaml_blocks(doc):
    write_annotation(doc, ".", "Final decision.\nAppeal deadline passed.")
    text = (doc / ANNOTATIONS_FILE).read_text()
    assert ".: |-\n  Final decision.\n  Appeal deadline passed.\n" in text
    assert read_annotations(doc)["."] == "Final decision.\nAppeal deadline passed."
