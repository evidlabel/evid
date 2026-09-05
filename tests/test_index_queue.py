"""Tests for IndexQueueWorker — the serialized background vecdb index queue."""

from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt

pytestmark = pytest.mark.skipif(
    os.environ.get("CI") != "true" and os.environ.get("HEADLESS") != "1",
    reason="GUI tests require headless/CI env (set HEADLESS=1)",
)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


class _ES:
    """Minimal stand-in for an EvidenceSet."""

    slug = "demo"


def _patch_ingester(monkeypatch, recorder_cls):
    import evid.services.doc_ingester as di_mod
    import evid.services.vec_service as vec_mod

    monkeypatch.setattr(di_mod, "DocIngester", recorder_cls)
    monkeypatch.setattr(vec_mod, "VecService", lambda *_a, **_k: object())


def test_queue_processes_jobs_in_order(qapp, tmp_path, monkeypatch):
    """Enqueued docs are indexed one at a time, in FIFO order, once each."""
    from evid.gui.workers import IndexQueueWorker

    calls: list[str] = []

    class _Recorder:
        def __init__(self, *_a, **_k):
            pass

        def index_existing(self, doc_dir, _evidence_set):
            calls.append(doc_dir.name)
            return True

    _patch_ingester(monkeypatch, _Recorder)

    es = _ES()
    done: list[tuple[str, str, bool]] = []
    worker = IndexQueueWorker()
    worker.item_done.connect(
        lambda s, u, ok: done.append((s, u, ok)), Qt.ConnectionType.DirectConnection
    )
    worker.start()

    dirs = [tmp_path / "docs" / (c * 32) for c in "abc"]
    for d in dirs:
        worker.enqueue(d, es)
    worker.stop()
    worker.wait(5000)

    expected = [d.name for d in dirs]
    assert calls == expected
    assert [u for _, u, _ in done] == expected
    assert all(ok for *_, ok in done)


def test_queue_reports_failure(qapp, tmp_path, monkeypatch):
    """A raising index_existing yields item_done(..., ok=False) and keeps going."""
    from evid.gui.workers import IndexQueueWorker

    class _Recorder:
        def __init__(self, *_a, **_k):
            pass

        def index_existing(self, doc_dir, _evidence_set):
            if doc_dir.name.startswith("a"):
                raise RuntimeError("boom")
            return True

    _patch_ingester(monkeypatch, _Recorder)

    es = _ES()
    done: list[tuple[str, str, bool]] = []
    worker = IndexQueueWorker()
    worker.item_done.connect(
        lambda s, u, ok: done.append((s, u, ok)), Qt.ConnectionType.DirectConnection
    )
    worker.start()

    bad = tmp_path / "docs" / ("a" * 32)
    good = tmp_path / "docs" / ("b" * 32)
    worker.enqueue(bad, es)
    worker.enqueue(good, es)
    worker.stop()
    worker.wait(5000)

    results = {u: ok for _, u, ok in done}
    assert results[bad.name] is False
    assert results[good.name] is True


def test_queue_emits_idle_when_drained(qapp, tmp_path, monkeypatch):
    """idle fires after the last queued job completes."""
    from evid.gui.workers import IndexQueueWorker

    class _Recorder:
        def __init__(self, *_a, **_k):
            pass

        def index_existing(self, _doc_dir, _evidence_set):
            return True

    _patch_ingester(monkeypatch, _Recorder)

    es = _ES()
    idle_count: list[int] = []
    worker = IndexQueueWorker()
    worker.idle.connect(
        lambda: idle_count.append(1), Qt.ConnectionType.DirectConnection
    )
    worker.start()

    worker.enqueue(tmp_path / "docs" / ("a" * 32), es)
    worker.enqueue(tmp_path / "docs" / ("b" * 32), es)
    worker.stop()
    worker.wait(5000)

    assert idle_count, "idle should fire at least once after the queue drains"


def _src_doc(tmp_path, uuid: str = "c" * 32):
    src = tmp_path / "src_docs" / uuid
    src.mkdir(parents=True)
    (src / "info.yml").write_text(
        "label: Memo\ntags: ''\ntitle: Memo\nauthors: ''\ndates: ''\nurl: ''\n",
        encoding="utf-8",
    )
    (src / "label.typ").write_text(
        "= Memo\n\nA base paragraph long enough to be indexed later.\n",
        encoding="utf-8",
    )
    return src


def test_copy_worker_does_not_index(qapp, tmp_path):
    """Copy is filesystem-only; the dest stays unindexed for the background queue."""
    from datetime import UTC, datetime

    from evid.core.evid_meta import read_meta
    from evid.gui.workers import CopyDocWorker
    from evid.models import EvidenceSet, SetType

    src = _src_doc(tmp_path)
    dest_path = tmp_path / "dest_set"
    (dest_path / "docs").mkdir(parents=True)
    dest = EvidenceSet(
        name="Dest",
        slug="dest",
        path=dest_path,
        set_type=SetType.NORMAL,
        created=datetime.now(tz=UTC),
    )

    worker = CopyDocWorker(src, dest)
    worker.run()

    dest_doc = dest_path / "docs" / src.name
    assert dest_doc.is_dir()
    assert (dest_doc / "label.typ").exists()
    assert read_meta(dest_doc)["indexed"] is False


def test_copy_enqueues_background_index(qapp, tmp_path):
    """After a copy, indexing goes through the serialized background queue."""
    from pathlib import Path

    from evid.config import EvidConfig
    from evid.core.evid_meta import read_meta
    from evid.gui.main_window import EvidMgrWindow

    config = EvidConfig(data_dir=tmp_path)
    window = EvidMgrWindow(config=config)
    dest_set = window._set_manager.create_set("Dest")
    uuid = "d" * 32
    src = _src_doc(tmp_path, uuid=uuid)

    enqueued: list[tuple[Path, str]] = []

    class _FakeQ:
        def enqueue(self, doc_dir, es):
            enqueued.append((Path(doc_dir), es.slug))

    window._docs_tab._index_queue = _FakeQ()
    window._docs_tab.start_copy_doc(src, dest_set)
    for w in list(window._docs_tab._workers):
        w.wait(5000)
    qapp.processEvents()

    dest_doc = dest_set.path / "docs" / uuid
    assert dest_doc.is_dir()
    assert read_meta(dest_doc)["indexed"] is False
    assert enqueued == [(dest_doc, dest_set.slug)]
    window.close()
