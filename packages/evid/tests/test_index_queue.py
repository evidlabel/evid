"""Tests for IndexQueueWorker — the serialized background vecdb index queue."""

from __future__ import annotations

import os
import sys

import pytest
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
