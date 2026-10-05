"""Per-document operations (evid.services.doc_ops) and opening paths (evid.open_external)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import yaml

from evid.services import doc_ops
from evid.services.set_manager import SetManager

if TYPE_CHECKING:
    from pathlib import Path


def _write_doc(
    set_path: Path,
    uuid: str,
    label: str,
    time_added: str = "2024-01-01",
    tags: str = "",
) -> Path:
    doc = set_path / "docs" / uuid
    doc.mkdir(parents=True)
    (doc / "info.yml").write_text(
        yaml.safe_dump(
            {
                "uuid": uuid,
                "label": label,
                "title": label,
                "authors": "",
                "dates": "2024",
                "tags": tags,
                "url": "",
                "original_name": "original.pdf",
                "time_added": time_added,
            }
        ),
        encoding="utf-8",
    )
    (doc / "evid_meta.yml").write_text(
        yaml.safe_dump({"notes": "", "indexed": True}), encoding="utf-8"
    )
    (doc / "original.pdf").write_bytes(b"%PDF-1.4 stub")
    return doc


def test_collect_documents_sorted_newest_first(tmp_path):
    sm = SetManager(tmp_path)
    es = sm.create_set("Case")
    _write_doc(es.path, "a" * 32, "Older", "2024-01-01", "alpha")
    _write_doc(es.path, "b" * 32, "Newer", "2024-06-01", "alpha, beta")

    docs = doc_ops.collect_documents(sm, "case")
    assert [d.label for d in docs] == ["Newer", "Older"]
    assert docs[0].tags == ["alpha", "beta"]
    assert docs[0].indexed is True
    assert docs[0].uuid == "b" * 32


def test_collect_documents_skips_dirs_without_info_yml(tmp_path):
    sm = SetManager(tmp_path)
    es = sm.create_set("Case")
    _write_doc(es.path, "a" * 32, "PHD_ER_ONLINE")
    (es.path / "docs" / "sets").mkdir()
    assert [d.label for d in doc_ops.collect_documents(sm, "case")] == ["PHD_ER_ONLINE"]


def test_resolve_doc_pdf_uses_original_without_parsing_info(tmp_path, monkeypatch):
    """The canonical original.pdf short-circuits before any YAML parse."""
    from evid.services import doc_tags

    doc = tmp_path / "doc"
    doc.mkdir()
    (doc / "original.pdf").write_bytes(b"%PDF")
    (doc / "info.yml").write_text("original_name: other.pdf\n", encoding="utf-8")

    def _boom(*_args, **_kwargs):
        raise AssertionError("info.yml must not be parsed when original.pdf exists")

    monkeypatch.setattr(doc_tags, "load_yaml", _boom)
    assert doc_tags.resolve_doc_pdf(doc) == doc / "original.pdf"


def test_load_yaml_parses_like_safe_load():
    from evid.utils.yaml_io import load_yaml

    assert load_yaml("a: 1\nb: [x, y]\n") == {"a": 1, "b": ["x", "y"]}


def test_get_and_update_doc(tmp_path):
    sm = SetManager(tmp_path)
    es = sm.create_set("Case")
    d = _write_doc(es.path, "a" * 32, "Doc")
    got = doc_ops.get_doc(d)
    assert got["title"] == "Doc" and got["has_pdf"] and got["notes"] == ""
    out = doc_ops.update_doc(d, {"title": "  New  ", "notes": "why", "tags": "x, y"})
    assert out["title"] == "New" and out["notes"] == "why" and out["tags"] == "x, y"
    info = yaml.safe_load((d / "info.yml").read_text())
    assert info["time_added"] == "2024-01-01"  # untouched fields survive
    assert (
        doc_ops.update_doc(d, {"label": "L"})["notes"] == "why"
    )  # notes kept when absent


def test_doc_dir_of_rejects_paths(tmp_path):
    sm = SetManager(tmp_path)
    es = sm.create_set("Case")
    for bad in ("", "..", "a/b"):
        with pytest.raises(ValueError, match="bad document id"):
            doc_ops.doc_dir_of(es, bad)
    with pytest.raises(FileNotFoundError):
        doc_ops.doc_dir_of(es, "f" * 32)


def test_copy_doc_marks_unindexed_and_skips_existing(tmp_path):
    from evid.core.evid_meta import read_meta

    sm = SetManager(tmp_path)
    src_set, dest = sm.create_set("Case"), sm.create_set("Other")
    d = _write_doc(src_set.path, "a" * 32, "Doc")
    dest_dir, copied = doc_ops.copy_doc(d, dest)
    assert copied and (dest_dir / "original.pdf").exists()
    assert read_meta(dest_dir)["indexed"] is False
    assert doc_ops.copy_doc(d, dest) == (dest_dir, False)
    doc_ops.delete_doc(dest_dir)
    assert not dest_dir.exists() and d.exists()


def test_ensure_label_typ(tmp_path):
    import pymupdf

    d = tmp_path / "doc"
    d.mkdir()
    with pytest.raises(FileNotFoundError, match="No PDF"):
        doc_ops.ensure_label_typ(d)
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Body text here")
    pdf.save(str(d / "original.pdf"))
    typ = doc_ops.ensure_label_typ(d)
    assert typ.name == "label.typ" and "Body text here" in typ.read_text()
    (d / "label.typ").unlink()
    (d / "custom.typ").write_text("x")
    assert doc_ops.ensure_label_typ(d).name == "custom.typ"


# ── open_external ────────────────────────────────────────────────────────────


def test_open_local_path_missing(tmp_path):
    from evid.open_external import open_local_path

    err = open_local_path(tmp_path / "nope")
    assert err is not None and "does not exist" in err


def test_open_local_path_uses_editor_detached(tmp_path):
    from evid.open_external import open_local_path

    target = tmp_path / "file.typ"
    target.write_text("")
    with (
        patch("evid.open_external.shutil.which", return_value="/usr/bin/code"),
        patch("evid.open_external.subprocess.Popen") as popen,
    ):
        assert open_local_path(target, editor="code") is None
    popen.assert_called_once()
    assert popen.call_args[0][0] == ["/usr/bin/code", str(target.resolve())]
    assert popen.call_args.kwargs.get("start_new_session") is True


def test_open_local_path_falls_back_when_editor_missing(tmp_path):
    from evid.open_external import open_local_path

    target = tmp_path / "folder"
    target.mkdir()
    with (
        patch(
            "evid.open_external.shutil.which",
            side_effect=lambda n: "/usr/bin/xdg-open" if n == "xdg-open" else None,
        ),
        patch("evid.open_external.subprocess.Popen") as popen,
    ):
        assert open_local_path(target, editor="code") is None
    assert popen.call_args[0][0][0] == "/usr/bin/xdg-open"


def test_open_local_path_reports_when_all_handlers_fail(tmp_path):
    from evid.open_external import open_local_path

    target = tmp_path / "file.typ"
    target.write_text("")
    with (
        patch("evid.open_external.shutil.which", return_value=None),
        patch("evid.open_external.webbrowser.open", return_value=False),
    ):
        err = open_local_path(target, editor="code")
    assert err is not None and "Could not open" in err


def test_open_url_rejects_non_web(tmp_path):
    from evid.open_external import open_url

    assert "Not a web URL" in open_url("file:///etc/passwd")
