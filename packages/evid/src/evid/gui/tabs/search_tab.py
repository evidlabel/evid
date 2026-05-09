"""Search tab — meta filter + vector search + tag action bar."""

from __future__ import annotations

import contextlib
import logging
import subprocess
from datetime import UTC
from typing import TYPE_CHECKING

import yaml
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


def _add_token_to_layer_yaml(layers: list, layer_id: str, token: str) -> bool:
    """Recursively find layer by id in raw YAML dicts and append token to evidence."""
    for layer in layers:
        if layer.get("id") == layer_id:
            ev = layer.setdefault("evidence", [])
            if token not in ev:
                ev.append(token)
            return True
        if _add_token_to_layer_yaml(layer.get("layers", []), layer_id, token):
            return True
    return False


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
        vec_btn = QPushButton("Search")
        vec_btn.clicked.connect(self._run_vector_search)
        qrow.addWidget(self._query_edit)
        qrow.addWidget(self._n_spin)
        qrow.addWidget(vec_btn)
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
        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(4, 0, 0, 0)
        pv.setSpacing(4)

        # ── header ────────────────────────────────────────────────────────────
        row0 = QHBoxLayout()
        row0.addWidget(QLabel("Tags:"))
        self._prev_tags = QLabel("")
        self._prev_tags.setWordWrap(True)
        self._prev_tags.setStyleSheet("color: #aaa; font-size: 11px;")
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

        # ── add to prompt ─────────────────────────────────────────────────────
        self._add_to_prompt_btn = QPushButton("Add to Prompt")
        self._add_to_prompt_btn.clicked.connect(self._on_add_to_prompt)
        pv.addWidget(self._add_to_prompt_btn)

        # ── footer ────────────────────────────────────────────────────────────
        self._prev_footer = QLabel("")
        self._prev_footer.setStyleSheet("color: #888; font-size: 11px;")
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

    def showEvent(self, event) -> None:  # noqa: N802
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
        if not self._evidence_set:
            return
        import re
        from datetime import datetime

        from evid.core.models import InfoModel
        from evid.models import Document

        pattern = self._meta_filter.text().strip()
        docs_dir = self._evidence_set.path / "docs"
        if not docs_dir.exists():
            return
        results = []
        for doc_dir in sorted(docs_dir.iterdir()):
            if not doc_dir.is_dir():
                continue
            info_path = doc_dir / "info.yml"
            if not info_path.exists():
                continue
            try:
                with info_path.open("r", encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
                info = InfoModel(**raw)
            except Exception:
                logger.debug("Skipping bad info.yml in %s", doc_dir.name)
                continue

            # Search across all values in info.yml flattened to a single string
            haystack = " ".join(str(v) for v in raw.values() if v is not None)
            if pattern:
                try:
                    if not re.search(pattern, haystack, re.IGNORECASE):
                        continue
                except re.error:
                    if pattern.lower() not in haystack.lower():
                        continue

            tags = [t.strip() for t in info.tags.split(",") if t.strip()]
            results.append(
                Document(
                    uuid=info.uuid or doc_dir.name,
                    path=doc_dir,
                    label=info.title or info.label,
                    tags=tags,
                    added=datetime.now(tz=UTC),
                    source_url=info.url,
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

    def _fill_table_from_docs(self, docs: list[Document]) -> None:
        self._results = []
        self._meta_docs = list(docs)
        self._table.setRowCount(0)
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
            self._prev_text.setPlainText(res.chunk_text)
            self._prev_footer.setText(
                f"Source: {doc.label[:60]}    \u2003Chunk {res.chunk_idx}"
            )
            self._prev_show_in_docs_btn.setEnabled(True)
        elif row >= 0 and row < len(self._meta_docs):
            doc = self._meta_docs[row]
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
            self._prev_text.setPlainText("")
            self._prev_footer.setText("")
            self._prev_show_in_docs_btn.setEnabled(True)
        else:
            self._clear_preview()

    def _clear_preview(self) -> None:
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
        for candidate in [doc.path / "original.pdf", *doc.path.glob("*.pdf")]:
            if candidate.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(candidate)))
                return

    def _on_preview_copy_uuid(self) -> None:
        if self._prev_current_uuid:
            QApplication.clipboard().setText(self._prev_current_uuid)

    def _on_add_to_prompt(self) -> None:
        uuid = self._prev_current_uuid
        if not uuid:
            return
        self._add_uuid_to_prompt(uuid)
        with contextlib.suppress(Exception):
            self.window().statusBar().showMessage(
                f"Added {uuid[:8]}\u2026 to Prompt", 3000
            )

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
            act_open_pdf.setEnabled(
                bool(doc_dir and (doc_dir / "original.pdf").exists())
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
        act_add_prompt = menu.addAction(
            "Add to Prompt" if single else f"Add {len(uuids)} to Prompt"
        )

        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action is None:
            return

        if action is act_label:
            self._label_doc(uuid0)
        elif action is act_open_dir:
            self._open_dir(uuid0)
        elif action is act_open_pdf and doc_dir:
            subprocess.Popen(["xdg-open", str(doc_dir / "original.pdf")])
        elif action is act_open_url and doc0:
            QDesktopServices.openUrl(QUrl(doc0.source_url))
        elif action is act_tag:
            if not self._evidence_set:
                return
            from evid.models import TagItem

            tag_name = self._ask_tag_name()
            if not tag_name:
                return
            tag_name = self._tag_service.qualify(tag_name, self._evidence_set.slug)
            try:
                self._tag_service.get_tag(tag_name)
            except KeyError:
                self._tag_service.create_tag(tag_name, self._evidence_set.slug)
            self._tag_service.add_items(
                tag_name,
                [TagItem(set_slug=self._evidence_set.slug, doc_uuid=u) for u in uuids],
            )
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
        elif action is act_add_prompt:
            for uuid in uuids:
                self._add_uuid_to_prompt(uuid)

    def _remove_tag_from_uuid(self, tag_name: str, uuid: str) -> None:
        if not self._evidence_set:
            return
        try:
            self._tag_service.remove_item(tag_name, self._evidence_set.slug, uuid)
        except Exception:
            logger.debug("Tag %s not in TagService for %s", tag_name, uuid)
        info_path = self._evidence_set.path / "docs" / uuid / "info.yml"
        try:
            info: dict = {}
            if info_path.exists():
                with info_path.open("r", encoding="utf-8") as f:
                    info = yaml.safe_load(f) or {}
            existing = [t.strip() for t in info.get("tags", "").split(",") if t.strip()]
            if tag_name in existing:
                existing.remove(tag_name)
                info["tags"] = ", ".join(existing)
                with info_path.open("w", encoding="utf-8") as f:
                    yaml.safe_dump(info, f, allow_unicode=True)
        except Exception:
            logger.exception("Failed to remove tag from info.yml for %s", uuid)

    def _add_uuid_to_prompt(self, uuid: str) -> None:
        parent = self.window()
        prompt_tab = getattr(parent, "_prompt_tab", None)
        if prompt_tab is None or getattr(prompt_tab, "_recipe_path", None) is None:
            with contextlib.suppress(Exception):
                self.window().statusBar().showMessage(
                    "No recipe open in Prompts tab", 3000
                )
            return
        token = f"evid-{uuid}"
        recipe_path = prompt_tab._recipe_path
        current_item = prompt_tab._tree.currentItem()
        layer_id = (
            current_item.data(0, Qt.ItemDataRole.UserRole) if current_item else None
        )
        try:
            with recipe_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            layers = data.get("layers", [])
            if not layers:
                return
            if layer_id and _add_token_to_layer_yaml(layers, layer_id, token):
                pass
            else:
                layers[0].setdefault("evidence", [])
                if token not in layers[0]["evidence"]:
                    layers[0]["evidence"].append(token)
            with recipe_path.open("w", encoding="utf-8") as f:
                yaml.safe_dump(
                    data,
                    f,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                )
        except Exception:
            logger.exception("Failed to add %s to recipe", uuid)

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
