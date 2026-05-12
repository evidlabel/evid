"""Docs tab — document list, metadata detail, and (for ANON sets) anonymisation controls."""

from __future__ import annotations

import contextlib
import json
import logging
import shutil
import subprocess
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from PySide6.QtCore import (
    QEvent,
    QMimeData,
    QPoint,
    QRect,
    QSize,
    Qt,
)
from PySide6.QtGui import QDrag, QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from evid.gui.signals import AppSignals
    from evid.models import Document, EvidenceSet
    from evid.services.doc_ingester import DocIngester
    from evid.services.tag_service import TagService
    from evid.services.vec_service import VecService

logger = logging.getLogger(__name__)

_COLS = ["F", "J", "Label", "Added", "UUID"]
_DOC_MIME_TYPE = "application/x-evidmgr-doc"
_ENTITY_COLS = ["Type", "Original", "Placeholder", "Fake", "Variants"]


# ── pre-ingest metadata dialog ────────────────────────────────────────────────


class AddDocDialog(QDialog):
    """Metadata dialog shown before a document is ingested."""

    def __init__(
        self,
        pdf_path: Path,
        parent=None,
        *,
        url: str = "",
        title: str = "",
        authors: str = "",
    ) -> None:
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
        self._title_edit = QLineEdit()
        self._authors_edit = QLineEdit()
        self._dates_edit = QLineEdit()
        self._tags_edit = QLineEdit()
        self._tags_edit.setPlaceholderText("comma-separated")
        self._label_edit = QLineEdit()
        self._url_edit = QLineEdit(url)
        for w in (
            self._title_edit,
            self._authors_edit,
            self._dates_edit,
            self._tags_edit,
            self._label_edit,
            self._url_edit,
        ):
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

        form.addRow("Title:", self._title_edit)
        form.addRow("Authors:", self._authors_edit)
        form.addRow("Dates:", self._dates_edit)
        form.addRow("Tags:", tags_widget)
        form.addRow("Label:", self._label_edit)
        form.addRow("URL:", self._url_edit)
        layout.addLayout(form)

        layout.addWidget(QLabel("Preview:"))
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMaximumHeight(90)
        layout.addWidget(self._preview)

        self._open_in_labeller_cb = QCheckBox("Open in labeller after adding")
        self._open_in_labeller_cb.setChecked(True)
        layout.addWidget(self._open_in_labeller_cb)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
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

    @property
    def open_in_labeller(self) -> bool:
        return self._open_in_labeller_cb.isChecked()

    def _prefill(self, hint_title: str, hint_authors: str) -> None:
        try:
            from evid.core.pdf_metadata import extract_pdf_metadata

            auto_title, auto_authors, auto_date = extract_pdf_metadata(
                self._pdf_path, self._pdf_path.name
            )
        except Exception:
            auto_title, auto_authors, auto_date = "", "", ""

        title = hint_title or auto_title or self._pdf_path.stem
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
            subprocess.Popen(["xdg-open", str(self._pdf_path)])
        except Exception as exc:
            logger.warning("Could not open file: %s", exc)


# ── flow layout ───────────────────────────────────────────────────────────────


class FlowLayout(QLayout):
    """Wrapping flow layout — pills wrap to the next row when the row is full."""

    def __init__(self, parent=None, *, h_spacing: int = 6, v_spacing: int = 4) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations(Qt.Orientation.Horizontal)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(
            margins.left() + margins.right(), margins.top() + margins.bottom()
        )
        return size

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        left = rect.x() + margins.left()
        top = rect.y() + margins.top()
        right = rect.right() - margins.right()
        x, y, line_height = left, top, 0
        for item in self._items:
            size = item.sizeHint()
            if x + size.width() > right and x > left:
                x = left
                y += line_height + self._v_spacing
                line_height = 0
            if not test_only:
                from PySide6.QtCore import QPoint

                item.setGeometry(QRect(QPoint(x, y), size))
            x += size.width() + self._h_spacing
            line_height = max(line_height, size.height())
        return y + line_height - rect.y() + margins.bottom()


# ── tag pill ───────────────────────────────────────────────────────────────────


class TagPill(QPushButton):
    """A single rounded pill button representing one tag."""

    MIME_TYPE = "application/x-tag-name"
    _STATE_DEFAULT = "default"
    _STATE_ACTIVE = "active"
    _STATE_CARRIED = "carried"

    _STYLES = {
        _STATE_DEFAULT: (
            "QPushButton{border-radius:10px;padding:2px 8px;"
            "border:1px solid #999;background:#e8e8e8;color:#222;font-size:11px;}"
            "QPushButton:hover{background:#d0d0d0;}"
        ),
        _STATE_ACTIVE: (
            "QPushButton{border-radius:10px;padding:2px 8px;"
            "border:1px solid #005a9e;background:#0078d4;color:#fff;font-size:11px;}"
            "QPushButton:hover{background:#006cbe;}"
        ),
        _STATE_CARRIED: (
            "QPushButton{border-radius:10px;padding:2px 8px;"
            "border:1px solid #2e7d32;background:#c8e6c9;color:#1b5e20;font-size:11px;}"
            "QPushButton:hover{background:#b5ddb7;}"
        ),
    }

    def __init__(self, tag_name: str, count: int, parent=None) -> None:
        super().__init__(parent)
        self._tag_name = tag_name
        self._count = count
        self._state = self._STATE_DEFAULT
        self._drag_start: QPoint | None = None
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._refresh_text()
        self._refresh_style()

    @property
    def tag_name(self) -> str:
        return self._tag_name

    def update_count(self, count: int) -> None:
        self._count = count
        self._refresh_text()

    def set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self._refresh_style()

    def _refresh_text(self) -> None:
        self.setText(f"  {self._tag_name}  ×  {self._count}  ")

    def _refresh_style(self) -> None:
        self.setStyleSheet(
            self._STYLES.get(self._state, self._STYLES[self._STATE_DEFAULT])
        )

    # ── drag ──────────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            self._drag_start is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and (event.pos() - self._drag_start).manhattanLength() > 8
        ):
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(self.MIME_TYPE, self._tag_name.encode("utf-8"))
            drag.setMimeData(mime)
            self._drag_start = None
            drag.exec(Qt.DropAction.CopyAction)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton or (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() & Qt.KeyboardModifier.AltModifier
        ):
            self.customContextMenuRequested.emit(event.pos())
            return
        self._drag_start = None
        super().mouseReleaseEvent(event)


# ── tags completer ─────────────────────────────────────────────────────────────


class TagsCompleter(QCompleter):
    """QCompleter that completes the last comma-separated token in a QLineEdit."""

    def __init__(self, tags: list[str], parent=None) -> None:
        super().__init__(tags, parent)
        self.setFilterMode(Qt.MatchFlag.MatchContains)
        self.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)

    def splitPath(self, path: str) -> list[str]:
        return [path.rsplit(",", maxsplit=1)[-1].strip()]

    def pathFromIndex(self, index) -> str:
        completion = super().pathFromIndex(index)
        widget = self.widget()
        if widget is None:
            return completion
        text = widget.text()
        parts = text.split(",")
        parts[-1] = " " + completion
        return ",".join(parts)


# ── tag pill pool ──────────────────────────────────────────────────────────────


class TagPillPool(QWidget):
    """Scrollable flow area showing one pill per unique tag in the loaded corpus."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._active_tags: set[str] = set()
        self._carried_tags: set[str] = set()
        self._pills: dict[str, TagPill] = {}
        self._on_pill_click = None
        self._on_pill_menu = None

        # Content widget inside the scroll area
        self._content = QWidget()
        self._flow = FlowLayout(self._content, h_spacing=6, v_spacing=4)
        self._content.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(self._content)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # "+ new tag" button — always last
        self._new_pill = QPushButton("+ new tag")
        self._new_pill.setStyleSheet(
            "QPushButton{border-radius:10px;padding:2px 8px;"
            "border:1px dashed #999;background:transparent;color:#666;font-size:11px;}"
            "QPushButton:hover{color:#333;border-color:#555;}"
        )
        self._new_pill.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._new_pill.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_callbacks(
        self,
        on_pill_click,
        on_pill_menu,
        on_new_tag,
    ) -> None:
        self._on_pill_click = on_pill_click
        self._on_pill_menu = on_pill_menu
        self._new_pill.clicked.connect(on_new_tag)

    def rebuild(self, docs: list) -> None:
        """Rebuild pills from scratch based on doc.tags across all docs."""
        # Clear existing pills — skip _new_pill (it is persistent and re-added at the end)
        while self._flow.count():
            item = self._flow.takeAt(0)
            if not item:
                continue
            w = item.widget()
            if not w or w is self._new_pill:
                continue
            w.deleteLater()  # Qt cleans up signal connections on destruction
        self._pills.clear()

        # Count tags
        tag_counts: dict[str, int] = {}
        for doc in docs:
            for tag in doc.tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        # Create pills in alphabetical order
        for name in sorted(tag_counts):
            pill = TagPill(name, tag_counts[name])
            self._update_pill_state_for(name, pill)
            if self._on_pill_click:
                pill.clicked.connect(
                    lambda _checked=False, n=name: self._on_pill_click(n)
                )
            if self._on_pill_menu:
                pill.customContextMenuRequested.connect(
                    lambda pos, p=pill, n=name: self._on_pill_menu(
                        n, p.mapToGlobal(pos)
                    )
                )
            self._flow.addWidget(pill)
            self._pills[name] = pill

        self._flow.addWidget(self._new_pill)
        self._content.updateGeometry()

    def set_active_tags(self, tags: set[str]) -> None:
        self._active_tags = set(tags)
        for name, pill in self._pills.items():
            self._update_pill_state_for(name, pill)

    def set_carried_tags(self, tags: set[str]) -> None:
        self._carried_tags = set(tags)
        for name, pill in self._pills.items():
            self._update_pill_state_for(name, pill)

    def _update_pill_state_for(self, name: str, pill: TagPill) -> None:
        if name in self._active_tags:
            pill.set_state(TagPill._STATE_ACTIVE)
        elif name in self._carried_tags:
            pill.set_state(TagPill._STATE_CARRIED)
        else:
            pill.set_state(TagPill._STATE_DEFAULT)


# ── main tab ──────────────────────────────────────────────────────────────────


class DocsTab(QWidget):
    def __init__(
        self,
        ingester: DocIngester,
        vec_service: VecService,
        signals: AppSignals,
        tag_service: TagService,
    ) -> None:
        super().__init__()
        self._ingester = ingester
        self._vec_service = vec_service
        self._signals = signals
        self._tag_service = tag_service
        self._evidence_set: EvidenceSet | None = None
        self._docs: list[Document] = []
        self._workers: list = []
        self._current_yaml_path: Path | None = None
        # Active progress dialogs (one per operation type; only one of each runs at a time)
        self._ingest_dlg: QProgressDialog | None = None
        self._index_dlg: QProgressDialog | None = None
        self._fetch_dlg: QProgressDialog | None = None
        from evid.gui.label_controller import LabelController

        self._labeler = LabelController(self._editor, parent=self)
        self._labeler.label_updated.connect(self._on_label_done)
        self._labeler.label_error.connect(self._on_label_error)
        self._open_in_labeller_after_ingest: bool = False
        self._doc_drag_start: object = None  # QPoint | None
        self._fetch_worker: object = (
            None  # UrlFetchWorker kept alive until _on_url_ready
        )
        self._active_tag_filter: set[str] = set()

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

        self._rb_real = QRadioButton("Real")
        self._rb_placeholder = QRadioButton("Placeholder")
        self._rb_fake = QRadioButton("Fake")
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
        self._index_btn.setToolTip(
            "Index all unindexed documents into the vector store"
        )
        self._index_btn.clicked.connect(self._on_index_docs)
        self._open_editor_btn = QPushButton("Label")
        self._open_editor_btn.setToolTip(
            "Open label.typ in editor (generates it from PDF if missing)"
        )
        self._open_editor_btn.clicked.connect(self._on_label_doc)
        self._open_dir_btn = QPushButton("Open dir")
        self._open_dir_btn.setToolTip("Open document directory in editor")
        self._open_dir_btn.clicked.connect(self._on_open_dir)
        for btn in [
            self._ingest_btn,
            self._url_btn,
            self._index_btn,
            self._open_editor_btn,
            self._open_dir_btn,
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
        hh = self._table.horizontalHeader()
        from PySide6.QtWidgets import QHeaderView

        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)  # F
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)  # J
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Label
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)  # Added
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)  # UUID
        self._table.setColumnWidth(0, 28)
        self._table.setColumnWidth(1, 28)
        self._table.setColumnWidth(3, 88)
        self._table.setColumnWidth(4, 260)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)
        lv.addWidget(self._table)

        splitter.addWidget(left)

        # ── right: tab widget ─────────────────────────────────────────────
        from PySide6.QtWidgets import QTabWidget

        self._right_tabs = QTabWidget()

        # Tab 0: Detail — form (top) + tag pill pool (bottom) in a vertical splitter
        form_widget = QWidget()
        dv = QVBoxLayout(form_widget)
        dv.setContentsMargins(4, 4, 4, 4)

        # Compact UUID row: truncated monospace label + View + Copy buttons
        self._detail_uuid_full = ""
        self._detail_uuid = QLabel("—")
        self._detail_uuid.setFont(QFont("monospace"))
        uuid_row = QWidget()
        uuid_hl = QHBoxLayout(uuid_row)
        uuid_hl.setContentsMargins(0, 0, 0, 0)
        uuid_hl.setSpacing(4)
        uuid_hl.addWidget(self._detail_uuid, 1)
        self._uuid_view_btn = QPushButton("View")
        self._uuid_view_btn.setFixedWidth(44)
        self._uuid_view_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._uuid_view_btn.clicked.connect(self._on_uuid_view)
        self._uuid_copy_btn = QPushButton("Copy")
        self._uuid_copy_btn.setFixedWidth(44)
        self._uuid_copy_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._uuid_copy_btn.clicked.connect(self._on_uuid_copy)
        uuid_hl.addWidget(self._uuid_view_btn)
        uuid_hl.addWidget(self._uuid_copy_btn)

        self._detail_title = QLineEdit()
        self._detail_authors = QLineEdit()
        self._detail_dates = QLineEdit()
        self._detail_tags = QLineEdit()
        self._detail_label = QLineEdit()
        self._detail_url = QLineEdit()
        self._detail_notes = QTextEdit()
        self._detail_notes.setPlaceholderText("Notes…")
        self._detail_notes.setMaximumHeight(80)
        self._save_btn = QPushButton("Save changes")
        self._save_btn.clicked.connect(self._on_save_detail)

        form = QFormLayout()
        form.addRow("UUID:", uuid_row)
        form.addRow("Title:", self._detail_title)
        form.addRow("Authors:", self._detail_authors)
        form.addRow("Dates:", self._detail_dates)
        form.addRow("Tags:", self._detail_tags)
        form.addRow("Label:", self._detail_label)
        form.addRow("URL:", self._detail_url)
        form.addRow("Notes:", self._detail_notes)
        dv.addLayout(form, 0)
        dv.addWidget(self._save_btn, 0)

        # Label key list: shows keys from label.json; click → preview text below
        dv.addWidget(QLabel("Labels:"), 0)
        self._label_keys_list = QListWidget()
        self._label_keys_list.setAlternatingRowColors(True)
        self._label_keys_list.currentItemChanged.connect(self._on_label_key_selected)
        dv.addWidget(self._label_keys_list, 2)
        self._label_key_text = QPlainTextEdit()
        self._label_key_text.setReadOnly(True)
        self._label_key_text.setPlaceholderText("Select a label above to preview…")
        dv.addWidget(self._label_key_text, 1)

        # Bottom: column key strip + tag pill pool
        bottom_widget = QWidget()
        bv = QVBoxLayout(bottom_widget)
        bv.setContentsMargins(4, 2, 4, 2)
        bv.setSpacing(2)
        key_strip = QLabel("  ✓ F = Fetched    ✓ J = Indexed (JSON)")
        key_strip.setStyleSheet("color: #888; font-size: 10px;")
        bv.addWidget(key_strip)
        self._pill_pool = TagPillPool()
        self._pill_pool.setMinimumHeight(60)
        self._pill_pool.set_callbacks(
            on_pill_click=self._on_pill_clicked,
            on_pill_menu=self._on_pill_menu,
            on_new_tag=self._on_new_tag_pill,
        )
        bv.addWidget(self._pill_pool)

        detail_splitter = QSplitter(Qt.Orientation.Vertical)
        detail_splitter.addWidget(form_widget)
        detail_splitter.addWidget(bottom_widget)
        detail_splitter.setSizes([650, 350])

        self._right_tabs.addTab(detail_splitter, "Detail")

        # Tab 1: Anonymize (hidden for NORMAL sets)
        self._anon_tab_widget = self._build_anon_tab()
        self._right_tabs.addTab(self._anon_tab_widget, "Anonymize")
        self._right_tabs.tabBar().setTabVisible(1, False)

        splitter.addWidget(self._right_tabs)
        splitter.setSizes([700, 400])

        outer.addWidget(splitter)

        # Tags autocomplete for the detail pane
        self._tags_completer = TagsCompleter([], self)
        self._detail_tags.setCompleter(self._tags_completer)
        self._detail_tags.textEdited.connect(lambda _: self._tags_completer.complete())

        # Accept drops on the doc table (tag pills dragged onto rows)
        self._table.viewport().setAcceptDrops(True)
        self._table.viewport().installEventFilter(self)

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
        self._anon_preview_text.setPlaceholderText(
            "Select a document to preview anonymised text…"
        )
        pv.addWidget(self._anon_preview_text)
        right_splitter.addWidget(preview_widget)
        right_splitter.setSizes([300, 200])

        rv.addWidget(right_splitter)
        anon_splitter.addWidget(right)
        anon_splitter.setSizes([260, 540])

        v.addWidget(anon_splitter)
        return widget

    # ── public ───────────────────────────────────────────────────────────

    def reload(self, evidence_set: EvidenceSet) -> None:
        from evid.models import AnonMode, SetType

        self._evidence_set = evidence_set
        self._active_tag_filter = set()
        self._docs = self._load_documents()
        self._refresh_table(self._docs)
        self._pill_pool.rebuild(self._docs)
        self._pill_pool.set_active_tags(set())
        self._pill_pool.set_carried_tags(set())

        # Update tags completer model
        from PySide6.QtCore import QStringListModel

        all_tags = sorted({tag for doc in self._docs for tag in doc.tags})
        self._tags_completer.setModel(QStringListModel(all_tags))

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

    def _load_documents(self) -> list[Document]:
        if self._evidence_set is None:
            return []
        from datetime import date, datetime

        from evid.models import Document

        docs = []
        docs_dir = self._evidence_set.path / "docs"
        if not docs_dir.exists():
            return []
        for doc_dir in docs_dir.iterdir():
            if not doc_dir.is_dir():
                continue
            try:
                info_path = doc_dir / "info.yml"
                meta_path = doc_dir / "evidmgr_meta.yml"
                info = {}
                if info_path.exists():
                    try:
                        with info_path.open("r", encoding="utf-8") as f:
                            info = yaml.safe_load(f) or {}
                    except yaml.YAMLError as exc:
                        logger.warning(
                            "Skipping %s — bad info.yml: %s", doc_dir.name, exc
                        )
                        continue
                meta = {}
                if meta_path.exists():
                    with meta_path.open("r", encoding="utf-8") as f:
                        meta = yaml.safe_load(f) or {}
                tags_raw = info.get("tags", "")
                if isinstance(tags_raw, list):
                    tags = [str(t).strip() for t in tags_raw if str(t).strip()]
                elif tags_raw:
                    tags = [t.strip() for t in str(tags_raw).split(",") if t.strip()]
                else:
                    tags = []
                raw_added = info.get("time_added", "")
                try:
                    if isinstance(raw_added, date):
                        added = datetime(
                            raw_added.year, raw_added.month, raw_added.day, tzinfo=UTC
                        )
                    else:
                        added = datetime.strptime(str(raw_added), "%Y-%m-%d").replace(
                            tzinfo=UTC
                        )
                except (ValueError, TypeError):
                    added = datetime.fromtimestamp(doc_dir.stat().st_mtime, tz=UTC)
                docs.append(
                    Document(
                        uuid=doc_dir.name,
                        path=doc_dir,
                        label=info.get("label", doc_dir.name),
                        tags=tags,
                        added=added,
                        indexed=meta.get("indexed", False),
                        anon_pending=meta.get("anon_pending", False),
                        notes=meta.get("notes", ""),
                        source_url=info.get("url", ""),
                    )
                )
            except Exception:
                logger.exception("Failed to load doc at %s", doc_dir)
        docs.sort(key=lambda d: (d.added, d.path.stat().st_mtime), reverse=True)
        return docs

    def _refresh_table(self, docs: list[Document]) -> None:
        self._table.setRowCount(0)
        for doc in docs:
            row = self._table.rowCount()
            self._table.insertRow(row)
            has_file = (doc.path / "original.pdf").exists()
            has_json = (doc.path / "label.json").exists()
            self._table.setItem(row, 0, QTableWidgetItem("✓" if has_file else "✗"))
            self._table.setItem(row, 1, QTableWidgetItem("✓" if has_json else "✗"))
            self._table.setItem(row, 2, QTableWidgetItem(doc.label))
            self._table.setItem(
                row, 3, QTableWidgetItem(doc.added.strftime("%Y-%m-%d"))
            )
            self._table.setItem(row, 4, QTableWidgetItem(doc.uuid))
            for col in range(len(_COLS)):
                item = self._table.item(row, col)
                if item:
                    item.setData(Qt.ItemDataRole.UserRole, doc.uuid)

    def _reload_preserving_selection(self) -> None:
        """Reload docs + table while keeping the current selection intact."""
        selected_uuids = {d.uuid for d in self._selected_docs()}
        self._docs = self._load_documents()
        self._refresh_table(self._get_filtered_docs())
        if selected_uuids:
            for row in range(self._table.rowCount()):
                item = self._table.item(row, 4)
                if item and item.text() in selected_uuids:
                    self._table.selectRow(row)
                    break  # single-doc detail pane; first match is enough
        self._on_selection_changed()
        self._pill_pool.rebuild(self._docs)
        self._pill_pool.set_active_tags(self._active_tag_filter)
        carried = {t for d in self._selected_docs() for t in d.tags}
        self._pill_pool.set_carried_tags(carried)

    def _apply_filter(self, text: str) -> None:
        self._refresh_table(self._get_filtered_docs())

    def _selected_doc(self) -> Document | None:
        """Return the current (last-clicked) document for detail pane display."""
        row = self._table.currentRow()
        if row < 0:
            return None
        uuid_item = self._table.item(row, 4)
        if not uuid_item:
            return None
        return next((d for d in self._docs if d.uuid == uuid_item.text()), None)

    def _selected_docs(self) -> list[Document]:
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

        menu = QMenu(self)
        single = len(docs) == 1
        doc = docs[0] if single else None

        if single:
            act_label = menu.addAction("Label")
            act_open_dir = menu.addAction("Open dir")
            act_open_pdf = menu.addAction("Open PDF")
            act_open_pdf.setEnabled((doc.path / "original.pdf").exists())
            act_open_url = menu.addAction("Open URL")
            act_open_url.setEnabled(bool(doc.source_url))
            menu.addSeparator()
        else:
            act_label = act_open_dir = act_open_pdf = act_open_url = None

        act_tag = menu.addAction(f"Tag {len(docs)} selected\u2026")
        all_tags = sorted({t for d in docs for t in d.tags})
        tag_actions: dict = {}
        if all_tags:
            remove_menu = menu.addMenu("Remove tag")
            tag_actions = {remove_menu.addAction(t): t for t in all_tags}

        menu.addSeparator()
        act_copy_uuid = menu.addAction("Copy UUID") if single else None
        act_copy_quotes = menu.addAction(f"Copy quotes ({len(docs)}) to clipboard")
        menu.addSeparator()
        act_delete = menu.addAction(f"Delete {len(docs)} document(s)\u2026")

        action = menu.exec(self._table.viewport().mapToGlobal(pos))
        if action is None:
            return

        if action is act_label:
            self._on_label_doc()
        elif action is act_open_dir:
            self._on_open_dir()
        elif action is act_open_pdf and doc:
            subprocess.Popen(["xdg-open", str(doc.path / "original.pdf")])
        elif action is act_open_url and doc:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl(doc.source_url))
        elif action is act_tag:
            if not self._evidence_set:
                return
            tag_name = self._ask_tag_name()
            if not tag_name:
                return
            tag_name = self._tag_service.qualify(tag_name, self._evidence_set.slug)
            for d in docs:
                self._assign_tag_to_doc(tag_name, d)
            self._reload_preserving_selection()
            self.window().statusBar().showMessage(
                f"{len(docs)} docs tagged '{tag_name}'", 3000
            )
        elif action in tag_actions:
            tag_name = tag_actions[action]
            for d in docs:
                if tag_name in d.tags:
                    self._remove_tag_from_doc(tag_name, d)
            self._reload_preserving_selection()
            self.window().statusBar().showMessage(
                f"Removed tag '{tag_name}' from {len(docs)} doc(s)", 3000
            )
        elif action is act_copy_uuid and doc:
            from PySide6.QtWidgets import QApplication

            QApplication.clipboard().setText(doc.uuid)
        elif action is act_copy_quotes:
            from PySide6.QtWidgets import QApplication

            from evid.core.prompt import quotes_markdown

            md = quotes_markdown([d.path for d in docs])
            if md:
                QApplication.clipboard().setText(md)
                self.window().statusBar().showMessage(
                    f"Copied quotes from {len(docs)} doc(s) to clipboard", 3000
                )
            else:
                self.window().statusBar().showMessage(
                    "No labelled quotes found in selection", 3000
                )
        elif action is act_delete:
            preview = ", ".join(d.label[:30] for d in docs[:3])
            if len(docs) > 3:
                preview += f" … +{len(docs) - 3} more"
            reply = QMessageBox.question(
                self,
                "Delete documents",
                f"Permanently delete {len(docs)} document(s)?\n{preview}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            for d in docs:
                try:
                    shutil.rmtree(d.path)
                except Exception:
                    logger.exception("Failed to delete doc %s", d.uuid)
            self._reload_preserving_selection()
            self.window().statusBar().showMessage(
                f"Deleted {len(docs)} document(s)", 3000
            )

    def _ask_tag_name(self) -> str:
        """Show a dialog with an editable combo of existing tags; return chosen name or ''."""
        from PySide6.QtWidgets import (
            QComboBox,
            QDialog,
            QDialogButtonBox,
            QFormLayout,
        )

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

    def _on_selection_changed(self) -> None:
        doc = self._selected_doc()
        if not doc:
            self._label_keys_list.clear()
            self._label_key_text.clear()
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

        # Compact UUID display
        self._detail_uuid_full = doc.uuid
        short = doc.uuid[:16] + "…" if len(doc.uuid) > 16 else doc.uuid
        self._detail_uuid.setText(short)
        self._detail_uuid.setToolTip(doc.uuid)

        self._detail_title.setText(info.get("title", ""))
        self._detail_authors.setText(info.get("authors", ""))
        self._detail_dates.setText(info.get("dates", ""))
        self._detail_tags.setText(info.get("tags", ""))
        self._detail_label.setText(info.get("label", ""))
        self._detail_url.setText(info.get("url", ""))
        self._detail_notes.setPlainText(meta.get("notes", ""))
        self._update_anon_preview()
        carried = {t.strip() for t in info.get("tags", "").split(",") if t.strip()}
        self._pill_pool.set_carried_tags(carried)
        self._load_label_keys(doc)

    def _on_save_detail(self) -> None:
        doc = self._selected_doc()
        if not doc or not self._evidence_set:
            return
        from evid.core.models import InfoModel

        info_path = doc.path / "info.yml"
        meta_path = doc.path / "evidmgr_meta.yml"

        info: dict = {}
        if info_path.exists():
            with info_path.open("r", encoding="utf-8") as f:
                info = yaml.safe_load(f) or {}

        info["title"] = self._detail_title.text().strip()
        info["authors"] = self._detail_authors.text().strip()
        info["dates"] = self._detail_dates.text().strip()
        info["tags"] = self._detail_tags.text().strip()
        info["label"] = self._detail_label.text().strip()
        info["url"] = self._detail_url.text().strip()

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
        self._refresh_table(self._get_filtered_docs())
        self._pill_pool.rebuild(self._docs)
        self._pill_pool.set_active_tags(self._active_tag_filter)
        carried = {t.strip() for t in self._detail_tags.text().split(",") if t.strip()}
        self._pill_pool.set_carried_tags(carried)

    # ── anon mode ─────────────────────────────────────────────────────────

    def _on_anon_mode_radio(self, btn_id: int) -> None:
        from evid.models import AnonMode

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
                    self._evidence_set = parent._set_manager.load_set(
                        self._evidence_set.slug
                    )
                except Exception:
                    logger.exception(
                        "Failed to save anon mode for %s", self._evidence_set.slug
                    )
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
        rb_style = f"color:{color}; font-weight:bold; border:none;"
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
            self._entity_table.setItem(
                row, 0, QTableWidgetItem(entity.get("entity_type", ""))
            )
            self._entity_table.setItem(
                row, 1, QTableWidgetItem(entity.get("original", ""))
            )
            self._entity_table.setItem(
                row, 2, QTableWidgetItem(entity.get("placeholder", ""))
            )
            self._entity_table.setItem(row, 3, QTableWidgetItem(entity.get("fake", "")))
            self._entity_table.setItem(
                row, 4, QTableWidgetItem(", ".join(entity.get("variants", [])))
            )

    def _on_set_current_yaml(self) -> None:
        if not self._current_yaml_path or not self._evidence_set:
            return
        parent = self.window()
        if hasattr(parent, "_anon_service"):
            parent._anon_service.set_current(
                self._evidence_set, self._current_yaml_path
            )
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
            entities.append(
                {
                    "entity_type": cell(0),
                    "original": cell(1),
                    "placeholder": cell(2),
                    "fake": cell(3),
                    "variants": variants,
                }
            )
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
        from evid.gui.workers import AnonExtractWorker

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

        selected = [
            item.data(Qt.ItemDataRole.UserRole) for item in doc_list.selectedItems()
        ]
        if not selected:
            return

        parent = self.window()
        if not hasattr(parent, "_anon_service"):
            return
        worker = AnonExtractWorker(parent._anon_service, self._evidence_set, selected)
        worker.finished.connect(
            self._on_anon_extract_done
        )  # AutoConnection → main thread
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
        from evid.models import AnonMode, SetType

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
                result = parent._anon_service.pseudonymize(
                    text[:4000], self._evidence_set, mode
                )
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

        from evid.gui.workers import UrlFetchWorker

        fetch_dlg = QProgressDialog("Fetching URL…", "Cancel", 0, 0, self)
        fetch_dlg.setWindowTitle("Downloading")
        fetch_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        fetch_dlg.show()

        self._fetch_dlg = fetch_dlg
        self._fetch_worker = None  # will be set right after so GC doesn't drop it
        worker = UrlFetchWorker(url.strip())
        self._fetch_worker = worker
        worker.ready.connect(self._on_url_ready)  # AutoConnection → main thread
        worker.error.connect(self._on_url_error)
        self._workers.append(worker)
        worker.start()

    def _on_url_ready(
        self, pdf_path_str: str, page_title: str, authors: str, url: str
    ) -> None:
        try:
            fetch_dlg = self._fetch_dlg
            worker = self._fetch_worker
            self._fetch_dlg = None
            self._fetch_worker = None
            if fetch_dlg:
                fetch_dlg.close()
            if not self._evidence_set:
                QMessageBox.warning(
                    self, "No set", "Select an evidence set before adding a document."
                )
                return
            pdf_path = Path(pdf_path_str)
            dlg = AddDocDialog(
                pdf_path, self, url=url, title=page_title, authors=authors
            )
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

    def _start_ingest(self, pdf_path: Path, dlg: AddDocDialog) -> None:
        self._open_in_labeller_after_ingest = dlg.open_in_labeller
        if not self._evidence_set:
            QMessageBox.warning(self, "No set", "Select an evidence set first.")
            return
        # Detect duplicate before spawning a worker to avoid a cross-thread race
        # on the fast "already ingested → return early" code path.
        try:
            import hashlib
            import uuid as _uuid

            with pdf_path.open("rb") as fh:
                digest = hashlib.sha256(fh.read()).digest()[:16]
            doc_uuid = _uuid.UUID(bytes=digest).hex
            doc_dir = self._evidence_set.path / "docs" / doc_uuid
            if doc_dir.exists():
                QMessageBox.information(
                    self,
                    "Already exists",
                    f"This document was already added to '{self._evidence_set.name}'.",
                )
                return
        except Exception:
            logger.exception("Duplicate check failed; proceeding with ingest")
        from evid.gui.workers import IngestWorker
        from evid.services.doc_ingester import DocIngester
        from evid.services.vec_service import VecService

        progress_dlg = QProgressDialog(f"Ingesting {pdf_path.name}…", None, 0, 7, self)
        progress_dlg.setWindowTitle("Ingesting")
        progress_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dlg.show()

        if self._evidence_set:
            self._vec_service.close(self._evidence_set.slug)
        worker_vec = VecService()
        worker_ingester = DocIngester(vec_service=worker_vec)

        worker = IngestWorker(
            worker_ingester,
            pdf_path,
            self._evidence_set,
            label=dlg.label,
            title=dlg.title,
            authors=dlg.authors,
            dates=dlg.dates,
            tags=dlg.tags,
            source_url=dlg.url,
            temp_dir=getattr(dlg, "_temp_dir", None),
        )
        self._ingest_dlg = progress_dlg
        worker.progress.connect(
            self._on_ingest_progress
        )  # AutoConnection → main thread
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
            self._refresh_table(self._get_filtered_docs())
            self._pill_pool.rebuild(self._docs)
            self._pill_pool.set_active_tags(self._active_tag_filter)
            if self._open_in_labeller_after_ingest:
                self._open_in_labeller_after_ingest = False
                for row in range(self._table.rowCount()):
                    item = self._table.item(row, 4)
                    if item and item.text() == doc_uuid:
                        self._table.selectRow(row)
                        break
                self._on_label_doc()
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
            QMessageBox.information(
                self, "All indexed", "All documents are already indexed."
            )
            return

        progress_dlg = QProgressDialog(
            f"Indexing {len(unindexed)} document(s)…", None, 0, len(unindexed), self
        )
        progress_dlg.setWindowTitle("Indexing")
        progress_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dlg.show()

        from evid.gui.workers import IndexWorker
        from evid.services.doc_ingester import DocIngester
        from evid.services.vec_service import VecService

        self._vec_service.close(self._evidence_set.slug)
        worker_vec = VecService()
        worker_ingester = DocIngester(vec_service=worker_vec)

        self._index_dlg = progress_dlg
        worker = IndexWorker(worker_ingester, unindexed, self._evidence_set)
        worker.progress.connect(self._on_index_progress)  # AutoConnection → main thread
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
            subprocess.Popen([editor, path])
        else:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _on_open_dir(self) -> None:
        doc = self._selected_doc()
        if doc:
            self._open_with_editor(str(doc.path))

    def _on_label_doc(self) -> None:
        doc = self._selected_doc()
        if not doc:
            return
        self._labeler.label_doc(doc.path, doc.uuid)

    # ── tag helpers ───────────────────────────────────────────────────────

    def _get_filtered_docs(self) -> list[Document]:
        """AND-filter docs by label text filter AND active tag filter."""
        text = self._filter.text().lower()
        result = []
        for doc in self._docs:
            if text and text not in doc.label.lower():
                continue
            if self._active_tag_filter and not self._active_tag_filter.issubset(
                set(doc.tags)
            ):
                continue
            result.append(doc)
        return result

    def _assign_tag_to_doc(self, tag_name: str, doc: Document) -> None:
        """Add *tag_name* to *doc* in both TagService and info.yml."""
        from evid.models import TagItem

        if not self._evidence_set:
            return
        try:
            self._tag_service.get_tag(tag_name)
        except KeyError:
            self._tag_service.create_tag(tag_name, self._evidence_set.slug)
        self._tag_service.add_items(
            tag_name, [TagItem(set_slug=self._evidence_set.slug, doc_uuid=doc.uuid)]
        )

        info_path = doc.path / "info.yml"
        try:
            info: dict = {}
            if info_path.exists():
                with info_path.open("r", encoding="utf-8") as f:
                    info = yaml.safe_load(f) or {}
            existing = [t.strip() for t in info.get("tags", "").split(",") if t.strip()]
            if tag_name not in existing:
                existing.append(tag_name)
                info["tags"] = ", ".join(existing)
                with info_path.open("w", encoding="utf-8") as f:
                    yaml.safe_dump(info, f, allow_unicode=True)
        except Exception:
            logger.exception("Failed to update info.yml tags for %s", doc.uuid)

    def _remove_tag_from_doc(self, tag_name: str, doc: Document) -> None:
        """Remove *tag_name* from *doc* in TagService and info.yml."""
        if not self._evidence_set:
            return
        try:
            self._tag_service.remove_item(tag_name, self._evidence_set.slug, doc.uuid)
        except Exception:
            logger.debug("Tag %s not in TagService for %s", tag_name, doc.uuid)

        info_path = doc.path / "info.yml"
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
            logger.exception("Failed to remove tag from info.yml for %s", doc.uuid)

    # ── UUID row actions ──────────────────────────────────────────────────

    def _on_uuid_view(self) -> None:
        doc = self._selected_doc()
        if not doc:
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        url = self._detail_url.text().strip()
        if url:
            QDesktopServices.openUrl(QUrl(url))
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(doc.path)))

    def _on_uuid_copy(self) -> None:
        from PySide6.QtWidgets import QApplication

        if self._detail_uuid_full:
            QApplication.clipboard().setText(self._detail_uuid_full)

    # ── label key list ────────────────────────────────────────────────────

    def _load_label_keys(self, doc: Document) -> None:
        """Populate the label keys list from doc's label.json."""
        import json

        self._label_keys_list.clear()
        self._label_key_text.clear()
        json_path = doc.path / "label.json"
        if not json_path.exists():
            return
        try:
            with json_path.open("r", encoding="utf-8") as f:
                entries = json.load(f)
        except Exception:
            logger.debug("Could not read label.json for %s", doc.uuid)
            return
        for entry in entries:
            val = entry.get("value", {}) if isinstance(entry, dict) else {}
            key = val.get("key", "")
            if not key or key == "main":
                continue
            item = QListWidgetItem(key)
            item.setData(Qt.ItemDataRole.UserRole, val)
            self._label_keys_list.addItem(item)

    def _on_label_key_selected(self, current, _previous) -> None:
        if current is None:
            self._label_key_text.clear()
            return
        val: dict = current.data(Qt.ItemDataRole.UserRole) or {}
        text = val.get("text", "")
        note = val.get("note", "")
        page = val.get("opage", "")
        section = val.get("title", "")
        parts = []
        if section:
            parts.append(f"§ {section}")
        if page:
            parts.append(f"p. {page}")
        if text:
            parts.append(text)
        if note:
            parts.append(f"\n[note] {note}")
        self._label_key_text.setPlainText("\n".join(parts))

    # ── pill pool callbacks ────────────────────────────────────────────────

    def _on_pill_clicked(self, tag_name: str) -> None:
        doc = self._selected_doc()
        if doc:
            # Toggle tag on the selected document
            if tag_name in doc.tags:
                self._remove_tag_from_doc(tag_name, doc)
            else:
                self._assign_tag_to_doc(tag_name, doc)
            self._reload_preserving_selection()
        else:
            # Toggle tag filter
            if tag_name in self._active_tag_filter:
                self._active_tag_filter.discard(tag_name)
            else:
                self._active_tag_filter.add(tag_name)
            self._pill_pool.set_active_tags(self._active_tag_filter)
            self._refresh_table(self._get_filtered_docs())

    def _on_pill_menu(self, tag_name: str, global_pos) -> None:
        """Show popover listing docs that carry this tag; click selects the row."""
        menu = QMenu(self)
        docs_with_tag = [d for d in self._docs if tag_name in d.tags]
        if not docs_with_tag:
            menu.addAction("(no documents)").setEnabled(False)
        else:
            for doc in docs_with_tag:
                action = menu.addAction(doc.label)
                action.setData(doc.uuid)
        chosen = menu.exec(global_pos)
        if chosen and chosen.data():
            uuid = chosen.data()
            for row in range(self._table.rowCount()):
                item = self._table.item(row, 4)
                if item and item.text() == uuid:
                    self._table.selectRow(row)
                    self._table.scrollToItem(item)
                    break

    def _on_new_tag_pill(self) -> None:
        tag_name = self._ask_tag_name()
        if not tag_name or not self._evidence_set:
            return
        tag_name = self._tag_service.qualify(tag_name, self._evidence_set.slug)
        doc = self._selected_doc()
        if doc:
            self._assign_tag_to_doc(tag_name, doc)
            self._reload_preserving_selection()
        else:
            # Just ensure tag exists in registry
            try:
                self._tag_service.get_tag(tag_name)
            except KeyError:
                self._tag_service.create_tag(tag_name, self._evidence_set.slug)
            self._pill_pool.rebuild(self._docs)
            self._pill_pool.set_active_tags(self._active_tag_filter)

    # ── drag-drop from pill pool onto table ────────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        if obj is not self._table.viewport():
            return super().eventFilter(obj, event)
        ev_type = event.type()
        if ev_type == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                idx = self._table.indexAt(event.position().toPoint())
                self._doc_drag_start = (
                    event.position().toPoint() if idx.isValid() else None
                )
            return False
        if ev_type == QEvent.Type.MouseMove:
            if (
                self._doc_drag_start is not None
                and event.buttons() & Qt.MouseButton.LeftButton
            ):
                from PySide6.QtWidgets import QApplication

                dist = (
                    event.position().toPoint() - self._doc_drag_start
                ).manhattanLength()
                if dist >= QApplication.startDragDistance():
                    self._doc_drag_start = None
                    self._start_doc_drag()
                    return True
            return False
        if ev_type == QEvent.Type.MouseButtonRelease:
            self._doc_drag_start = None
            return False
        if ev_type == QEvent.Type.DragEnter:
            if event.mimeData().hasFormat(TagPill.MIME_TYPE):
                event.acceptProposedAction()
                return True
        elif ev_type == QEvent.Type.DragMove:
            if event.mimeData().hasFormat(TagPill.MIME_TYPE):
                event.acceptProposedAction()
                # Highlight hovered row
                index = self._table.indexAt(event.position().toPoint())
                if index.isValid():
                    self._table.blockSignals(True)
                    self._table.selectRow(index.row())
                    self._table.blockSignals(False)
                return True
        elif ev_type == QEvent.Type.Drop:
            if event.mimeData().hasFormat(TagPill.MIME_TYPE):
                tag_name = event.mimeData().data(TagPill.MIME_TYPE).toStdString()
                index = self._table.indexAt(event.position().toPoint())
                if index.isValid() and self._evidence_set:
                    uuid_item = self._table.item(index.row(), 4)
                    if uuid_item:
                        doc = next(
                            (d for d in self._docs if d.uuid == uuid_item.text()), None
                        )
                        if doc:
                            tag_name = self._tag_service.qualify(
                                tag_name, self._evidence_set.slug
                            )
                            self._assign_tag_to_doc(tag_name, doc)
                            self._reload_preserving_selection()
                            self.window().statusBar().showMessage(
                                f"Tagged '{doc.label}' with {tag_name}", 3000
                            )
                event.acceptProposedAction()
                return True
        return super().eventFilter(obj, event)

    # ── doc drag-to-sidebar ────────────────────────────────────────────────

    def _start_doc_drag(self) -> None:
        doc = self._selected_doc()
        if not doc or not self._evidence_set:
            return
        from PySide6.QtGui import QPainter, QPixmap

        mime = QMimeData()
        payload = json.dumps(
            {"doc_uuid": doc.uuid, "src_slug": self._evidence_set.slug}
        )
        mime.setData(_DOC_MIME_TYPE, payload.encode("utf-8"))

        label_text = doc.label[:50]
        fm = self._table.fontMetrics()
        pix = QPixmap(fm.horizontalAdvance(label_text) + 16, fm.height() + 8)
        pix.fill(Qt.GlobalColor.white)
        p = QPainter(pix)
        p.drawText(
            pix.rect().adjusted(8, 4, -8, -4), Qt.AlignmentFlag.AlignVCenter, label_text
        )
        p.end()

        drag = QDrag(self._table)
        drag.setMimeData(mime)
        drag.setPixmap(pix)
        drag.exec(Qt.DropAction.CopyAction)

    # ── copy doc to another set ────────────────────────────────────────────

    def navigate_to_doc(self, uuid: str) -> None:
        """Select the doc with *uuid* in the table and show the Detail subtab.

        If the document is hidden by an active filter, the filter is cleared first.
        """

        def _select_row(uuid: str) -> bool:
            for row in range(self._table.rowCount()):
                item = self._table.item(row, 4)
                if item and item.text() == uuid:
                    self._table.selectRow(row)
                    self._table.scrollTo(self._table.model().index(row, 0))
                    self._right_tabs.setCurrentIndex(0)
                    return True
            return False

        if _select_row(uuid):
            return
        # May be hidden by filter — clear it and try again
        self._filter.clear()
        if not _select_row(uuid):
            logger.warning("navigate_to_doc: UUID %s not found in current set", uuid)

    def start_copy_doc(self, src_doc_dir: Path, dest_set: object) -> None:
        """Copy *src_doc_dir* into *dest_set* and re-index into its vecdb."""
        from evid.gui.workers import CopyDocWorker
        from evid.services.vec_service import VecService

        worker_vec = VecService()
        worker = CopyDocWorker(src_doc_dir, dest_set, vec_service=worker_vec)
        worker.finished.connect(self._on_copy_done)
        worker.error.connect(self._on_copy_error)
        self._workers.append(worker)
        worker.start()

    def _on_copy_done(self, doc_uuid: str, dest_slug: str) -> None:
        try:
            self._signals.doc_ingested.emit(dest_slug, doc_uuid)
            self.window().statusBar().showMessage(
                f"Copied {doc_uuid[:8]}… to '{dest_slug}'", 4000
            )
        except Exception:
            logger.exception("Error completing copy of %s to %s", doc_uuid, dest_slug)

    def _on_copy_error(self, msg: str) -> None:
        try:
            QMessageBox.critical(self, "Copy failed", msg)
        except Exception:
            logger.exception("Error handling copy failure: %s", msg)

    # ── typ file watcher ───────────────────────────────────────────────────

    def _on_label_done(self, doc_uuid: str) -> None:
        try:
            self._docs = self._load_documents()
            self._refresh_table(self._get_filtered_docs())
            self._pill_pool.rebuild(self._docs)
            self._pill_pool.set_active_tags(self._active_tag_filter)
            if self._evidence_set:
                self._signals.labels_updated.emit(self._evidence_set.slug, doc_uuid)
            self.window().statusBar().showMessage("Labels updated", 2000)
        except Exception:
            logger.exception("Error after label regeneration for %s", doc_uuid)

    def _on_label_error(self, msg: str) -> None:
        logger.warning("Label regeneration failed: %s", msg)
        with contextlib.suppress(Exception):
            self.window().statusBar().showMessage(
                f"Label compile failed: {msg[:120]}", 5000
            )
