"""Provenance (url / authors / dates / title) for documents added from files.

A script that downloads a PDF itself and runs ``doc add <file>`` has the URL in
hand; evid must store it at creation, let a re-run backfill it, let ``doc meta``
fix it later, and say loudly when it is missing.
"""

from __future__ import annotations

import io
import json
import os

import pymupdf
import pytest
import yaml

from evid.cli import callbacks as cb
from evid.cli.dataset import require_tty
from evid.cli.evidence import add_evidence
from evid.core.gather import gather_dataset, missing_provenance
from evid.core.hayagriva_fields import (
    braced_names,
    hayagriva_author,
    hayagriva_author_field,
)
from evid.services.doc_ingester import ORIGIN_XATTR, origin_url
from evid.services.layout import find_set_dir
from tests.labelkit import label_doc


def _make_pdf(path, text="Henvendelse til udvalget om sagen.", author="Web Master"):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    doc.set_metadata({"author": author})
    doc.save(str(path))
    doc.close()
    return path


def _info(db, slug="demo"):
    (doc,) = (find_set_dir(db, slug) / "docs").iterdir()
    return doc, yaml.safe_load((doc / "info.yml").read_text(encoding="utf-8"))


# ── doc add ────────────────────────────────────────────────────────────────────


def test_file_add_stores_provenance_at_creation(tmp_path):
    pdf = _make_pdf(tmp_path / "Formålsparagraf.pdf")
    db = tmp_path / "db"
    add_evidence(
        db,
        "demo",
        str(pdf),
        no_index=True,
        url="https://www.ft.dk/samling/x.pdf",
        authors="{Folketinget}",
        dates="2026-06-22",
        title="Henvendelse fra Lena Michelsen",
    )
    _, info = _info(db)
    assert info["url"] == "https://www.ft.dk/samling/x.pdf"
    assert info["authors"] == "{Folketinget}"  # not the PDF's "Web Master"
    assert info["dates"] == "2026-06-22"
    assert info["title"] == info["label"] == "Henvendelse fra Lena Michelsen"


def test_readd_backfills_explicit_metadata(tmp_path, capsys):
    pdf = _make_pdf(tmp_path / "a.pdf")
    db = tmp_path / "db"
    add_evidence(db, "demo", str(pdf), no_index=True)
    assert "has no source URL" in capsys.readouterr().err
    add_evidence(db, "demo", str(pdf), no_index=True, url="https://example.org/a.pdf")
    out = capsys.readouterr()
    assert "already added" in out.out
    assert "url: '' -> 'https://example.org/a.pdf'" in out.out
    assert "has no source URL" not in out.err
    _, info = _info(db)
    assert info["url"] == "https://example.org/a.pdf"


def test_one_url_for_several_files_is_refused(tmp_path):
    a = _make_pdf(tmp_path / "a.pdf", text="first")
    b = _make_pdf(tmp_path / "b.pdf", text="second")
    with pytest.raises(SystemExit) as e:
        add_evidence(
            tmp_path / "db", "demo", [str(a), str(b)], no_index=True, url="https://x"
        )
    assert "one document" in str(e.value)


def test_origin_url_from_browser_xattr(tmp_path):
    pdf = _make_pdf(tmp_path / "a.pdf")
    assert origin_url(pdf) == ""
    try:
        os.setxattr(pdf, ORIGIN_XATTR, b"https://www.ft.dk/samling/y.pdf")
    except (OSError, AttributeError):
        pytest.skip("no user xattrs on this filesystem")
    assert origin_url(pdf) == "https://www.ft.dk/samling/y.pdf"
    db = tmp_path / "db"
    add_evidence(db, "demo", str(pdf), no_index=True)
    assert _info(db)[1]["url"] == "https://www.ft.dk/samling/y.pdf"


# ── doc meta ───────────────────────────────────────────────────────────────────


def test_doc_meta_show_set_clear_and_gather(tmp_path, monkeypatch, capsys, caplog):
    pdf = _make_pdf(tmp_path / "a.pdf", text="Henvendelse til udvalget om sagen.")
    add_evidence(tmp_path, "demo", str(pdf), no_index=True)
    doc, _ = _info(tmp_path)
    monkeypatch.setattr(cb, "DIRECTORY", tmp_path)
    capsys.readouterr()

    cb.meta_callback(dataset="demo", uuid=doc.name, format="json")
    shown = json.loads(capsys.readouterr().out)
    assert shown["authors"] == "Web Master" and shown["url"] == ""

    cb.meta_callback(
        dataset="demo", uuid=doc.name, authors="", url="https://example.org/a.pdf"
    )
    out = capsys.readouterr().out
    assert "authors: 'Web Master' -> ''" in out
    assert "url: '' -> 'https://example.org/a.pdf'" in out

    cb.meta_callback(dataset="demo", uuid=doc.name, url="https://example.org/a.pdf")
    assert "No change." in capsys.readouterr().out

    label_doc(doc, labels=[{"key": "k", "text": "a labelled passage"}])
    out_yml = tmp_path / "refs.yml"
    gather_dataset(tmp_path, "demo", out_yml)
    data = yaml.safe_load(out_yml.read_text(encoding="utf-8"))
    main = data[f"{doc.name[:6]}:main"]
    assert main["url"] == "https://example.org/a.pdf" and "author" not in main
    assert f"no author on {doc.name[:8]}" in caplog.text
    assert "no url" not in caplog.text


def test_doc_meta_is_in_the_tree():
    from evid.cli import main as m

    (doc,) = [g for g in m.app.subgroups if g.name == "doc"]
    (meta,) = [c for c in doc.commands if c.name == "meta"]
    flags = {f for o in meta.options for f in o.flags}
    assert {"-u", "--title", "--authors", "--dates", "--url", "-f"} <= flags


# ── gather ─────────────────────────────────────────────────────────────────────


def test_missing_provenance_counts_only_cited_docs(tmp_path):
    root = tmp_path / "sets" / "demo" / "docs"
    for uid, info, cited in (
        ("aaaaaaaa1111", {"url": "", "authors": "X", "dates": "2020"}, True),
        ("bbbbbbbb2222", {"url": "https://e", "authors": "", "dates": ""}, True),
        ("cccccccc3333", {"url": "", "authors": "", "dates": ""}, False),
    ):
        d = root / uid
        d.mkdir(parents=True)
        (d / "info.yml").write_text(
            yaml.safe_dump({"uuid": uid, "title": uid, **info}), encoding="utf-8"
        )
        label_doc(d, labels=[{"key": "k", "text": "cited text"}] if cited else ())
    from evid.core.gather import collect

    docs, _ = collect(root)
    assert missing_provenance(docs) == {
        "url": ["aaaaaaaa"],
        "author": ["bbbbbbbb"],
        "date": ["bbbbbbbb"],
    }


# ── authors ────────────────────────────────────────────────────────────────────


def test_braced_organisations_stay_whole():
    org = "{Institut for Menneskerettigheder, Danmark}"
    assert braced_names(org) == ["Institut for Menneskerettigheder, Danmark"]
    assert hayagriva_author(org) == "Institut for Menneskerettigheder, Danmark"
    assert hayagriva_author_field(org) == {
        "name": "Institut for Menneskerettigheder, Danmark"
    }
    assert hayagriva_author_field("{A, B}, {C}") == [{"name": "A, B"}, {"name": "C"}]
    # Not only braces: the ordinary rules apply.
    assert braced_names("{x} plus") == []
    assert hayagriva_author_field("Ann Berg, Carl Dahl") == "Ann Berg and Carl Dahl"


# ── no prompts without a terminal ──────────────────────────────────────────────


def test_no_prompt_without_a_tty(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    with pytest.raises(SystemExit) as e:
        require_tty("Select dataset", "Pass -s.")
    assert "not a terminal" in str(e.value) and "Pass -s." in str(e.value)

    _make_pdf(tmp_path / "a.pdf")
    add_evidence(tmp_path, "demo", str(tmp_path / "a.pdf"), no_index=True)
    monkeypatch.setattr(cb, "DIRECTORY", tmp_path)
    monkeypatch.delenv("EVID_SET", raising=False)
    with pytest.raises(SystemExit) as e:
        cb.quote_callback(from_path="c.json")
    assert "--dataset" in str(e.value) and "demo" in str(e.value)
    with pytest.raises(SystemExit) as e:
        cb.quote_callback(dataset="demo", from_path="c.json")
    assert "--uuid" in str(e.value)
