"""Headless GUI test for batch ingest — one dialog, many documents."""

from __future__ import annotations

import os

import pymupdf
import pytest

pytest.importorskip("PySide6")

pytestmark = pytest.mark.skipif(
    os.environ.get("CI") != "true" and os.environ.get("HEADLESS") != "1",
    reason="GUI tests require headless/CI env (set HEADLESS=1)",
)


@pytest.fixture(scope="module")
def qapp():
    import sys

    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


def _make_pdf(path, text: str) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


def _drain(qapp, tab) -> None:
    for worker in list(tab._workers):
        worker.wait(5000)
    for _ in range(5):
        qapp.processEvents()


def test_batch_ingest_adds_every_document(qapp, tmp_path, wait_for_docs):
    from evid.config import EvidConfig
    from evid.gui.main_window import EvidMgrWindow
    from evid.gui.tabs.docs_tab import BatchAddDialog

    config = EvidConfig(data_dir=tmp_path)
    window = EvidMgrWindow(config=config)
    evidence_set = window._set_manager.create_set("Batch")
    window._sidebar.refresh()
    window._sidebar.select_first()
    wait_for_docs(qapp, window._docs_tab)

    pdf_a = tmp_path / "a.pdf"
    pdf_b = tmp_path / "b.pdf"
    _make_pdf(pdf_a, "Alpha document body.")
    _make_pdf(pdf_b, "Beta document body.")

    dlg = BatchAddDialog([str(pdf_a), str(pdf_b)], window._docs_tab)
    dlg._tags_edit.setText("batch-tag")

    window._docs_tab._start_ingest(pdf_a, dlg)
    window._docs_tab._start_ingest(pdf_b, dlg)
    _drain(qapp, window._docs_tab)

    docs = list((evidence_set.path / "docs").iterdir())
    assert len(docs) == 2
    for doc_dir in docs:
        assert (doc_dir / "info.yml").exists()
        assert (doc_dir / "original.pdf").exists()

    window.close()


def test_batch_ingest_duplicate_is_not_added_twice(qapp, tmp_path, wait_for_docs):
    from evid.config import EvidConfig
    from evid.gui.main_window import EvidMgrWindow
    from evid.gui.tabs.docs_tab import BatchAddDialog

    config = EvidConfig(data_dir=tmp_path)
    window = EvidMgrWindow(config=config)
    evidence_set = window._set_manager.create_set("Dup")
    window._sidebar.refresh()
    window._sidebar.select_first()
    wait_for_docs(qapp, window._docs_tab)

    pdf = tmp_path / "same.pdf"
    _make_pdf(pdf, "Same content.")

    dlg = BatchAddDialog([str(pdf)], window._docs_tab)
    window._docs_tab._start_ingest(pdf, dlg)
    _drain(qapp, window._docs_tab)
    window._docs_tab._start_ingest(pdf, dlg)
    _drain(qapp, window._docs_tab)

    docs = list((evidence_set.path / "docs").iterdir())
    assert len(docs) == 1

    window.close()
