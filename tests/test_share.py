"""`evid set share` writes a gzipped catalog of public urls and labels."""

from __future__ import annotations

import gzip
import hashlib
import json

import pytest
import yaml

import evid.cli.callbacks as cb
from evid.core.share import build_share, share_url
from evid.services.set_manager import SetManager


def _doc(set_path, uuid, **info):
    doc = set_path / "docs" / uuid
    doc.mkdir(parents=True)
    (doc / "info.yml").write_text(
        yaml.safe_dump({"uuid": uuid, **info}), encoding="utf-8"
    )
    return doc


def _labels(doc, **lists):
    label = doc / "label"
    label.mkdir(exist_ok=True)
    (label / "labels.json").write_text(
        json.dumps({"schema": 1, **lists}), encoding="utf-8"
    )


def test_share_url_keeps_public_addresses_and_drops_the_rest():
    assert share_url(" https://example.com/a.pdf ") == "https://example.com/a.pdf"
    assert share_url("https://user:secret@example.com/a.pdf") == (
        "https://example.com/a.pdf"
    )
    assert share_url("") == ""
    assert share_url("file:///tmp/scan.pdf") == ""
    assert share_url("/home/wr1/scan.pdf") == ""


def test_share_keeps_public_docs_with_hashes_and_drops_the_rest(tmp_path):
    sm = SetManager(tmp_path)
    case = sm.create_set("Case")
    public = _doc(
        case.path,
        "pub",
        title="Judgment",
        authors=["A", "B"],
        dates="2018",
        tags="court, exhibit",
        label="Judgment",
        url="https://user:secret@example.com/decision.pdf",
        source_name="decision.pdf",
    )
    (public / "original.pdf").write_bytes(b"%PDF-public")
    text = "The court holds that the words stand."
    (public / "label").mkdir()
    (public / "label" / "text.txt").write_text(
        text + "\n\nThis sentence is the rest of the extract.", encoding="utf-8"
    )
    text_sha = hashlib.sha256((public / "label" / "text.txt").read_bytes()).hexdigest()
    (public / "label" / "pages.json").write_text(
        json.dumps({"schema": 1, "sha256": text_sha, "pages": [[0, 1]]}),
        encoding="utf-8",
    )
    _labels(
        public,
        labels=[
            {
                "key": "holding",
                "start": 0,
                "end": 38,
                "page": 1,
                "text": text,
                "prefix": "",
                "suffix": "\n\n",
                "created": "2026-01-01T00:00:00+00:00",
                "by": "you",
                "notes": [
                    {
                        "at": "2026-01-01T00:00:00+00:00",
                        "by": "you",
                        "text": "the holding",
                    }
                ],
            }
        ],
        annotations=[
            {
                "id": "abc",
                "start": 0,
                "end": 3,
                "page": 1,
                "text": "The",
                "notes": [{"at": "t", "by": "you", "text": "margin"}],
            }
        ],
        document=[
            {
                "id": "doc1",
                "kind": "label",
                "key": "exhibit",
                "created": "2026-01-02T00:00:00+00:00",
                "by": "you",
                "notes": [{"at": "t", "by": "you", "text": "whole doc"}],
                "start": 5,
            }
        ],
    )
    _doc(case.path, "local", title="Scan", url="", label="Scan")
    (case.path / "docs" / "local" / "original.pdf").write_bytes(b"%PDF-private")
    _doc(case.path, "disk", title="Filing", url="file:///tmp/filing.pdf")

    catalog, dropped = build_share(case.path, "case")
    assert dropped == 2
    assert [d["uuid"] for d in catalog["docs"]] == ["pub"]
    doc = catalog["docs"][0]
    assert doc["url"] == "https://example.com/decision.pdf"
    assert doc["title"] == "Judgment"
    assert doc["authors"] == "A, B"
    assert doc["tags"] == ["court", "exhibit"]
    assert doc["source_name"] == "decision.pdf"
    assert doc["pdf_sha256"] == hashlib.sha256(b"%PDF-public").hexdigest()
    assert doc["text_sha256"] == text_sha
    assert doc["labels"][0]["key"] == "holding"
    assert doc["labels"][0]["text"] == text
    assert doc["labels"][0]["notes"][0]["text"] == "the holding"
    assert doc["annotations"][0]["id"] == "abc"
    assert doc["document"] == [
        {
            "id": "doc1",
            "kind": "label",
            "key": "exhibit",
            "created": "2026-01-02T00:00:00+00:00",
            "by": "you",
            "notes": [{"at": "t", "by": "you", "text": "whole doc"}],
        }
    ]
    assert "start" not in doc["document"][0]
    raw = json.dumps(catalog)
    assert "secret" not in raw
    assert "%PDF-private" not in raw
    assert "rest of the extract" not in raw
    assert catalog["schema"] == 1 and catalog["kind"] == "evid-share"
    assert catalog["set"] == "case" and catalog["name"] == "Case"


def test_text_hash_is_taken_from_text_when_pages_json_has_none(tmp_path):
    sm = SetManager(tmp_path)
    case = sm.create_set("Case")
    doc = _doc(case.path, "pub", title="Note", url="https://example.com/n")
    label = doc / "label"
    label.mkdir()
    (label / "text.txt").write_bytes(b"only the extract")
    catalog, dropped = build_share(case.path, "case")
    assert dropped == 0
    assert (
        catalog["docs"][0]["text_sha256"]
        == hashlib.sha256(b"only the extract").hexdigest()
    )
    assert "pdf_sha256" not in catalog["docs"][0]


def test_share_command_writes_gzip(tmp_path, monkeypatch, capsys):
    sm = SetManager(tmp_path)
    case = sm.create_set("Case")
    _doc(case.path, "pub", title="Judgment", url="https://example.com/a.pdf")
    _doc(case.path, "local", title="Scan", url="")
    monkeypatch.setattr(cb, "DIRECTORY", tmp_path)
    dest = tmp_path / "out" / "case.json.gz"
    cb.share_callback(dataset="case", output=str(dest))
    assert dest.is_file()
    catalog = json.loads(gzip.decompress(dest.read_bytes()))
    assert [d["uuid"] for d in catalog["docs"]] == ["pub"]
    assert (
        capsys.readouterr().out
        == f"Wrote {dest} (1 document(s), 1 without a public URL left out).\n"
    )
    with pytest.raises(SystemExit, match="--output"):
        cb.share_callback(dataset="case")
