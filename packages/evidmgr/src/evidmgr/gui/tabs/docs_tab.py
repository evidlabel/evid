"""Docs tab — document list + detail pane."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from evidmgr.gui.signals import AppSignals
    from evidmgr.models import Document, EvidenceSet
    from evidmgr.services.doc_ingester import DocIngester
    from evidmgr.services.vec_service import VecService

logger = logging.getLogger(__name__)

_COLS = ["F", "J", "Label", "Type", "Added", "UUID"]


class DocsTab(QWidget):
    def __init__(
        self,
        ingester: "DocIngester",
        vec_service: "VecService",
        signals: "AppSignals",
    ) -> None:
        super().__init__()
        self._ingester = ingester
        self._vec_service = vec_service
        self._signals = signals
        self._evidence_set: "EvidenceSet | None" = None
        self._docs: list["Document"] = []
        self._workers: list = []  # keep workers alive

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── left: doc list ──────────────────────────────────────────────────
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        self._ingest_btn = QPushButton("Ingest PDF")
        self._ingest_btn.clicked.connect(self._on_ingest)
        self._open_editor_btn = QPushButton("Open .typ")
        self._open_editor_btn.clicked.connect(self._on_open_editor)
        self._add_prompt_btn = QPushButton("Add to Prompt")
        self._add_prompt_btn.clicked.connect(self._on_add_to_prompt)
        for btn in [self._ingest_btn, self._open_editor_btn, self._add_prompt_btn]:
            toolbar.addWidget(btn)
        toolbar.addStretch()
        lv.addLayout(toolbar)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter by label…")
        self._filter.textChanged.connect(self._apply_filter)
        lv.addWidget(self._filter)

        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(_COLS)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        lv.addWidget(self._table)

        splitter.addWidget(left)

        # ── right: detail pane ───────────────────────────────────────────────
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 0, 0, 0)

        self._detail_uuid = QLabel("—")
        self._detail_label = QLineEdit()
        self._detail_label.setPlaceholderText("Label")
        self._detail_notes = QTextEdit()
        self._detail_notes.setPlaceholderText("Notes…")
        self._detail_notes.setMaximumHeight(100)
        self._save_btn = QPushButton("Save changes")
        self._save_btn.clicked.connect(self._on_save_detail)

        rv.addWidget(QLabel("UUID:"))
        rv.addWidget(self._detail_uuid)
        rv.addWidget(QLabel("Label:"))
        rv.addWidget(self._detail_label)
        rv.addWidget(QLabel("Notes:"))
        rv.addWidget(self._detail_notes)
        rv.addWidget(self._save_btn)
        rv.addStretch()
        splitter.addWidget(right)
        splitter.setSizes([700, 300])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        signals.set_selected.connect(self._on_set_selected)

    # ── public ───────────────────────────────────────────────────────────────

    def reload(self, evidence_set: "EvidenceSet") -> None:
        self._evidence_set = evidence_set
        self._docs = self._load_documents()
        self._refresh_table(self._docs)

    # ── private ───────────────────────────────────────────────────────────────

    def _on_set_selected(self, slug: str) -> None:
        from evidmgr.services.set_manager import SetManager  # noqa: PLC0415
        # The sidebar already loaded the set; we need it from signals context
        # The main window passes itself; here we use the slug to find the parent
        parent = self.window()
        if hasattr(parent, "_set_manager"):
            try:
                es = parent._set_manager.load_set(slug)
                self.reload(es)
            except Exception:
                logger.exception("Failed to load set %s", slug)

    def _load_documents(self) -> list["Document"]:
        if self._evidence_set is None:
            return []
        from evidmgr.models import Document, SourceType  # noqa: PLC0415
        from datetime import datetime, timezone

        docs = []
        docs_dir = self._evidence_set.path / "docs"
        if not docs_dir.exists():
            return []
        for doc_dir in sorted(docs_dir.iterdir()):
            if not doc_dir.is_dir():
                continue
            try:
                info_path = doc_dir / "info.yml"
                meta_path = doc_dir / "evidmgr_meta.yml"
                info = {}
                if info_path.exists():
                    with info_path.open("r", encoding="utf-8") as f:
                        info = yaml.safe_load(f) or {}
                meta = {}
                if meta_path.exists():
                    with meta_path.open("r", encoding="utf-8") as f:
                        meta = yaml.safe_load(f) or {}
                tags_raw = info.get("tags", "")
                tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
                docs.append(
                    Document(
                        uuid=doc_dir.name,
                        path=doc_dir,
                        label=info.get("label", doc_dir.name),
                        tags=tags,
                        source_type=SourceType(meta.get("source_type", "other")),
                        added=datetime.now(tz=timezone.utc),
                        indexed=meta.get("indexed", False),
                        anon_pending=meta.get("anon_pending", False),
                        notes=meta.get("notes", ""),
                        source_url=info.get("url", ""),
                    )
                )
            except Exception:
                logger.exception("Failed to load doc at %s", doc_dir)
        return docs

    def _refresh_table(self, docs: list["Document"]) -> None:
        self._table.setRowCount(0)
        for doc in docs:
            row = self._table.rowCount()
            self._table.insertRow(row)
            has_file = (doc.path / "original.pdf").exists()
            has_json = (doc.path / "label.json").exists()
            self._table.setItem(row, 0, QTableWidgetItem("✓" if has_file else "✗"))
            self._table.setItem(row, 1, QTableWidgetItem("✓" if has_json else "✗"))
            self._table.setItem(row, 2, QTableWidgetItem(doc.label))
            self._table.setItem(row, 3, QTableWidgetItem(str(doc.source_type.value)))
            self._table.setItem(row, 4, QTableWidgetItem(doc.added.strftime("%Y-%m-%d")))
            self._table.setItem(row, 5, QTableWidgetItem(doc.uuid))
            for col in range(len(_COLS)):
                item = self._table.item(row, col)
                if item:
                    item.setData(Qt.ItemDataRole.UserRole, doc.uuid)

    def _apply_filter(self, text: str) -> None:
        text = text.lower()
        filtered = [d for d in self._docs if not text or text in d.label.lower()]
        self._refresh_table(filtered)

    def _selected_doc(self) -> "Document | None":
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        uuid_item = self._table.item(rows[0].row(), 5)
        if not uuid_item:
            return None
        doc_uuid = uuid_item.text()
        return next((d for d in self._docs if d.uuid == doc_uuid), None)

    def _on_selection_changed(self) -> None:
        doc = self._selected_doc()
        if doc:
            self._detail_uuid.setText(doc.uuid)
            self._detail_label.setText(doc.label)
            self._detail_notes.setPlainText(doc.notes)

    def _on_save_detail(self) -> None:
        doc = self._selected_doc()
        if not doc or not self._evidence_set:
            return
        meta_path = doc.path / "evidmgr_meta.yml"
        meta = {}
        if meta_path.exists():
            with meta_path.open("r", encoding="utf-8") as f:
                meta = yaml.safe_load(f) or {}
        meta["notes"] = self._detail_notes.toPlainText()
        with meta_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(meta, f, allow_unicode=True)
        # Update label in info.yml
        info_path = doc.path / "info.yml"
        if info_path.exists():
            with info_path.open("r", encoding="utf-8") as f:
                info = yaml.safe_load(f) or {}
            info["label"] = self._detail_label.text()
            with info_path.open("w", encoding="utf-8") as f:
                yaml.safe_dump(info, f, allow_unicode=True)
        self._docs = self._load_documents()
        self._refresh_table(self._docs)

    def _on_ingest(self) -> None:
        if not self._evidence_set:
            QMessageBox.warning(self, "No set", "Select an evidence set first.")
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select PDFs", "", "PDF files (*.pdf)"
        )
        if not paths:
            return
        for path_str in paths:
            self._start_ingest(Path(path_str))

    def _start_ingest(self, pdf_path: Path) -> None:
        from evidmgr.gui.workers import IngestWorker  # noqa: PLC0415

        progress_dlg = QProgressDialog(
            f"Ingesting {pdf_path.name}…", None, 0, 7, self
        )
        progress_dlg.setWindowTitle("Ingesting")
        progress_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dlg.show()

        worker = IngestWorker(self._ingester, pdf_path, self._evidence_set)
        worker.progress.connect(lambda step, total, msg: (
            progress_dlg.setValue(step),
            progress_dlg.setLabelText(msg),
        ))
        worker.finished.connect(lambda uuid: self._on_ingest_done(uuid, progress_dlg))
        worker.error.connect(lambda msg: self._on_ingest_error(msg, progress_dlg))
        self._workers.append(worker)
        worker.start()

    def _on_ingest_done(self, doc_uuid: str, dlg: QProgressDialog) -> None:
        dlg.close()
        if self._evidence_set:
            self._signals.doc_ingested.emit(self._evidence_set.slug, doc_uuid)
        self._docs = self._load_documents()
        self._refresh_table(self._docs)

    def _on_ingest_error(self, msg: str, dlg: QProgressDialog) -> None:
        dlg.close()
        QMessageBox.critical(self, "Ingest failed", msg)
        self._signals.ingestion_error.emit(msg)

    def _on_open_editor(self) -> None:
        doc = self._selected_doc()
        if not doc:
            return
        typ_files = list(doc.path.glob("*.typ"))
        if not typ_files:
            QMessageBox.information(self, "No .typ file", "No Typst file found for this document.")
            return
        from PySide6.QtGui import QDesktopServices  # noqa: PLC0415
        from PySide6.QtCore import QUrl  # noqa: PLC0415
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(typ_files[0])))

    def _on_add_to_prompt(self) -> None:
        doc = self._selected_doc()
        if doc and self._evidence_set:
            self._signals.add_to_prompt.emit(self._evidence_set.slug, doc.uuid)
