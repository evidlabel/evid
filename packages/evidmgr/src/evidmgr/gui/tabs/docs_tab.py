"""Docs tab — document list, metadata detail, and (for ANON sets) anonymisation controls."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QRadioButton,
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
    from evidmgr.services.tag_service import TagService
    from evidmgr.services.vec_service import VecService

logger = logging.getLogger(__name__)

_COLS = ["F", "J", "Label", "Added", "UUID"]
_ENTITY_COLS = ["Type", "Original", "Placeholder", "Fake", "Variants"]


# ── pre-ingest metadata dialog ────────────────────────────────────────────────


class AddDocDialog(QDialog):
    """Metadata dialog shown before a document is ingested."""

    def __init__(self, pdf_path: Path, parent=None, *, url: str = "", title: str = "", authors: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Add document")
        self.setMinimumWidth(540)

        self._pdf_path = pdf_path
        self._temp_dir: object = None

        layout = QVBoxLayout(self)

        file_row = QHBoxLayout()
        file_row.addWidget(QLabel("File:"))
        self._file_label = QLabel(str(pdf_path))
        self._file_label.setWordWrap(True)
        file_row.addWidget(self._file_label, 1)
        view_btn = QPushButton("View")
        view_btn.setFixedWidth(50)
        view_btn.clicked.connect(self._view_file)
        file_row.addWidget(view_btn)
        layout.addLayout(file_row)

        form = QFormLayout()
        self._title_edit   = QLineEdit()
        self._authors_edit = QLineEdit()
        self._dates_edit   = QLineEdit()
        self._tags_edit    = QLineEdit()
        self._tags_edit.setPlaceholderText("comma-separated")
        self._label_edit   = QLineEdit()
        self._url_edit     = QLineEdit(url)
        for w in (self._title_edit, self._authors_edit, self._dates_edit,
                  self._tags_edit, self._label_edit, self._url_edit):
            w.textChanged.connect(self._update_preview)

        # Tags: free-text field + combo picker for existing tags
        tags_widget = QWidget()
        tags_layout = QVBoxLayout(tags_widget)
        tags_layout.setContentsMargins(0, 0, 0, 0)
        tags_layout.setSpacing(2)
        tags_layout.addWidget(self._tags_edit)

        picker_row = QHBoxLayout()
        self._tag_picker = QComboBox()
        self._tag_picker.setEditable(True)
        self._tag_picker.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._tag_picker.lineEdit().setPlaceholderText("pick or type tag…")
        existing_tags: list[str] = []
        if hasattr(parent, "_tag_service"):
            existing_tags = [t.name for t in parent._tag_service.list_tags()]
        self._tag_picker.addItems(existing_tags)
        self._tag_picker.setCurrentText("")
        add_tag_btn = QPushButton("Add")
        add_tag_btn.setFixedWidth(40)
        add_tag_btn.clicked.connect(self._on_add_tag)
        self._tag_picker.lineEdit().returnPressed.connect(self._on_add_tag)
        picker_row.addWidget(self._tag_picker, 1)
        picker_row.addWidget(add_tag_btn)
        tags_layout.addLayout(picker_row)

        form.addRow("Title:",       self._title_edit)
        form.addRow("Authors:",     self._authors_edit)
        form.addRow("Dates:",       self._dates_edit)
        form.addRow("Tags:",        tags_widget)
        form.addRow("Label:",       self._label_edit)
        form.addRow("URL:",         self._url_edit)
        layout.addLayout(form)

        layout.addWidget(QLabel("Preview:"))
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMaximumHeight(90)
        layout.addWidget(self._preview)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._prefill(title, authors)

    @property
    def title(self) -> str:
        return self._title_edit.text().strip()

    @property
    def authors(self) -> str:
        return self._authors_edit.text().strip()

    @property
    def dates(self) -> str:
        return self._dates_edit.text().strip()

    @property
    def tags(self) -> list[str]:
        raw = self._tags_edit.text().strip()
        return [t.strip() for t in raw.split(",") if t.strip()]

    @property
    def label(self) -> str:
        return self._label_edit.text().strip()

    @property
    def url(self) -> str:
        return self._url_edit.text().strip()

    def _prefill(self, hint_title: str, hint_authors: str) -> None:
        try:
            from evid.core.pdf_metadata import extract_pdf_metadata  # noqa: PLC0415
            auto_title, auto_authors, auto_date = extract_pdf_metadata(
                self._pdf_path, self._pdf_path.name
            )
        except Exception:
            auto_title, auto_authors, auto_date = "", "", ""

        title   = hint_title   or auto_title   or self._pdf_path.stem
        authors = hint_authors or auto_authors
        self._title_edit.setText(title)
        self._authors_edit.setText(authors)
        self._dates_edit.setText(auto_date)
        self._label_edit.setText(title)
        self._update_preview()

    def _on_add_tag(self) -> None:
        tag = self._tag_picker.currentText().strip()
        if not tag:
            return
        current = self._tags_edit.text().strip()
        existing = [t.strip() for t in current.split(",") if t.strip()]
        if tag not in existing:
            existing.append(tag)
        self._tags_edit.setText(", ".join(existing))
        self._tag_picker.setCurrentText("")

    def _update_preview(self) -> None:
        lines = [
            f"title:   {self._title_edit.text()}",
            f"authors: {self._authors_edit.text()}",
            f"dates:   {self._dates_edit.text()}",
            f"tags:    {self._tags_edit.text()}",
            f"label:   {self._label_edit.text()}",
            f"url:     {self._url_edit.text()}",
        ]
        self._preview.setPlainText("\n".join(lines))

    def _view_file(self) -> None:
        try:
            subprocess.Popen(["xdg-open", str(self._pdf_path)])  # noqa: S603
        except Exception as exc:
            logger.warning("Could not open file: %s", exc)


# ── main tab ──────────────────────────────────────────────────────────────────


class DocsTab(QWidget):
    def __init__(
        self,
        ingester: "DocIngester",
        vec_service: "VecService",
        signals: "AppSignals",
        tag_service: "TagService",
    ) -> None:
        super().__init__()
        self._ingester = ingester
        self._vec_service = vec_service
        self._signals = signals
        self._tag_service = tag_service
        self._evidence_set: "EvidenceSet | None" = None
        self._docs: list["Document"] = []
        self._workers: list = []
        self._current_yaml_path: Path | None = None
        # Active progress dialogs (one per operation type; only one of each runs at a time)
        self._ingest_dlg: "QProgressDialog | None" = None
        self._index_dlg: "QProgressDialog | None" = None
        self._fetch_dlg: "QProgressDialog | None" = None
        self._fetch_worker: object = None  # UrlFetchWorker kept alive until _on_url_ready

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── anon mode header (shown only for ANON sets) ───────────────────
        self._anon_header = QFrame()
        self._anon_header.setFrameShape(QFrame.Shape.StyledPanel)
        self._anon_header.setStyleSheet(
            "QFrame { background:#fff3cd; border:2px solid #c97a00; border-radius:4px; padding:2px; }"
        )
        ah = QHBoxLayout(self._anon_header)
        ah.setContentsMargins(8, 4, 8, 4)
        lbl = QLabel("Anonymization mode:")
        lbl.setStyleSheet("font-weight:bold; color:#7a4800; border:none;")
        ah.addWidget(lbl)

        self._rb_real        = QRadioButton("Real")
        self._rb_placeholder = QRadioButton("Placeholder")
        self._rb_fake        = QRadioButton("Fake")
        self._rb_real.setChecked(True)
        for rb in (self._rb_real, self._rb_placeholder, self._rb_fake):
            rb.setStyleSheet("color:#7a4800; font-weight:bold; border:none;")
            ah.addWidget(rb)

        self._anon_btn_group = QButtonGroup(self)
        self._anon_btn_group.addButton(self._rb_real, 0)
        self._anon_btn_group.addButton(self._rb_placeholder, 1)
        self._anon_btn_group.addButton(self._rb_fake, 2)
        self._anon_btn_group.idClicked.connect(self._on_anon_mode_radio)
        ah.addStretch()
        self._anon_header.hide()
        outer.addWidget(self._anon_header)

        # ── horizontal splitter: doc list | right tabs ────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── left: doc list ────────────────────────────────────────────────
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        self._ingest_btn = QPushButton("Ingest PDF")
        self._ingest_btn.clicked.connect(self._on_ingest)
        self._url_btn = QPushButton("Add from URL")
        self._url_btn.clicked.connect(self._on_add_from_url)
        self._index_btn = QPushButton("Index docs")
        self._index_btn.setToolTip("Index all unindexed documents into the vector store")
        self._index_btn.clicked.connect(self._on_index_docs)
        self._open_editor_btn = QPushButton("Open .typ")
        self._open_editor_btn.clicked.connect(self._on_open_editor)
        self._open_dir_btn = QPushButton("Open dir")
        self._open_dir_btn.setToolTip("Open document directory in editor")
        self._open_dir_btn.clicked.connect(self._on_open_dir)
        for btn in [
            self._ingest_btn, self._url_btn, self._index_btn,
            self._open_editor_btn, self._open_dir_btn,
        ]:
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
        self._table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        lv.addWidget(self._table)

        splitter.addWidget(left)

        # ── right: tab widget ─────────────────────────────────────────────
        from PySide6.QtWidgets import QTabWidget  # noqa: PLC0415
        self._right_tabs = QTabWidget()

        # Tab 0: Detail
        detail_widget = QWidget()
        dv = QVBoxLayout(detail_widget)
        dv.setContentsMargins(4, 4, 4, 4)

        self._detail_uuid    = QLabel("—")
        self._detail_title   = QLineEdit()
        self._detail_authors = QLineEdit()
        self._detail_dates   = QLineEdit()
        self._detail_tags    = QLineEdit()
        self._detail_label   = QLineEdit()
        self._detail_url     = QLineEdit()
        self._detail_notes   = QTextEdit()
        self._detail_notes.setPlaceholderText("Notes…")
        self._detail_notes.setMaximumHeight(80)
        self._save_btn = QPushButton("Save changes")
        self._save_btn.clicked.connect(self._on_save_detail)

        form = QFormLayout()
        form.addRow("UUID:",    self._detail_uuid)
        form.addRow("Title:",   self._detail_title)
        form.addRow("Authors:", self._detail_authors)
        form.addRow("Dates:",   self._detail_dates)
        form.addRow("Tags:",    self._detail_tags)
        form.addRow("Label:",   self._detail_label)
        form.addRow("URL:",     self._detail_url)
        form.addRow("Notes:",   self._detail_notes)
        dv.addLayout(form)
        dv.addWidget(self._save_btn)
        dv.addStretch()
        self._right_tabs.addTab(detail_widget, "Detail")

        # Tab 1: Anonymize (hidden for NORMAL sets)
        self._anon_tab_widget = self._build_anon_tab()
        self._right_tabs.addTab(self._anon_tab_widget, "Anonymize")
        self._right_tabs.tabBar().setTabVisible(1, False)

        splitter.addWidget(self._right_tabs)
        splitter.setSizes([700, 400])

        outer.addWidget(splitter)

        signals.set_selected.connect(self._on_set_selected)
        signals.anon_mode_changed.connect(self._on_anon_mode_signal)

    # ── anon tab builder ──────────────────────────────────────────────────

    def _build_anon_tab(self) -> QWidget:
        widget = QWidget()
        v = QVBoxLayout(widget)
        v.setContentsMargins(0, 0, 0, 0)

        anon_splitter = QSplitter(Qt.Orientation.Horizontal)

        # left: YAML history
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("Entity YAML history:"))
        self._history_list = QListWidget()
        self._history_list.itemClicked.connect(self._on_yaml_selected)
        lv.addWidget(self._history_list)

        hist_btns = QHBoxLayout()
        self._set_current_btn = QPushButton("★ Set current")
        self._set_current_btn.clicked.connect(self._on_set_current_yaml)
        self._gen_yaml_btn = QPushButton("Generate YAML…")
        self._gen_yaml_btn.clicked.connect(self._on_generate_yaml)
        hist_btns.addWidget(self._set_current_btn)
        hist_btns.addWidget(self._gen_yaml_btn)
        lv.addLayout(hist_btns)
        anon_splitter.addWidget(left)

        # right: entity editor + anon preview
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 0, 0, 0)

        right_splitter = QSplitter(Qt.Orientation.Vertical)

        # entity editor
        entity_widget = QWidget()
        ev = QVBoxLayout(entity_widget)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.addWidget(QLabel("Entity editor:"))
        self._entity_table = QTableWidget(0, len(_ENTITY_COLS))
        self._entity_table.setHorizontalHeaderLabels(_ENTITY_COLS)
        self._entity_table.horizontalHeader().setStretchLastSection(True)
        ev.addWidget(self._entity_table)

        entity_btns = QHBoxLayout()
        self._save_entities_btn = QPushButton("Save entities")
        self._save_entities_btn.clicked.connect(self._on_save_entities)
        self._gen_fakes_btn = QPushButton("Generate fakes")
        self._gen_fakes_btn.clicked.connect(self._on_generate_fakes)
        entity_btns.addWidget(self._save_entities_btn)
        entity_btns.addWidget(self._gen_fakes_btn)
        ev.addLayout(entity_btns)
        right_splitter.addWidget(entity_widget)

        # anon preview
        preview_widget = QWidget()
        pv = QVBoxLayout(preview_widget)
        pv.setContentsMargins(0, 4, 0, 0)
        pv.addWidget(QLabel("Doc anon preview:"))
        self._anon_preview_text = QPlainTextEdit()
        self._anon_preview_text.setReadOnly(True)
        self._anon_preview_text.setPlaceholderText("Select a document to preview anonymised text…")
        pv.addWidget(self._anon_preview_text)
        right_splitter.addWidget(preview_widget)
        right_splitter.setSizes([300, 200])

        rv.addWidget(right_splitter)
        anon_splitter.addWidget(right)
        anon_splitter.setSizes([260, 540])

        v.addWidget(anon_splitter)
        return widget

    # ── public ───────────────────────────────────────────────────────────

    def reload(self, evidence_set: "EvidenceSet") -> None:
        from evidmgr.models import AnonMode, SetType  # noqa: PLC0415

        self._evidence_set = evidence_set
        self._docs = self._load_documents()
        self._refresh_table(self._docs)

        is_anon = evidence_set.set_type == SetType.ANON
        self._anon_header.setVisible(is_anon)
        self._right_tabs.tabBar().setTabVisible(1, is_anon)

        if is_anon:
            mode_idx = [AnonMode.REAL, AnonMode.PLACEHOLDER, AnonMode.FAKE].index(
                evidence_set.anon_mode
            )
            self._anon_btn_group.button(mode_idx).setChecked(True)
            self._refresh_yaml_history()

        self._anon_preview_text.setPlainText("")

    # ── private ───────────────────────────────────────────────────────────

    def _on_set_selected(self, slug: str) -> None:
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
        from evidmgr.models import Document  # noqa: PLC0415
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
            self._table.setItem(row, 3, QTableWidgetItem(doc.added.strftime("%Y-%m-%d")))
            self._table.setItem(row, 4, QTableWidgetItem(doc.uuid))
            for col in range(len(_COLS)):
                item = self._table.item(row, col)
                if item:
                    item.setData(Qt.ItemDataRole.UserRole, doc.uuid)

    def _reload_preserving_selection(self) -> None:
        """Reload docs + table while keeping the current selection intact."""
        selected_uuids = {d.uuid for d in self._selected_docs()}
        self._docs = self._load_documents()
        self._refresh_table(self._docs)
        if selected_uuids:
            for row in range(self._table.rowCount()):
                item = self._table.item(row, 4)
                if item and item.text() in selected_uuids:
                    self._table.selectRow(row)
                    break  # single-doc detail pane; first match is enough
        self._on_selection_changed()

    def _apply_filter(self, text: str) -> None:
        text = text.lower()
        filtered = [d for d in self._docs if not text or text in d.label.lower()]
        self._refresh_table(filtered)

    def _selected_doc(self) -> "Document | None":
        """Return the current (last-clicked) document for detail pane display."""
        row = self._table.currentRow()
        if row < 0:
            return None
        uuid_item = self._table.item(row, 4)
        if not uuid_item:
            return None
        return next((d for d in self._docs if d.uuid == uuid_item.text()), None)

    def _selected_docs(self) -> "list[Document]":
        """Return all selected documents (multi-select aware)."""
        seen: set[str] = set()
        docs: list[Document] = []
        for idx in self._table.selectionModel().selectedRows():
            uuid_item = self._table.item(idx.row(), 4)
            if uuid_item and uuid_item.text() not in seen:
                seen.add(uuid_item.text())
                doc = next((d for d in self._docs if d.uuid == uuid_item.text()), None)
                if doc:
                    docs.append(doc)
        return docs

    def _on_context_menu(self, pos) -> None:
        docs = self._selected_docs()
        if not docs:
            return
        from PySide6.QtWidgets import QMenu  # noqa: PLC0415
        menu = QMenu(self)
        tag_action = menu.addAction(f"Tag {len(docs)} selected\u2026")
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
        items = [TagItem(set_slug=self._evidence_set.slug, doc_uuid=d.uuid) for d in docs]
        self._tag_service.add_items(tag_name, items)
        # Also persist tag into info.yml so the detail pane reflects it
        for doc in docs:
            info_path = doc.path / "info.yml"
            try:
                info: dict = {}
                if info_path.exists():
                    with info_path.open("r", encoding="utf-8") as f:
                        info = yaml.safe_load(f) or {}
                existing_tags = [t.strip() for t in info.get("tags", "").split(",") if t.strip()]
                if tag_name not in existing_tags:
                    existing_tags.append(tag_name)
                    info["tags"] = ", ".join(existing_tags)
                    with info_path.open("w", encoding="utf-8") as f:
                        yaml.safe_dump(info, f, allow_unicode=True)
            except Exception:
                logger.exception("Failed to update info.yml tags for %s", doc.uuid)
        self._reload_preserving_selection()
        self.window().statusBar().showMessage(f"{len(docs)} docs added to {tag_name}", 3000)

    def _ask_tag_name(self) -> str:
        """Show a dialog with an editable combo of existing tags; return chosen name or ''."""
        from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout  # noqa: PLC0415

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
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addRow(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return ""
        return combo.currentText().strip()

    def _on_selection_changed(self) -> None:
        doc = self._selected_doc()
        if not doc:
            return
        info: dict = {}
        meta: dict = {}
        info_path = doc.path / "info.yml"
        meta_path = doc.path / "evidmgr_meta.yml"
        if info_path.exists():
            with info_path.open("r", encoding="utf-8") as f:
                info = yaml.safe_load(f) or {}
        if meta_path.exists():
            with meta_path.open("r", encoding="utf-8") as f:
                meta = yaml.safe_load(f) or {}

        self._detail_uuid.setText(doc.uuid)
        self._detail_title.setText(info.get("title", ""))
        self._detail_authors.setText(info.get("authors", ""))
        self._detail_dates.setText(info.get("dates", ""))
        self._detail_tags.setText(info.get("tags", ""))
        self._detail_label.setText(info.get("label", ""))
        self._detail_url.setText(info.get("url", ""))
        self._detail_notes.setPlainText(meta.get("notes", ""))
        self._update_anon_preview()

    def _on_save_detail(self) -> None:
        doc = self._selected_doc()
        if not doc or not self._evidence_set:
            return
        from evid.core.models import InfoModel  # noqa: PLC0415

        info_path = doc.path / "info.yml"
        meta_path = doc.path / "evidmgr_meta.yml"

        info: dict = {}
        if info_path.exists():
            with info_path.open("r", encoding="utf-8") as f:
                info = yaml.safe_load(f) or {}

        info["title"]   = self._detail_title.text().strip()
        info["authors"] = self._detail_authors.text().strip()
        info["dates"]   = self._detail_dates.text().strip()
        info["tags"]    = self._detail_tags.text().strip()
        info["label"]   = self._detail_label.text().strip()
        info["url"]     = self._detail_url.text().strip()

        try:
            validated = InfoModel(**{k: (v or "") for k, v in info.items()})
            info = validated.model_dump()
        except Exception:
            logger.exception("InfoModel validation failed on save for %s", doc.uuid)

        with info_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(info, f, allow_unicode=True)

        meta: dict = {}
        if meta_path.exists():
            with meta_path.open("r", encoding="utf-8") as f:
                meta = yaml.safe_load(f) or {}
        meta["notes"] = self._detail_notes.toPlainText()
        with meta_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(meta, f, allow_unicode=True)

        self._docs = self._load_documents()
        self._refresh_table(self._docs)

    # ── anon mode ─────────────────────────────────────────────────────────

    def _on_anon_mode_radio(self, btn_id: int) -> None:
        from evidmgr.models import AnonMode  # noqa: PLC0415
        modes = [AnonMode.REAL, AnonMode.PLACEHOLDER, AnonMode.FAKE]
        mode = modes[btn_id]
        # Persist in set.yml
        if self._evidence_set:
            parent = self.window()
            if hasattr(parent, "_set_manager"):
                try:
                    parent._set_manager.update_set_meta(
                        self._evidence_set.slug, anon_mode=mode.value
                    )
                    self._evidence_set = parent._set_manager.load_set(self._evidence_set.slug)
                except Exception:
                    logger.exception("Failed to save anon mode for %s", self._evidence_set.slug)
        self._signals.anon_mode_changed.emit(mode.value)
        self._update_anon_header_style(mode.value)
        self._update_anon_preview()

    def _on_anon_mode_signal(self, mode_str: str) -> None:
        """React when sidebar (or another source) changes the mode."""
        idx = {"real": 0, "placeholder": 1, "fake": 2}.get(mode_str, 0)
        btn = self._anon_btn_group.button(idx)
        if btn and not btn.isChecked():
            btn.setChecked(True)
        self._update_anon_header_style(mode_str)
        self._update_anon_preview()

    def _update_anon_header_style(self, mode_str: str) -> None:
        if mode_str == "real":
            bg, border, color = "#fff3cd", "#c97a00", "#7a4800"
        elif mode_str == "placeholder":
            bg, border, color = "#ffe0a0", "#b86800", "#6b3c00"
        else:  # fake
            bg, border, color = "#ffd0d0", "#c00000", "#7a0000"
        self._anon_header.setStyleSheet(
            f"QFrame {{ background:{bg}; border:2px solid {border}; border-radius:4px; padding:2px; }}"
        )
        label_style = f"font-weight:bold; color:{color}; border:none;"
        rb_style    = f"color:{color}; font-weight:bold; border:none;"
        for child in self._anon_header.findChildren(QLabel):
            child.setStyleSheet(label_style)
        for rb in (self._rb_real, self._rb_placeholder, self._rb_fake):
            rb.setStyleSheet(rb_style)

    # ── anon tab helpers ──────────────────────────────────────────────────

    def _refresh_yaml_history(self) -> None:
        self._history_list.clear()
        if not self._evidence_set:
            return
        parent = self.window()
        if not hasattr(parent, "_anon_service"):
            return
        yamls = parent._anon_service.list_yamls(self._evidence_set)
        for y in yamls:
            label = y.path.name
            if y.is_current:
                label = f"★ {label}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, str(y.path))
            self._history_list.addItem(item)

    def _on_yaml_selected(self, item: QListWidgetItem) -> None:
        self._current_yaml_path = Path(item.data(Qt.ItemDataRole.UserRole))
        self._load_entities_to_table(self._current_yaml_path)

    def _load_entities_to_table(self, yaml_path: Path) -> None:
        with yaml_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        entities = data.get("entities", [])
        self._entity_table.setRowCount(0)
        for entity in entities:
            row = self._entity_table.rowCount()
            self._entity_table.insertRow(row)
            self._entity_table.setItem(row, 0, QTableWidgetItem(entity.get("entity_type", "")))
            self._entity_table.setItem(row, 1, QTableWidgetItem(entity.get("original", "")))
            self._entity_table.setItem(row, 2, QTableWidgetItem(entity.get("placeholder", "")))
            self._entity_table.setItem(row, 3, QTableWidgetItem(entity.get("fake", "")))
            self._entity_table.setItem(row, 4, QTableWidgetItem(", ".join(entity.get("variants", []))))

    def _on_set_current_yaml(self) -> None:
        if not self._current_yaml_path or not self._evidence_set:
            return
        parent = self.window()
        if hasattr(parent, "_anon_service"):
            parent._anon_service.set_current(self._evidence_set, self._current_yaml_path)
        self._refresh_yaml_history()

    def _on_save_entities(self) -> None:
        if not self._current_yaml_path:
            return
        entities = []
        for row in range(self._entity_table.rowCount()):
            def cell(c, r=row):
                item = self._entity_table.item(r, c)
                return item.text() if item else ""
            variants = [v.strip() for v in cell(4).split(",") if v.strip()]
            entities.append({
                "entity_type": cell(0),
                "original":    cell(1),
                "placeholder": cell(2),
                "fake":        cell(3),
                "variants":    variants,
            })
        parent = self.window()
        if hasattr(parent, "_anon_service"):
            parent._anon_service.save_entity_yaml(
                self._evidence_set, self._current_yaml_path, entities
            )
        logger.info("Saved entity YAML: %s", self._current_yaml_path.name)

    def _on_generate_fakes(self) -> None:
        if not self._current_yaml_path or not self._evidence_set:
            return
        parent = self.window()
        if hasattr(parent, "_anon_service"):
            parent._anon_service.generate_fakes(
                self._current_yaml_path, self._evidence_set.anon_language
            )
            self._load_entities_to_table(self._current_yaml_path)

    def _on_generate_yaml(self) -> None:
        if not self._evidence_set:
            QMessageBox.warning(self, "No set", "Select an evidence set first.")
            return
        from evidmgr.gui.workers import AnonExtractWorker  # noqa: PLC0415

        dlg = QDialog(self)
        dlg.setWindowTitle("Select documents for entity extraction")
        dlg.resize(420, 320)
        lv = QVBoxLayout(dlg)
        lv.addWidget(QLabel("Select documents to extract entities from:"))
        doc_list = QListWidget()
        doc_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        docs_dir = self._evidence_set.path / "docs"
        if docs_dir.exists():
            for d in docs_dir.iterdir():
                if d.is_dir():
                    info_p = d / "info.yml"
                    label = d.name
                    if info_p.exists():
                        try:
                            with info_p.open("r", encoding="utf-8") as f:
                                info = yaml.safe_load(f) or {}
                            label = info.get("label", d.name)
                        except Exception:
                            pass
                    item = QListWidgetItem(label)
                    item.setData(Qt.ItemDataRole.UserRole, d.name)
                    doc_list.addItem(item)
        lv.addWidget(doc_list)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lv.addWidget(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        selected = [item.data(Qt.ItemDataRole.UserRole) for item in doc_list.selectedItems()]
        if not selected:
            return

        parent = self.window()
        if not hasattr(parent, "_anon_service"):
            return
        worker = AnonExtractWorker(parent._anon_service, self._evidence_set, selected)
        worker.finished.connect(self._on_anon_extract_done)   # AutoConnection → main thread
        worker.error.connect(self._on_anon_extract_error)
        self._workers.append(worker)
        worker.start()

    def _on_anon_extract_done(self, yaml_path: str) -> None:
        try:
            self._refresh_yaml_history()
            if self._evidence_set:
                self._signals.anon_yaml_created.emit(self._evidence_set.slug)
        except Exception:
            logger.exception("Error after anon extraction completed")

    def _on_anon_extract_error(self, msg: str) -> None:
        try:
            QMessageBox.critical(self, "Extraction failed", msg)
        except Exception:
            logger.exception("Error handling anon extraction failure: %s", msg)

    def _update_anon_preview(self) -> None:
        from evidmgr.models import AnonMode, SetType  # noqa: PLC0415

        if not self._evidence_set or self._evidence_set.set_type != SetType.ANON:
            return
        doc = self._selected_doc()
        if not doc:
            self._anon_preview_text.setPlainText("")
            return

        typ_path = doc.path / "label.typ"
        if not typ_path.exists():
            candidates = list(doc.path.glob("*.typ"))
            typ_path = candidates[0] if candidates else None
        if not typ_path:
            self._anon_preview_text.setPlainText("(no .typ file)")
            return

        try:
            text = typ_path.read_text(encoding="utf-8")
        except Exception:
            self._anon_preview_text.setPlainText("(could not read .typ file)")
            return

        idx = self._anon_btn_group.checkedId()
        mode = [AnonMode.REAL, AnonMode.PLACEHOLDER, AnonMode.FAKE][max(0, idx)]
        parent = self.window()
        if hasattr(parent, "_anon_service"):
            try:
                result = parent._anon_service.pseudonymize(text[:4000], self._evidence_set, mode)
                self._anon_preview_text.setPlainText(result)
            except Exception as exc:
                self._anon_preview_text.setPlainText(f"(preview error: {exc})")
        else:
            self._anon_preview_text.setPlainText(text[:4000])

    # ── ingest ────────────────────────────────────────────────────────────

    def _on_ingest(self) -> None:
        if not self._evidence_set:
            QMessageBox.warning(self, "No set", "Select an evidence set first.")
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select PDFs", "", "PDF files (*.pdf)"
        )
        for path_str in paths:
            pdf_path = Path(path_str)
            dlg = AddDocDialog(pdf_path, self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self._start_ingest(pdf_path, dlg)

    def _on_add_from_url(self) -> None:
        if not self._evidence_set:
            QMessageBox.warning(self, "No set", "Select an evidence set first.")
            return
        url, ok = QInputDialog.getText(self, "Add from URL", "URL:")
        if not ok or not url.strip():
            return

        from evidmgr.gui.workers import UrlFetchWorker  # noqa: PLC0415

        fetch_dlg = QProgressDialog("Fetching URL…", "Cancel", 0, 0, self)
        fetch_dlg.setWindowTitle("Downloading")
        fetch_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        fetch_dlg.show()

        self._fetch_dlg = fetch_dlg
        self._fetch_worker = None  # will be set right after so GC doesn't drop it
        worker = UrlFetchWorker(url.strip())
        self._fetch_worker = worker
        worker.ready.connect(self._on_url_ready)   # AutoConnection → main thread
        worker.error.connect(self._on_url_error)
        self._workers.append(worker)
        worker.start()

    def _on_url_ready(self, pdf_path_str: str, page_title: str, authors: str, url: str) -> None:
        try:
            fetch_dlg = self._fetch_dlg
            worker = self._fetch_worker
            self._fetch_dlg = None
            self._fetch_worker = None
            if fetch_dlg:
                fetch_dlg.close()
            if not self._evidence_set:
                QMessageBox.warning(self, "No set", "Select an evidence set before adding a document.")
                return
            pdf_path = Path(pdf_path_str)
            dlg = AddDocDialog(pdf_path, self, url=url, title=page_title, authors=authors)
            if worker is not None:
                dlg._temp_dir = worker.temp_dir
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self._start_ingest(pdf_path, dlg)
        except Exception:
            logger.exception("Error handling URL fetch result")

    def _on_url_error(self, msg: str) -> None:
        try:
            fetch_dlg = self._fetch_dlg
            self._fetch_dlg = None
            self._fetch_worker = None
            if fetch_dlg:
                fetch_dlg.close()
            QMessageBox.critical(self, "URL fetch failed", msg)
        except Exception:
            logger.exception("Error handling URL fetch error")

    def _start_ingest(self, pdf_path: Path, dlg: "AddDocDialog") -> None:
        if not self._evidence_set:
            QMessageBox.warning(self, "No set", "Select an evidence set first.")
            return
        # Detect duplicate before spawning a worker to avoid a cross-thread race
        # on the fast "already ingested → return early" code path.
        try:
            import hashlib, uuid as _uuid  # noqa: PLC0415, E401
            with pdf_path.open("rb") as fh:
                digest = hashlib.sha256(fh.read()).digest()[:16]
            doc_uuid = _uuid.UUID(bytes=digest).hex
            doc_dir = self._evidence_set.path / "docs" / doc_uuid
            if doc_dir.exists():
                QMessageBox.information(
                    self, "Already exists",
                    f"This document was already added to '{self._evidence_set.name}'.",
                )
                return
        except Exception:
            logger.exception("Duplicate check failed; proceeding with ingest")
        from evidmgr.gui.workers import IngestWorker  # noqa: PLC0415
        from evidmgr.services.doc_ingester import DocIngester  # noqa: PLC0415
        from evidmgr.services.vec_service import VecService  # noqa: PLC0415

        progress_dlg = QProgressDialog(
            f"Ingesting {pdf_path.name}…", None, 0, 7, self
        )
        progress_dlg.setWindowTitle("Ingesting")
        progress_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dlg.show()

        if self._evidence_set:
            self._vec_service.close(self._evidence_set.slug)
        worker_vec = VecService()
        worker_ingester = DocIngester(vec_service=worker_vec)

        worker = IngestWorker(
            worker_ingester, pdf_path, self._evidence_set,
            label=dlg.label,
            title=dlg.title,
            authors=dlg.authors,
            dates=dlg.dates,
            tags=dlg.tags,
            source_url=dlg.url,
            temp_dir=getattr(dlg, "_temp_dir", None),
        )
        self._ingest_dlg = progress_dlg
        worker.progress.connect(self._on_ingest_progress)  # AutoConnection → main thread
        worker.finished.connect(self._on_ingest_done)
        worker.error.connect(self._on_ingest_error)
        self._workers.append(worker)
        worker.start()

    def _on_ingest_progress(self, step: int, total: int, msg: str) -> None:
        try:
            if self._ingest_dlg:
                self._ingest_dlg.setValue(step)
                self._ingest_dlg.setLabelText(msg)
        except Exception:
            logger.exception("Error updating ingest progress")

    def _on_ingest_done(self, doc_uuid: str) -> None:
        try:
            if self._ingest_dlg:
                self._ingest_dlg.close()
                self._ingest_dlg = None
            if self._evidence_set:
                self._signals.doc_ingested.emit(self._evidence_set.slug, doc_uuid)
            self._docs = self._load_documents()
            self._refresh_table(self._docs)
        except Exception:
            logger.exception("Error completing ingest for %s", doc_uuid)

    def _on_ingest_error(self, msg: str) -> None:
        try:
            if self._ingest_dlg:
                self._ingest_dlg.close()
                self._ingest_dlg = None
            QMessageBox.critical(self, "Ingest failed", msg)
            self._signals.ingestion_error.emit(msg)
        except Exception:
            logger.exception("Error handling ingest failure: %s", msg)

    # ── indexing ──────────────────────────────────────────────────────────

    def _on_index_docs(self) -> None:
        if not self._evidence_set:
            QMessageBox.warning(self, "No set", "Select an evidence set first.")
            return
        unindexed = [d for d in self._docs if not d.indexed]
        if not unindexed:
            QMessageBox.information(self, "All indexed", "All documents are already indexed.")
            return

        progress_dlg = QProgressDialog(
            f"Indexing {len(unindexed)} document(s)…", None, 0, len(unindexed), self
        )
        progress_dlg.setWindowTitle("Indexing")
        progress_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dlg.show()

        from evidmgr.gui.workers import IndexWorker  # noqa: PLC0415
        from evidmgr.services.doc_ingester import DocIngester  # noqa: PLC0415
        from evidmgr.services.vec_service import VecService  # noqa: PLC0415

        self._vec_service.close(self._evidence_set.slug)
        worker_vec = VecService()
        worker_ingester = DocIngester(vec_service=worker_vec)

        self._index_dlg = progress_dlg
        worker = IndexWorker(worker_ingester, unindexed, self._evidence_set)
        worker.progress.connect(self._on_index_progress)   # AutoConnection → main thread
        worker.finished.connect(self._on_index_done)
        worker.error.connect(self._on_index_error)
        self._workers.append(worker)
        worker.start()

    def _on_index_progress(self, done: int, total: int, msg: str) -> None:
        try:
            if self._index_dlg:
                self._index_dlg.setValue(done)
                self._index_dlg.setLabelText(msg)
        except Exception:
            logger.exception("Error updating index progress")

    def _on_index_done(self) -> None:
        try:
            if self._index_dlg:
                self._index_dlg.close()
                self._index_dlg = None
            self._docs = self._load_documents()
            self._refresh_table(self._docs)
            if self._evidence_set:
                self._signals.doc_indexed.emit(self._evidence_set.slug, "")
        except Exception:
            logger.exception("Error completing index operation")

    def _on_index_error(self, msg: str) -> None:
        try:
            if self._index_dlg:
                self._index_dlg.close()
                self._index_dlg = None
            QMessageBox.critical(self, "Indexing failed", msg)
            self._signals.ingestion_error.emit(msg)
        except Exception:
            logger.exception("Error handling index failure: %s", msg)

    # ── editor / dir ──────────────────────────────────────────────────────

    def _editor(self) -> str:
        parent = self.window()
        if hasattr(parent, "_config"):
            return parent._config.editor
        return "code"

    def _open_with_editor(self, path: str) -> None:
        editor = self._editor()
        if shutil.which(editor):
            subprocess.Popen([editor, path])  # noqa: S603
        else:
            from PySide6.QtCore import QUrl  # noqa: PLC0415
            from PySide6.QtGui import QDesktopServices  # noqa: PLC0415
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _on_open_dir(self) -> None:
        doc = self._selected_doc()
        if doc:
            self._open_with_editor(str(doc.path))

    def _on_open_editor(self) -> None:
        doc = self._selected_doc()
        if not doc:
            return
        typ_files = list(doc.path.glob("*.typ"))
        if not typ_files:
            QMessageBox.information(self, "No .typ file", "No Typst file found for this document.")
            return
        self._open_with_editor(str(typ_files[0]))

