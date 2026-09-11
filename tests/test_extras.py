"""Optional extras: gui (PySide6) and vec (chromadb + sentence-transformers)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import yaml

from evid.models import Document


def test_require_vec_names_the_extra_when_missing(monkeypatch):
    from evid import extras

    monkeypatch.setattr(extras, "has_vec", lambda: False)
    with pytest.raises(ImportError, match=r"evid\[vec\]"):
        extras.require_vec()


def test_require_gui_names_the_extra_when_missing(monkeypatch):
    from evid import extras

    monkeypatch.setattr(extras, "has_gui", lambda: False)
    with pytest.raises(ImportError, match=r"evid\[gui\]"):
        extras.require_gui()


def test_vec_service_refuses_construct_without_extra(monkeypatch):
    from evid import extras
    from evid.services.vec_service import VecService

    monkeypatch.setattr(extras, "has_vec", lambda: False)
    with pytest.raises(ImportError, match=r"evid\[vec\]"):
        VecService()


def _make_pdf(path) -> None:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "The committee found the evidence conclusive.")
    doc.save(str(path))
    doc.close()


def test_add_skips_index_when_vec_extra_missing(tmp_path, monkeypatch):
    """Without evid[vec], doc add still ingests and never builds VecService."""
    import evid.cli.evidence as evidence_mod
    import evid.services.vec_service as vec_mod
    from evid import extras

    pdf = tmp_path / "judgment.pdf"
    _make_pdf(pdf)

    class _Boom:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("VecService should not be built without evid[vec]")

    monkeypatch.setattr(extras, "has_vec", lambda: False)
    monkeypatch.setattr(vec_mod, "VecService", _Boom)

    evidence_mod.add_evidence(tmp_path / "db", "demo", str(pdf), no_index=False)

    docs = list((tmp_path / "db" / "sets" / "demo" / "docs").iterdir())
    assert len(docs) == 1
    assert (docs[0] / "info.yml").exists()


def test_add_still_indexes_when_vec_extra_present(tmp_path, monkeypatch):
    """With evid[vec], doc add still constructs VecService (unless --no-index)."""
    import evid.cli.evidence as evidence_mod
    import evid.services.doc_ingester as doc_ingester_mod
    import evid.services.set_manager as sm_mod
    import evid.services.vec_service as vec_mod
    from evid import extras

    pdf = tmp_path / "judgment.pdf"
    _make_pdf(pdf)
    calls: list[dict] = []

    class _Recorder:
        def __init__(self, vec_service=None, **_kwargs):
            self.vec_service = vec_service
            self.last_was_existing = False
            calls.append({"vec_service": vec_service})

        def ingest_source(self, source, evidence_set, **kwargs):
            calls.append({"source": source, **kwargs})
            doc_dir = tmp_path / "fake_doc"
            doc_dir.mkdir(exist_ok=True)
            (doc_dir / "info.yml").write_text(
                "uuid: fake\ntitle: t\n", encoding="utf-8"
            )
            return Document(
                uuid="fake",
                path=doc_dir,
                label="t",
                tags=[],
                added=datetime.now(tz=UTC),
            )

    class _FakeSetManager:
        def __init__(self, *_args, **_kwargs):
            pass

        def load_set(self, _dataset):
            return object()

        def create_set(self, _dataset):
            return object()

    monkeypatch.setattr(extras, "has_vec", lambda: True)
    monkeypatch.setattr(doc_ingester_mod, "DocIngester", _Recorder)
    monkeypatch.setattr(sm_mod, "SetManager", _FakeSetManager)
    monkeypatch.setattr(vec_mod, "VecService", lambda *_a, **_k: "VEC")

    evidence_mod.add_evidence(tmp_path / "db", "demo", str(pdf), no_index=False)

    assert calls[0]["vec_service"] == "VEC"
    assert calls[1]["do_index"] is True


def test_mcp_omits_search_vec_without_extra(tmp_path, monkeypatch):
    import asyncio

    from evid import extras
    from evid.mcpserver import build_server
    from evid.services.set_manager import SetManager

    sm = SetManager(tmp_path)
    s = sm.create_set("My Case")
    doc_dir = s.path / "docs" / "u1"
    doc_dir.mkdir(parents=True)
    with (doc_dir / "info.yml").open("w", encoding="utf-8") as f:
        yaml.safe_dump({"uuid": "u1", "title": "Judgment 2024", "tags": "priority"}, f)

    monkeypatch.setattr(extras, "has_vec", lambda: False)
    m = build_server(tmp_path, "my-case")
    names = {t.name for t in asyncio.run(m.list_tools())}
    assert "search_vec" not in names
    assert names == {"search_text", "search_meta", "list_docs", "doc_quotes"}


def test_gui_callback_exits_with_extra_hint(monkeypatch, capsys):
    import evid.cli.callbacks as cb
    from evid import extras

    monkeypatch.setattr(extras, "has_gui", lambda: False)
    with pytest.raises(SystemExit) as ei:
        cb.gui_callback()
    assert ei.value.code == 1
    assert "evid[gui]" in capsys.readouterr().out


def test_search_vec_callback_exits_with_extra_hint(monkeypatch, capsys):
    import evid.cli.callbacks as cb
    from evid import extras

    monkeypatch.setattr(extras, "has_vec", lambda: False)
    with pytest.raises(SystemExit) as ei:
        cb.search_vec_callback(query="anything", dataset="demo")
    assert ei.value.code == 1
    err = capsys.readouterr()
    text = err.out + err.err
    assert "evid[vec]" in text
