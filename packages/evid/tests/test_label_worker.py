"""Tests for LabelWorker and the .typ file-watching / label-regeneration pipeline."""

from __future__ import annotations

import os
import sys
from datetime import UTC
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import yaml
from PySide6.QtCore import Qt

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.skipif(
    os.environ.get("CI") != "true" and os.environ.get("HEADLESS") != "1",
    reason="GUI tests require headless/CI env (set HEADLESS=1)",
)


# ── shared fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


def _make_tab(tmp_path, qapp):
    """Construct a DocsTab inside a QMainWindow so statusBar() works."""
    from evid.config import EvidConfig
    from evid.gui.signals import AppSignals
    from evid.gui.tabs.docs_tab import DocsTab
    from evid.services.doc_ingester import DocIngester
    from evid.services.tag_service import TagService
    from evid.services.vec_service import VecService
    from PySide6.QtWidgets import QMainWindow

    EvidConfig(data_dir=tmp_path)  # ensure data_dir exists
    signals = AppSignals()
    tag_svc = TagService(tmp_path / "tags.yml")
    vec_svc = VecService()
    ingester = DocIngester(vec_service=vec_svc)

    tab = DocsTab(ingester, vec_svc, signals, tag_svc)
    mw = QMainWindow()
    mw.setCentralWidget(tab)
    # Store mw on tab so it isn't garbage-collected before the test finishes
    tab._mw = mw
    return tab, signals


def _make_doc_dir(es_path: Path, doc_uuid: str, with_typ: bool = True) -> Path:
    """Write a minimal doc directory under es_path/docs/<uuid>."""
    doc_dir = es_path / "docs" / doc_uuid
    doc_dir.mkdir(parents=True)
    info = {
        "label": "Test doc",
        "tags": "",
        "title": "Test Title",
        "authors": "Author A",
        "dates": "2024",
        "url": "",
    }
    with (doc_dir / "info.yml").open("w") as f:
        yaml.safe_dump(info, f)
    with (doc_dir / "evidmgr_meta.yml").open("w") as f:
        yaml.safe_dump({"notes": "", "indexed": False, "anon_pending": False}, f)
    if with_typ:
        (doc_dir / "label.typ").write_text("#show: doc => doc\n")
    return doc_dir


# ── LabelWorker unit tests ─────────────────────────────────────────────────────


def test_label_worker_emits_finished_on_success(qapp, tmp_path):
    """Emits finished(doc_uuid) when generate_bib_from_typ succeeds."""
    from evid.gui.workers import LabelWorker

    typ_path = tmp_path / "label.typ"
    typ_path.write_text('#lab("k", "text", "")\n')

    finished: list[str] = []
    errors: list[str] = []

    with patch(
        "evid.core.bibtex.generate_bib_from_typ", return_value=(True, "")
    ) as mock_fn:
        worker = LabelWorker(typ_path, "test-uuid-ok")
        worker.finished.connect(finished.append, Qt.ConnectionType.DirectConnection)
        worker.error.connect(errors.append, Qt.ConnectionType.DirectConnection)
        worker.start()
        worker.wait(5000)

    mock_fn.assert_called_once_with(typ_path)
    assert finished == ["test-uuid-ok"]
    assert errors == []


def test_label_worker_emits_error_on_failure(qapp, tmp_path):
    """Emits error when generate_bib_from_typ returns (False, message)."""
    from evid.gui.workers import LabelWorker

    typ_path = tmp_path / "label.typ"
    typ_path.write_text("")

    finished: list[str] = []
    errors: list[str] = []

    with patch(
        "evid.core.bibtex.generate_bib_from_typ",
        return_value=(False, "typst not found"),
    ):
        worker = LabelWorker(typ_path, "test-uuid-fail")
        worker.finished.connect(finished.append, Qt.ConnectionType.DirectConnection)
        worker.error.connect(errors.append, Qt.ConnectionType.DirectConnection)
        worker.start()
        worker.wait(5000)

    assert finished == []
    assert errors == ["typst not found"]


def test_label_worker_emits_error_on_exception(qapp, tmp_path):
    """Emits error when generate_bib_from_typ raises an exception."""
    from evid.gui.workers import LabelWorker

    typ_path = tmp_path / "label.typ"
    typ_path.write_text("")

    errors: list[str] = []

    with patch(
        "evid.core.bibtex.generate_bib_from_typ", side_effect=RuntimeError("boom")
    ):
        worker = LabelWorker(typ_path, "test-uuid-exc")
        worker.error.connect(errors.append, Qt.ConnectionType.DirectConnection)
        worker.start()
        worker.wait(5000)

    assert errors == ["boom"]


def test_label_worker_fallback_error_msg(qapp, tmp_path):
    """Uses fallback message when generate_bib_from_typ returns (False, '')."""
    from evid.gui.workers import LabelWorker

    typ_path = tmp_path / "label.typ"
    typ_path.write_text("")

    errors: list[str] = []

    with patch("evid.core.bibtex.generate_bib_from_typ", return_value=(False, "")):
        worker = LabelWorker(typ_path, "uuid-x")
        worker.error.connect(errors.append, Qt.ConnectionType.DirectConnection)
        worker.start()
        worker.wait(5000)

    assert errors == ["typst query failed"]


# ── DocsTab watcher registration ───────────────────────────────────────────────


def test_open_editor_registers_watcher(qapp, tmp_path):
    """_on_open_editor adds the .typ path to QFileSystemWatcher and _watched_typ."""
    from evid.services.set_manager import SetManager

    tab, _signals = _make_tab(tmp_path, qapp)
    sm = SetManager(tmp_path)
    es = sm.create_set("Watch Set")

    doc_uuid = "a" * 32
    doc_dir = _make_doc_dir(es.path, doc_uuid, with_typ=True)
    typ_path = str(doc_dir / "label.typ")

    from datetime import datetime

    from evid.models import Document

    doc = Document(
        uuid=doc_uuid,
        path=doc_dir,
        label="Test doc",
        tags=[],
        added=datetime.now(tz=UTC),
    )
    tab._docs = [doc]
    tab._evidence_set = es
    tab._refresh_table([doc])
    tab._table.selectRow(0)

    with patch("subprocess.Popen"):
        tab._on_label_doc()

    assert typ_path in tab._labeler._watcher.files()
    assert tab._labeler._watched[typ_path] == doc_uuid


def test_open_editor_no_typ_file_skips_watcher(qapp, tmp_path):
    """_on_open_editor does not touch watcher when no .typ file exists."""
    from datetime import datetime

    from evid.models import Document
    from evid.services.set_manager import SetManager

    tab, _signals = _make_tab(tmp_path, qapp)
    sm = SetManager(tmp_path)
    es = sm.create_set("No Typ Set")

    doc_uuid = "b" * 32
    doc_dir = _make_doc_dir(es.path, doc_uuid, with_typ=False)

    doc = Document(
        uuid=doc_uuid,
        path=doc_dir,
        label="No typ doc",
        tags=[],
        added=datetime.now(tz=UTC),
    )
    tab._docs = [doc]
    tab._evidence_set = es
    tab._refresh_table([doc])
    tab._table.selectRow(0)

    with patch("PySide6.QtWidgets.QMessageBox.warning"):
        tab._on_label_doc()

    assert tab._labeler._watched == {}


# ── _on_label_done signal propagation ─────────────────────────────────────────


def test_on_label_done_emits_labels_updated(qapp, tmp_path):
    """_on_label_done emits labels_updated(set_slug, doc_uuid)."""
    from evid.services.set_manager import SetManager

    tab, signals = _make_tab(tmp_path, qapp)
    sm = SetManager(tmp_path)
    es = sm.create_set("Signal Set")
    tab._evidence_set = es
    tab._docs = []

    emitted: list[tuple[str, str]] = []
    signals.labels_updated.connect(lambda s, u: emitted.append((s, u)))

    tab._on_label_done("my-doc-uuid")

    assert len(emitted) == 1
    assert emitted[0] == (es.slug, "my-doc-uuid")


def test_on_label_done_without_set_does_not_emit(qapp, tmp_path):
    """_on_label_done with no evidence_set does not emit labels_updated."""
    tab, signals = _make_tab(tmp_path, qapp)
    tab._evidence_set = None
    tab._docs = []

    emitted: list = []
    signals.labels_updated.connect(lambda s, u: emitted.append((s, u)))

    tab._on_label_done("some-uuid")

    assert emitted == []


# ── _on_typ_file_changed spawns worker ────────────────────────────────────────


def test_on_typ_file_changed_spawns_worker(qapp, tmp_path):
    """LabelController._on_file_changed starts a LabelWorker for a watched path."""
    tab, _signals = _make_tab(tmp_path, qapp)

    typ_path = tmp_path / "label.typ"
    typ_path.write_text("")
    tab._labeler._watched[str(typ_path)] = "uuid-spawn"

    initial_worker_count = len(tab._labeler._workers)

    with patch("evid.core.bibtex.generate_bib_from_typ", return_value=(True, "")):
        tab._labeler._on_file_changed(str(typ_path))
        for w in tab._labeler._workers[initial_worker_count:]:
            w.wait(5000)

    assert len(tab._labeler._workers) > initial_worker_count


def test_on_typ_file_changed_unknown_path_no_worker(qapp, tmp_path):
    """LabelController._on_file_changed ignores paths not in _watched."""
    tab, _signals = _make_tab(tmp_path, qapp)

    initial_worker_count = len(tab._labeler._workers)
    tab._labeler._on_file_changed("/nonexistent/label.typ")

    assert len(tab._labeler._workers) == initial_worker_count
