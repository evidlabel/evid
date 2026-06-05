"""Search tab — meta filter + vector search + tag action bar."""

from __future__ import annotations

import contextlib
import logging
import subprocess
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from evid.gui.signals import AppSignals
    from evid.models import Document, EvidenceSet, VecResult
    from evid.services.tag_service import TagService
    from evid.services.vec_service import VecService

logger = logging.getLogger(__name__)

_RESULT_COLS = ["Score", "Label", "Preview", "UUID"]


class SearchTab(QWidget):
    def __init__(
        self,
        vec_service: VecService,
        tag_service: TagService,
        signals: AppSignals,
    ) -> None:
        super().__init__()
        self._vec_service = vec_service
        self._tag_service = tag_service
        self._signals = signals
        self._evidence_set: EvidenceSet | None = None
        self._results: list[VecResult] = []
        self._meta_docs: list[Document] = []
        self._workers: list = []
        self._search_busy = False
        self._prev_current_uuid: str | None = None
        from evid.gui.label_controller import LabelController

        self._labeler = LabelController(self._get_editor, parent=self)
        self._labeler.label_updated.connect(self._on_label_done)
        self._labeler.label_error.connect(self._on_label_error)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Sub-tabs: Meta / Vector
        self._sub_tabs = QTabBar()
        self._sub_tabs.addTab("Meta search")
        self._sub_tabs.addTab("Vector search")
        self._sub_tabs.currentChanged.connect(self._on_sub_tab_changed)
        layout.addWidget(self._sub_tabs, 0)

        # Meta search area
        self._meta_widget = QWidget()
        mv = QVBoxLayout(self._meta_widget)
        mv.setContentsMargins(0, 0, 0, 0)
        self._meta_filter = QLineEdit()
        self._meta_filter.setPlaceholderText("Search info.yml (regex)…")
        self._meta_filter.returnPressed.connect(self._run_meta_search)
        self._meta_search_btn = QPushButton("Search")
        self._meta_search_btn.clicked.connect(self._run_meta_search)
        row = QHBoxLayout()
        row.addWidget(self._meta_filter)
        row.addWidget(self._meta_search_btn)
        mv.addLayout(row)
        layout.addWidget(self._meta_widget, 0)

        # Vector search area
        self._vec_widget = QWidget()
        vv = QVBoxLayout(self._vec_widget)
        vv.setContentsMargins(0, 0, 0, 0)
        qrow = QHBoxLayout()
        self._query_edit = QLineEdit()
        self._query_edit.setPlaceholderText("Semantic query…")
        self._query_edit.returnPressed.connect(self._run_vector_search)
        self._n_spin = QSpinBox()
        self._n_spin.setRange(1, 100)
        self._n_spin.setValue(10)
        self._n_spin.setPrefix("n=")
        self._vec_search_btn = QPushButton("Search")
        self._vec_search_btn.clicked.connect(self._run_vector_search)
        qrow.addWidget(self._query_edit)
        qrow.addWidget(self._n_spin)
        qrow.addWidget(self._vec_search_btn)
        vv.addLayout(qrow)
        layout.addWidget(self._vec_widget, 0)

        # Start on Vector search tab
        self._sub_tabs.setCurrentIndex(1)

        # Results table (multi-select, right-click menu)
        self._table = QTableWidget(0, len(_RESULT_COLS))
        self._table.setHorizontalHeaderLabels(_RESULT_COLS)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        label_col = _RESULT_COLS.index("Label")
        self._table.horizontalHeader().setSectionResizeMode(
            label_col, self._table.horizontalHeader().ResizeMode.Stretch
        )
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        self._table.itemSelectionChanged.connect(self._update_action_bar)
        self._table.itemSelectionChanged.connect(self._update_preview)

        # Left side: table + action bar
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)
        left_layout.addWidget(self._table)

        action_bar = QHBoxLayout()
        self._selected_count_label = QLabel("0 selected")
        action_bar.addWidget(self._selected_count_label)
        action_bar.addStretch()
        left_layout.addLayout(action_bar)

        # Horizontal splitter: table | preview
        content_splitter = QSplitter(Qt.Orientation.Horizontal)
        content_splitter.addWidget(left_widget)
        content_splitter.addWidget(self._build_preview_panel())
        content_splitter.setSizes([550, 450])
        layout.addWidget(content_splitter, 1)

        signals.set_selected.connect(self._on_set_selected)

    # ── preview panel ─────────────────────────────────────────────────────────

    def _build_preview_panel(self) -> QWidget:
        from evid.gui.theme import muted_label_stylesheet

        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(4, 0, 0, 0)
        pv.setSpacing(4)

        # ── header ────────────────────────────────────────────────────────────
        row0 = QHBoxLayout()
        row0.addWidget(QLabel("Tags:"))
        self._prev_tags = QLabel("")
        self._prev_tags.setWordWrap(True)
        self._prev_tags.setStyleSheet(muted_label_stylesheet())
        row0.addWidget(self._prev_tags, 1)
        pv.addLayout(row0)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Label:"))
        self._prev_label = QLabel("—")
        self._prev_label.setWordWrap(True)
        row1.addWidget(self._prev_label, 1)
        row1.addWidget(QLabel("Score:"))
        self._prev_score = QLabel("")
        self._prev_score.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        row1.addWidget(self._prev_score)
        pv.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("UUID:"))
        self._prev_uuid = QLabel("—")
        row2.addWidget(self._prev_uuid, 1)
        self._prev_view_btn = QPushButton("View")
        self._prev_view_btn.setFixedWidth(48)
        self._prev_view_btn.clicked.connect(self._on_preview_view)
        self._prev_copy_btn = QPushButton("Copy UUID")
        self._prev_copy_btn.setFixedWidth(80)
        self._prev_copy_btn.clicked.connect(self._on_preview_copy_uuid)
        self._prev_show_in_docs_btn = QPushButton("Show in Docs")
        self._prev_show_in_docs_btn.setEnabled(False)
        self._prev_show_in_docs_btn.clicked.connect(self._on_show_in_docs)
        row2.addWidget(self._prev_view_btn)
        row2.addWidget(self._prev_copy_btn)
        row2.addWidget(self._prev_show_in_docs_btn)
        pv.addLayout(row2)

        # ── chunk content ─────────────────────────────────────────────────────
        self._prev_text = QTextEdit()
        self._prev_text.setReadOnly(True)
        self._prev_text.setPlaceholderText("Select a result to preview")
        pv.addWidget(self._prev_text, 1)

        # ── footer ────────────────────────────────────────────────────────────
        self._prev_footer = QLabel("")
        self._prev_footer.setStyleSheet(muted_label_stylesheet())
        pv.addWidget(self._prev_footer)

        return panel

    # ── private ───────────────────────────────────────────────────────────────

    def _on_set_selected(self, slug: str) -> None:
        parent = self.window()
        if hasattr(parent, "_set_manager"):
            try:
                self._evidence_set = parent._set_manager.load_set(slug)
            except Exception:
                logger.exception("Failed to load set %s", slug)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._focus_query()

    def _focus_query(self) -> None:
        if self._sub_tabs.currentIndex() == 0:
            self._meta_filter.setFocus()
        else:
            self._query_edit.setFocus()

    def _on_sub_tab_changed(self, idx: int) -> None:
        self._meta_widget.setVisible(idx == 0)
        self._vec_widget.setVisible(idx == 1)
        self._focus_query()

    def _run_meta_search(self) -> None:
        if not self._evidence_set or self._search_busy:
            return
        from evid.gui.workers import MetaSearchWorker

        pattern = self._meta_filter.text().strip()
        self._set_search_busy(True)
        worker = MetaSearchWorker(self._evidence_set, pattern)
        worker.finished.connect(self._on_meta_search_done)
        worker.error.connect(self._on_search_error)
        self._workers.append(worker)
        worker.start()

    def _on_meta_search_done(self, docs: list) -> None:
        try:
            self._fill_table_from_docs(docs)
        finally:
            self._set_search_busy(False)

    def _run_vector_search(self) -> None:
        if not self._evidence_set:
            QMessageBox.warning(self, "No set", "Select an evidence set first.")
            return
        if self._search_busy:
            return
        query = self._query_edit.text().strip()
        if not query:
            return
        from evid.gui.workers import VectorSearchWorker

        self._set_search_busy(True)
        worker = VectorSearchWorker(
            self._vec_service,
            self._evidence_set,
            query,
            self._n_spin.value(),
        )
        worker.finished.connect(self._on_vector_search_done)
        worker.error.connect(self._on_search_error)
        self._workers.append(worker)
        worker.start()

    def _on_vector_search_done(self, results: list) -> None:
        try:
            self._results = results
            self._fill_table_from_vec_results(self._results)
        finally:
            self._set_search_busy(False)

    def _on_search_error(self, msg: str) -> None:
        self._set_search_busy(False)
        logger.error("Search failed: %s", msg)
        QMessageBox.critical(self, "Search failed", msg)

    def _set_search_busy(self, busy: bool) -> None:
        self._search_busy = busy
        self._meta_search_btn.setEnabled(not busy)
        self._meta_filter.setEnabled(not busy)
        self._vec_search_btn.setEnabled(not busy)
        self._query_edit.setEnabled(not busy)
        self._n_spin.setEnabled(not busy)

    def _fill_table_from_docs(self, docs: list[Document]) -> None:
        self._results = []
        self._meta_docs = list(docs)
        self._table.setRowCount(0)
        if not docs:
            self._table.insertRow(0)
            empty = QTableWidgetItem("(No matching documents)")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._table.setItem(0, 1, empty)
            self._clear_preview()
            return
        for doc in docs:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem("—"))
            self._table.setItem(row, 1, QTableWidgetItem(doc.label))
            self._table.setItem(row, 2, QTableWidgetItem(""))
            self._table.setItem(row, 3, QTableWidgetItem(doc.uuid))
        self._clear_preview()

    def _fill_table_from_vec_results(self, results: list[VecResult]) -> None:
        self._meta_docs = []
        self._table.setRowCount(0)
        if not results:
            self._table.insertRow(0)
            empty = QTableWidgetItem("(No results)")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self._table.setItem(0, 1, empty)
            self._clear_preview()
            return
        for res in results:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(f"{res.score:.3f}"))
            self._table.setItem(row, 1, QTableWidgetItem(res.doc.label))
            preview = res.chunk_text[:120].replace("\n", " ")
            self._table.setItem(row, 2, QTableWidgetItem(preview))
            self._table.setItem(row, 3, QTableWidgetItem(res.doc.uuid))
        self._clear_preview()

    def _update_action_bar(self) -> None:
        n = len(self._table.selectionModel().selectedRows())
        self._selected_count_label.setText(f"{n} selected")

    def _update_preview(self) -> None:
        row = self._table.currentRow()

        if row >= 0 and row < len(self._results):
            res = self._results[row]
            doc = res.doc
            self._prev_tags.setText(", ".join(doc.tags) if doc.tags else "—")
            self._prev_label.setText(doc.label)
            self._prev_label.setToolTip(doc.label)
            self._prev_score.setText(f"{res.score:.3f}")
            short_uuid = (
                doc.uuid[:8] + "\u2026" + doc.uuid[-8:]
                if len(doc.uuid) > 16
                else doc.uuid
            )
            self._prev_uuid.setText(short_uuid)
            self._prev_uuid.setToolTip(doc.uuid)
            self._prev_current_uuid = doc.uuid
            self._prev_text.setPlainText(
                res.chunk_text or self._citations_preview(doc.uuid)
            )
            self._prev_footer.setText(
                f"Source: {doc.label[:60]}    \u2003Chunk {res.chunk_idx}"
            )
            self._prev_show_in_docs_btn.setEnabled(True)
        elif row >= 0 and row < len(self._meta_docs):
            doc = self._meta_docs[row]
            self._prev_tags.setText(", ".join(doc.tags) if doc.tags else "—")
            self._prev_label.setText(doc.label)
            self._prev_label.setToolTip(doc.label)
            self._prev_score.setText("")
            short_uuid = (
                doc.uuid[:8] + "\u2026" + doc.uuid[-8:]
                if len(doc.uuid) > 16
                else doc.uuid
            )
            self._prev_uuid.setText(short_uuid)
            self._prev_uuid.setToolTip(doc.uuid)
            self._prev_current_uuid = doc.uuid
            self._prev_text.setPlainText(self._citations_preview(doc.uuid))
            self._prev_footer.setText("")
            self._prev_show_in_docs_btn.setEnabled(True)
        else:
            self._clear_preview()

    def _citations_preview(self, uuid: str) -> str:
        """Render a doc's labelled citations as markdown for the preview pane."""
        if not self._evidence_set:
            return ""
        from evid.core.prompt import quotes_markdown

        md = quotes_markdown([self._evidence_set.path / "docs" / uuid])
        return md or "(no citations — document not yet labelled)"

    def _clear_preview(self) -> None:
        self._prev_tags.setText("—")
        self._prev_label.setText("—")
        self._prev_label.setToolTip("")
        self._prev_score.setText("")
        self._prev_uuid.setText("—")
        self._prev_uuid.setToolTip("")
        self._prev_current_uuid = None
        self._prev_text.setPlainText("")
        self._prev_footer.setText("")
        self._prev_show_in_docs_btn.setEnabled(False)

    def _on_show_in_docs(self) -> None:
        if self._prev_current_uuid:
            self._signals.doc_navigate.emit(self._prev_current_uuid)

    def _on_preview_view(self) -> None:
        row = self._table.currentRow()
        doc = None
        if row >= 0 and row < len(self._results):
            doc = self._results[row].doc
        elif row >= 0 and row < len(self._meta_docs):
            doc = self._meta_docs[row]
        if doc is None:
            return
        if doc.source_url:
            QDesktopServices.openUrl(QUrl(doc.source_url))
            return
        from evid.services.doc_tags import resolve_doc_pdf

        pdf = resolve_doc_pdf(doc.path)
        if pdf:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(pdf)))

    def _on_preview_copy_uuid(self) -> None:
        if self._prev_current_uuid:
            QApplication.clipboard().setText(self._prev_current_uuid)

    def _selected_uuids(self) -> list[str]:
        rows = self._table.selectionModel().selectedRows()
        uuids = []
        for row_idx in rows:
            item = self._table.item(row_idx.row(), 3)
            if item:
                uuids.append(item.text())
        return uuids

    def _selected_docs_info(self) -> list[tuple[str, object]]:
        """Return [(uuid, doc_or_None)] for selected rows, in row order."""
        rows = sorted(
            {idx.row() for idx in self._table.selectionModel().selectedRows()}
        )
        result = []
        for row in rows:
            uuid_item = self._table.item(row, 3)
            if not uuid_item:
                continue
            uuid = uuid_item.text()
            doc = None
            if row < len(self._results):
                doc = self._results[row].doc
            elif row < len(self._meta_docs):
                doc = self._meta_docs[row]
            result.append((uuid, doc))
        return result

    def _on_context_menu(self, pos) -> None:
        sel = self._selected_docs_info()
        if not sel:
            return
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        single = len(sel) == 1
        uuid0, doc0 = sel[0]

        if single:
            act_label = menu.addAction("Label")
            act_open_dir = menu.addAction("Open folder")
            doc_dir = (
                self._evidence_set.path / "docs" / uuid0 if self._evidence_set else None
            )
            act_open_pdf = menu.addAction("Open PDF")
            from evid.services.doc_tags import resolve_doc_pdf

            act_open_pdf.setEnabled(
                bool(doc_dir and resolve_doc_pdf(doc_dir) is not None)
            )
            act_open_url = menu.addAction("Open URL")
            act_open_url.setEnabled(bool(doc0 and getattr(doc0, "source_url", "")))
            menu.addSeparator()
        else:
            act_label = act_open_dir = act_open_pdf = act_open_url = None

        uuids = [u for u, _ in sel]
        act_tag = menu.addAction(f"Tag {len(uuids)} selected\u2026")

        all_tags = sorted({t for _, d in sel if d for t in getattr(d, "tags", [])})
        tag_actions: dict = {}
        if all_tags:
            remove_menu = menu.addMenu("Remove tag")
            tag_actions = {remove_menu.addAction(t): t for t in all_tags}

        menu.addSeparator()
        if single:
            act_copy_uuid = menu.addAction("Copy UUID")
            menu.addSeparator()
        else:
            act_copy_uuid = None
        act_copy_prompt = menu.addAction(
            "Copy quotes to clipboard"
            if single
            else f"Copy quotes ({len(uuids)}) to clipboard"
        )

        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action is None:
            return

        if action is act_label:
            self._label_doc(uuid0)
        elif action is act_open_dir:
            self._open_dir(uuid0)
        elif action is act_open_pdf and doc_dir:
            from evid.services.doc_tags import resolve_doc_pdf

            pdf = resolve_doc_pdf(doc_dir)
            if pdf:
                subprocess.Popen(["xdg-open", str(pdf)])
        elif action is act_open_url and doc0:
            QDesktopServices.openUrl(QUrl(doc0.source_url))
        elif action is act_tag:
            if not self._evidence_set:
                return
            from evid.services.doc_tags import assign_doc_tag

            tag_name = self._ask_tag_name()
            if not tag_name:
                return
            tag_name = self._tag_service.qualify(tag_name, self._evidence_set.slug)
            for uuid in uuids:
                info_path = self._evidence_set.path / "docs" / uuid / "info.yml"
                try:
                    assign_doc_tag(
                        self._tag_service,
                        self._evidence_set.slug,
                        uuid,
                        info_path,
                        tag_name,
                    )
                except Exception:
                    logger.exception("Failed to assign tag to %s", uuid)
            self.window().statusBar().showMessage(
                f"{len(uuids)} docs tagged '{tag_name}'", 3000
            )
        elif action in tag_actions:
            tag_name = tag_actions[action]
            for uuid, doc in sel:
                if doc and tag_name in getattr(doc, "tags", []):
                    self._remove_tag_from_uuid(tag_name, uuid)
            self.window().statusBar().showMessage(
                f"Removed tag '{tag_name}' from {len(uuids)} doc(s)", 3000
            )
        elif action is act_copy_uuid:
            QApplication.clipboard().setText(uuid0)
        elif action is act_copy_prompt:
            self._copy_prompt_to_clipboard(uuids)

    def _remove_tag_from_uuid(self, tag_name: str, uuid: str) -> None:
        from evid.services.doc_tags import remove_doc_tag

        if not self._evidence_set:
            return
        info_path = self._evidence_set.path / "docs" / uuid / "info.yml"
        try:
            remove_doc_tag(
                self._tag_service,
                self._evidence_set.slug,
                uuid,
                info_path,
                tag_name,
            )
        except Exception:
            logger.exception("Failed to remove tag %s from %s", tag_name, uuid)

    def _copy_prompt_to_clipboard(self, uuids: list[str]) -> None:
        if not self._evidence_set or not uuids:
            return
        from evid.core.prompt import quotes_markdown

        workdirs = [self._evidence_set.path / "docs" / u for u in uuids]
        md = quotes_markdown(workdirs)
        if not md:
            with contextlib.suppress(Exception):
                self.window().statusBar().showMessage(
                    "No labelled evidence in selection — nothing to copy", 3000
                )
            return
        QApplication.clipboard().setText(md)
        with contextlib.suppress(Exception):
            self.window().statusBar().showMessage(
                f"Prompt for {len(uuids)} doc(s) copied to clipboard", 3000
            )

    def _ask_tag_name(self) -> str:
        """Show a dialog with an editable combo of existing tags; return chosen name or ''."""
        existing: list[str] = []
        if self._evidence_set:
            existing = [t.name for t in self._tag_service.list_tags()]

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
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addRow(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return ""
        return combo.currentText().strip()

    def _open_dir(self, uuid: str) -> None:
        if not self._evidence_set:
            return
        doc_dir = self._evidence_set.path / "docs" / uuid
        try:
            subprocess.Popen(["xdg-open", str(doc_dir)])
        except Exception as exc:
            logger.warning("Could not open folder: %s", exc)

    def _label_doc(self, uuid: str) -> None:
        if not self._evidence_set:
            return
        doc_dir = self._evidence_set.path / "docs" / uuid
        self._labeler.label_doc(doc_dir, uuid)

    def _get_editor(self) -> str:
        parent = self.window()
        if hasattr(parent, "_config"):
            return parent._config.editor
        return "code"

    def _on_label_done(self, doc_uuid: str) -> None:
        with contextlib.suppress(Exception):
            self.window().statusBar().showMessage("Labels updated", 2000)

    def _on_label_error(self, msg: str) -> None:
        logger.warning("Label regeneration failed: %s", msg)
        with contextlib.suppress(Exception):
            self.window().statusBar().showMessage(
                f"Label compile failed: {msg[:120]}", 5000
            )
