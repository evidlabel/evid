"""`doc add --no-index` skips the vector index entirely."""

from datetime import UTC, datetime
from pathlib import Path

import pymupdf

import evid.extras as extras_mod
import evid.services.doc_ingester as doc_ingester_mod
import evid.services.set_manager as sm_mod
import evid.services.vec_service as vec_mod
from evid.cli.evidence import add_evidence
from evid.models import Document


def _make_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "The committee found the evidence conclusive.")
    doc.save(str(path))
    doc.close()


def test_no_index_does_not_construct_vec_service(tmp_path, monkeypatch):
    """With --no-index, VecService must never be constructed."""
    pdf = tmp_path / "judgment.pdf"
    _make_pdf(pdf)

    class _Boom:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("VecService should not be built with --no-index")

    monkeypatch.setattr(vec_mod, "VecService", _Boom)

    db = tmp_path / "db"
    add_evidence(db, "demo", str(pdf), no_index=True)

    docs = list((db / "sets" / "demo" / "docs").iterdir())
    assert len(docs) == 1
    assert (docs[0] / "info.yml").exists()
    assert (docs[0] / "original.pdf").exists()


def test_indexing_runs_without_no_index(tmp_path, monkeypatch):
    """Without --no-index, DocIngester.ingest_source is used with do_index=True."""
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
            # Minimal Document so add_evidence can finish without real pipeline.
            doc_dir = Path(tmp_path) / "fake_doc"
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

    monkeypatch.setattr(doc_ingester_mod, "DocIngester", _Recorder)
    monkeypatch.setattr(sm_mod, "SetManager", _FakeSetManager)
    monkeypatch.setattr(vec_mod, "VecService", lambda *_a, **_k: "VEC")
    # add_evidence only builds VecService when the vec extra is present.
    monkeypatch.setattr(extras_mod, "has_vec", lambda: True)

    add_evidence(tmp_path / "db", "demo", str(pdf), no_index=False)
    assert any(c.get("vec_service") == "VEC" for c in calls)
    assert any(c.get("do_index") is True for c in calls)
