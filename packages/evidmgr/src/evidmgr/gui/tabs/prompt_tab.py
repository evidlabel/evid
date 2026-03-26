"""Prompt Builder tab — assembles evidence into a Markdown prompt."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from evidmgr.gui.signals import AppSignals
    from evidmgr.models import AnonMode
    from evidmgr.services.anon_service import AnonService
    from evidmgr.services.tag_service import TagService

logger = logging.getLogger(__name__)


class PromptTab(QWidget):
    def __init__(
        self,
        anon_service: "AnonService",
        tag_service: "TagService",
        signals: "AppSignals",
    ) -> None:
        super().__init__()
        self._anon_service = anon_service
        self._tag_service = tag_service
        self._signals = signals
        # list of (set_slug, doc_uuid)
        self._items: list[tuple[str, str]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── left: item list ───────────────────────────────────────────────
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("Evidence items (drag to re-order)"))
        self._item_list = QListWidget()
        self._item_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self._item_list.itemSelectionChanged.connect(self._rebuild_preview)
        lv.addWidget(self._item_list)

        item_btns = QHBoxLayout()
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self._on_clear)
        self._remove_btn = QPushButton("Remove selected")
        self._remove_btn.clicked.connect(self._on_remove_selected)
        item_btns.addWidget(self._clear_btn)
        item_btns.addWidget(self._remove_btn)
        lv.addLayout(item_btns)
        splitter.addWidget(left)

        # ── right: preview + export ───────────────────────────────────────
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 0, 0, 0)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Anon mode:"))
        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Real", "Placeholder", "Fake"])
        self._mode_combo.currentTextChanged.connect(self._rebuild_preview)
        mode_row.addWidget(self._mode_combo)
        mode_row.addStretch()
        rv.addLayout(mode_row)

        rv.addWidget(QLabel("Preview:"))
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setFont(self._preview.document().defaultFont())
        rv.addWidget(self._preview)

        export_row = QHBoxLayout()
        self._copy_btn = QPushButton("Copy to clipboard")
        self._copy_btn.clicked.connect(self._on_copy)
        self._save_btn = QPushButton("Save as file…")
        self._save_btn.clicked.connect(self._on_save)
        export_row.addWidget(self._copy_btn)
        export_row.addWidget(self._save_btn)
        export_row.addStretch()
        rv.addLayout(export_row)
        splitter.addWidget(right)
        splitter.setSizes([280, 820])

        layout.addWidget(splitter)

        signals.add_to_prompt.connect(self._on_add_item)
        signals.anon_mode_changed.connect(self._on_anon_mode_changed)

    # ── public ────────────────────────────────────────────────────────────

    def build_prompt(self) -> str:
        """Assemble the current item list into a Markdown prompt string."""
        from evidmgr.models import AnonMode  # noqa: PLC0415

        mode_text = self._mode_combo.currentText().lower()
        mode_map = {"real": AnonMode.REAL, "placeholder": AnonMode.PLACEHOLDER, "fake": AnonMode.FAKE}
        mode = mode_map.get(mode_text, AnonMode.REAL)

        parts = []
        parent = self.window()
        for i in range(self._item_list.count()):
            item = self._item_list.item(i)
            if item is None:
                continue
            set_slug, doc_uuid = item.data(Qt.ItemDataRole.UserRole)
            block = self._build_block(set_slug, doc_uuid, mode, parent)
            if block:
                parts.append(block)
        return "\n\n---\n\n".join(parts)

    # ── private ───────────────────────────────────────────────────────────

    def _on_add_item(self, set_slug: str, doc_uuid: str) -> None:
        if (set_slug, doc_uuid) in self._items:
            return
        self._items.append((set_slug, doc_uuid))
        label = self._resolve_label(set_slug, doc_uuid)
        item = QListWidgetItem(f"[{set_slug}] {label}")
        item.setData(Qt.ItemDataRole.UserRole, (set_slug, doc_uuid))
        self._item_list.addItem(item)
        self._rebuild_preview()

    def _on_clear(self) -> None:
        self._items.clear()
        self._item_list.clear()
        self._preview.setPlainText("")

    def _on_remove_selected(self) -> None:
        for item in self._item_list.selectedItems():
            row = self._item_list.row(item)
            self._item_list.takeItem(row)
        self._rebuild_preview()

    def _on_anon_mode_changed(self, mode_str: str) -> None:
        idx = {"real": 0, "placeholder": 1, "fake": 2}.get(mode_str, 0)
        self._mode_combo.setCurrentIndex(idx)
        self._rebuild_preview()

    def _rebuild_preview(self) -> None:
        self._preview.setPlainText(self.build_prompt())

    def _on_copy(self) -> None:
        from PySide6.QtWidgets import QApplication  # noqa: PLC0415
        QApplication.clipboard().setText(self._preview.toPlainText())

    def _on_save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save prompt", "prompt.md", "Text files (*.md *.txt)")
        if path:
            Path(path).write_text(self._preview.toPlainText(), encoding="utf-8")

    def _resolve_label(self, set_slug: str, doc_uuid: str) -> str:
        parent = self.window()
        if hasattr(parent, "_set_manager"):
            try:
                es = parent._set_manager.load_set(set_slug)
                info_path = es.path / "docs" / doc_uuid / "info.yml"
                if info_path.exists():
                    with info_path.open("r", encoding="utf-8") as f:
                        info = yaml.safe_load(f) or {}
                    return info.get("label", doc_uuid)
            except Exception:
                pass
        return doc_uuid

    def _build_block(self, set_slug: str, doc_uuid: str, mode: "AnonMode", parent) -> str:
        if not hasattr(parent, "_set_manager"):
            return ""
        try:
            es = parent._set_manager.load_set(set_slug)
            doc_dir = es.path / "docs" / doc_uuid

            info_path = doc_dir / "info.yml"
            if not info_path.exists():
                return ""
            with info_path.open("r", encoding="utf-8") as f:
                info = yaml.safe_load(f) or {}

            title = info.get("title") or info.get("label", doc_uuid)
            authors = info.get("authors", "")
            url = info.get("url", "")

            # Load labels from label.json
            json_path = doc_dir / "label.json"
            labels_text = ""
            if json_path.exists():
                with json_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                labels = [item["value"] for item in data if item["value"].get("key") != "main"]
                lines = []
                for lbl in labels:
                    opage = lbl.get("opage", "")
                    content = lbl.get("note") or lbl.get("text", "")
                    lines.append(f"- Page {opage}: {content}")
                labels_text = "\n".join(lines)

            block = f"# {title}\n\n"
            if authors:
                block += f"**Author:** {authors}\n\n"
            if url:
                block += f"**Link:** {url}\n\n"
            if labels_text:
                block += labels_text + "\n"

            # Apply anonymisation
            block = self._anon_service.pseudonymize(block, es, mode)
            return block
        except Exception:
            logger.exception("Failed to build block for %s/%s", set_slug, doc_uuid)
            return ""
