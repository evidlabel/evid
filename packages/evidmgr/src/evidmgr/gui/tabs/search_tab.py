"""Search tab — meta filter + vector search + tag action bar."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from evidmgr.gui.signals import AppSignals
    from evidmgr.models import EvidenceSet, VecResult
    from evidmgr.services.tag_service import TagService
    from evidmgr.services.vec_service import VecService

logger = logging.getLogger(__name__)

_RESULT_COLS = ["Score", "Label", "Preview", "UUID"]


class SearchTab(QWidget):
    def __init__(
        self,
        vec_service: "VecService",
        tag_service: "TagService",
        signals: "AppSignals",
    ) -> None:
        super().__init__()
        self._vec_service = vec_service
        self._tag_service = tag_service
        self._signals = signals
        self._evidence_set: "EvidenceSet | None" = None
        self._results: list["VecResult"] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Sub-tabs: Meta / Vector
        self._sub_tabs = QTabBar()
        self._sub_tabs.addTab("Meta search")
        self._sub_tabs.addTab("Vector search")
        self._sub_tabs.currentChanged.connect(self._on_sub_tab_changed)
        layout.addWidget(self._sub_tabs)

        # Meta search area
        self._meta_widget = QWidget()
        mv = QVBoxLayout(self._meta_widget)
        mv.setContentsMargins(0, 0, 0, 0)
        self._meta_filter = QLineEdit()
        self._meta_filter.setPlaceholderText("Filter label (regex)…")
        self._meta_filter.returnPressed.connect(self._run_meta_search)
        self._meta_search_btn = QPushButton("Search")
        self._meta_search_btn.clicked.connect(self._run_meta_search)
        row = QHBoxLayout()
        row.addWidget(self._meta_filter)
        row.addWidget(self._meta_search_btn)
        mv.addLayout(row)
        layout.addWidget(self._meta_widget)

        # Vector search area
        self._vec_widget = QWidget()
        vv = QVBoxLayout(self._vec_widget)
        vv.setContentsMargins(0, 0, 0, 0)
        qrow = QHBoxLayout()
        self._query_edit = QLineEdit()
        self._query_edit.setPlaceholderText("Semantic query…")
        self._query_edit.returnPressed.connect(self._run_vector_search)
        self._n_spin = QSpinBox()
        self._n_spin.setRange(1, 50)
        self._n_spin.setValue(10)
        self._n_spin.setPrefix("n=")
        vec_btn = QPushButton("Search")
        vec_btn.clicked.connect(self._run_vector_search)
        qrow.addWidget(self._query_edit)
        qrow.addWidget(self._n_spin)
        qrow.addWidget(vec_btn)
        vv.addLayout(qrow)
        layout.addWidget(self._vec_widget)

        # Start on Vector search tab
        self._sub_tabs.setCurrentIndex(1)

        # Results table (multi-select, right-click menu)
        self._table = QTableWidget(0, len(_RESULT_COLS))
        self._table.setHorizontalHeaderLabels(_RESULT_COLS)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.itemSelectionChanged.connect(self._update_action_bar)
        layout.addWidget(self._table)

        # Action bar: selection count + export prompt
        action_bar = QHBoxLayout()
        self._selected_count_label = QLabel("0 selected")
        action_bar.addWidget(self._selected_count_label)
        action_bar.addStretch()
        layout.addLayout(action_bar)

        signals.set_selected.connect(self._on_set_selected)

    # ── private ───────────────────────────────────────────────────────────────

    def _on_set_selected(self, slug: str) -> None:
        parent = self.window()
        if hasattr(parent, "_set_manager"):
            try:
                self._evidence_set = parent._set_manager.load_set(slug)
            except Exception:
                logger.exception("Failed to load set %s", slug)

    def _on_sub_tab_changed(self, idx: int) -> None:
        self._meta_widget.setVisible(idx == 0)
        self._vec_widget.setVisible(idx == 1)

    def _run_meta_search(self) -> None:
        if not self._evidence_set:
            return
        import re  # noqa: PLC0415
        import yaml  # noqa: PLC0415
        from evidmgr.models import Document  # noqa: PLC0415
        from datetime import datetime, timezone

        pattern = self._meta_filter.text().strip()
        docs_dir = self._evidence_set.path / "docs"
        if not docs_dir.exists():
            return
        results = []
        for doc_dir in docs_dir.iterdir():
            if not doc_dir.is_dir():
                continue
            info_path = doc_dir / "info.yml"
            meta_path = doc_dir / "evidmgr_meta.yml"
            if not info_path.exists():
                continue
            with info_path.open("r", encoding="utf-8") as f:
                info = yaml.safe_load(f) or {}
            meta = {}
            if meta_path.exists():
                with meta_path.open("r", encoding="utf-8") as f:
                    meta = yaml.safe_load(f) or {}
            label = info.get("label", "")
            if pattern:
                try:
                    if not re.search(pattern, label, re.IGNORECASE):
                        continue
                except re.error:
                    if pattern.lower() not in label.lower():
                        continue
            tags_raw = info.get("tags", "")
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
            results.append(
                Document(
                    uuid=doc_dir.name,
                    path=doc_dir,
                    label=label,
                    tags=tags,
                    added=datetime.now(tz=timezone.utc),
                )
            )
        self._fill_table_from_docs(results)

    def _run_vector_search(self) -> None:
        if not self._evidence_set:
            QMessageBox.warning(self, "No set", "Select an evidence set first.")
            return
        query = self._query_edit.text().strip()
        if not query:
            return
        try:
            self._results = self._vec_service.query(
                self._evidence_set,
                query,
                n_results=self._n_spin.value(),
            )
            self._fill_table_from_vec_results(self._results)
        except Exception as exc:
            logger.error("Vector search failed: %s", exc)
            QMessageBox.critical(self, "Search failed", str(exc))

    def _fill_table_from_docs(self, docs) -> None:
        self._table.setRowCount(0)
        for doc in docs:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem("—"))
            self._table.setItem(row, 1, QTableWidgetItem(doc.label))
            self._table.setItem(row, 2, QTableWidgetItem(""))
            self._table.setItem(row, 3, QTableWidgetItem(doc.uuid))

    def _fill_table_from_vec_results(self, results: list["VecResult"]) -> None:
        self._table.setRowCount(0)
        for res in results:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(f"{res.score:.3f}"))
            self._table.setItem(row, 1, QTableWidgetItem(res.doc.label))
            preview = res.chunk_text[:120].replace("\n", " ")
            self._table.setItem(row, 2, QTableWidgetItem(preview))
            self._table.setItem(row, 3, QTableWidgetItem(res.doc.uuid))

    def _update_action_bar(self) -> None:
        n = len(self._table.selectionModel().selectedRows())
        self._selected_count_label.setText(f"{n} selected")

    def _selected_uuids(self) -> list[str]:
        rows = self._table.selectionModel().selectedRows()
        uuids = []
        for row_idx in rows:
            item = self._table.item(row_idx.row(), 3)
            if item:
                uuids.append(item.text())
        return uuids

    def _on_context_menu(self, pos) -> None:
        uuids = self._selected_uuids()
        if not uuids:
            return
        from PySide6.QtWidgets import QMenu  # noqa: PLC0415

        menu = QMenu(self)
        tag_action = menu.addAction(f"Tag {len(uuids)} selected\u2026")
        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action is not tag_action:
            return
        if not self._evidence_set:
            return
        from evidmgr.models import TagItem  # noqa: PLC0415

        tag_name = self._ask_tag_name()
        if not tag_name:
            return
        tag_name = self._tag_service.qualify(tag_name, self._evidence_set.slug)
        try:
            self._tag_service.get_tag(tag_name)
        except KeyError:
            self._tag_service.create_tag(tag_name, self._evidence_set.slug)
        items = [TagItem(set_slug=self._evidence_set.slug, doc_uuid=u) for u in uuids]
        self._tag_service.add_items(tag_name, items)
        self.window().statusBar().showMessage(f"{len(uuids)} docs added to {tag_name}", 3000)

    def _ask_tag_name(self) -> str:
        """Show a dialog with an editable combo of existing tags; return chosen name or ''."""
        existing: list[str] = []
        if self._evidence_set:
            existing = [
                t.name for t in self._tag_service.list_tags()
            ]

        dlg = QDialog(self)
        dlg.setWindowTitle("Tag selected")
        dlg.setMinimumWidth(280)
        layout = QFormLayout(dlg)
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.addItems(existing)
        combo.setCurrentText("")
        combo.lineEdit().setPlaceholderText("tag-name or pick existing…")
        layout.addRow("Tag:", combo)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addRow(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return ""
        return combo.currentText().strip()

