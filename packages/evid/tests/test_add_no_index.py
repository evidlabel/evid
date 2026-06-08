"""`doc add --no-index` skips the vector index entirely."""

import evid.services.doc_ingester as doc_ingester_mod
import evid.services.set_manager as sm_mod
import evid.services.vec_service as vec_mod
import fitz
from evid.cli.evidence import add_evidence


def _make_pdf(path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "The committee found the evidence conclusive.")
    doc.save(str(path))
    doc.close()


def test_no_index_does_not_instantiate_indexer(tmp_path, monkeypatch):
    pdf = tmp_path / "judgment.pdf"
    _make_pdf(pdf)

    calls = []

    class _Boom:
        def __init__(self, *_args, **_kwargs):
            calls.append(1)

    # Being constructed at all would mean indexing ran.
    monkeypatch.setattr(doc_ingester_mod, "DocIngester", _Boom)

    db = tmp_path / "db"
    add_evidence(db, "demo", str(pdf), no_index=True)

    assert calls == []
    docs = list((db / "sets" / "demo" / "docs").iterdir())
    assert len(docs) == 1
    assert (docs[0] / "info.yml").exists()


def test_indexing_runs_without_no_index(tmp_path, monkeypatch):
    pdf = tmp_path / "judgment.pdf"
    _make_pdf(pdf)

    calls = []

    class _Recorder:
        def __init__(self, *_args, **_kwargs):
            calls.append(1)

        def index_existing(self, *_args, **_kwargs):
            return None

    class _FakeSetManager:
        def __init__(self, *_args, **_kwargs):
            pass

        def load_set(self, _dataset):
            return object()

    monkeypatch.setattr(doc_ingester_mod, "DocIngester", _Recorder)
    monkeypatch.setattr(sm_mod, "SetManager", _FakeSetManager)
    monkeypatch.setattr(vec_mod, "VecService", lambda *_a, **_k: object())

    add_evidence(tmp_path / "db", "demo", str(pdf), no_index=False)
    assert calls == [1]
