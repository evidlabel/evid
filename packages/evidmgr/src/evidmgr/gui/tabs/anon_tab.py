"""Anonymize tab — YAML history + entity editor."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from evidmgr.gui.signals import AppSignals
    from evidmgr.models import EvidenceSet
    from evidmgr.services.anon_service import AnonService

logger = logging.getLogger(__name__)

_ENTITY_COLS = ["Type", "Original", "Placeholder", "Fake", "Variants"]


class AnonTab(QWidget):
    def __init__(self, anon_service: "AnonService", signals: "AppSignals") -> None:
        super().__init__()
        self._svc = anon_service
        self._signals = signals
        self._evidence_set: "EvidenceSet | None" = None
        self._current_yaml_path: Path | None = None
        self._workers: list = []

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── left: YAML history ────────────────────────────────────────────
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("YAML history (newest first)"))
        self._history_list = QListWidget()
        self._history_list.itemClicked.connect(self._on_yaml_selected)
        lv.addWidget(self._history_list)

        hist_btns = QHBoxLayout()
        self._set_current_btn = QPushButton("★ Set current")
        self._set_current_btn.clicked.connect(self._on_set_current)
        self._gen_yaml_btn = QPushButton("Generate new YAML…")
        self._gen_yaml_btn.clicked.connect(self._on_generate_yaml)
        hist_btns.addWidget(self._set_current_btn)
        hist_btns.addWidget(self._gen_yaml_btn)
        lv.addLayout(hist_btns)
        splitter.addWidget(left)

        # ── right: entity editor ──────────────────────────────────────────
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 0, 0, 0)
        rv.addWidget(QLabel("Entity editor"))
        self._entity_table = QTableWidget(0, len(_ENTITY_COLS))
        self._entity_table.setHorizontalHeaderLabels(_ENTITY_COLS)
        self._entity_table.horizontalHeader().setStretchLastSection(True)
        rv.addWidget(self._entity_table)

        entity_btns = QHBoxLayout()
        self._save_btn = QPushButton("Save")
        self._save_btn.clicked.connect(self._on_save_entities)
        self._gen_fakes_btn = QPushButton("Generate fakes")
        self._gen_fakes_btn.clicked.connect(self._on_generate_fakes)
        entity_btns.addWidget(self._save_btn)
        entity_btns.addWidget(self._gen_fakes_btn)
        rv.addLayout(entity_btns)
        splitter.addWidget(right)
        splitter.setSizes([300, 700])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        signals.set_selected.connect(self._on_set_selected)

    # ── private ───────────────────────────────────────────────────────────

    def _on_set_selected(self, slug: str) -> None:
        parent = self.window()
        if hasattr(parent, "_set_manager"):
            try:
                self._evidence_set = parent._set_manager.load_set(slug)
                self._refresh_history()
            except Exception:
                logger.exception("Failed to load set %s", slug)

    def _refresh_history(self) -> None:
        self._history_list.clear()
        if not self._evidence_set:
            return
        yamls = self._svc.list_yamls(self._evidence_set)
        for y in yamls:
            label = y.path.name
            if y.is_current:
                label = f"★ {label}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, str(y.path))
            self._history_list.addItem(item)

    def _on_yaml_selected(self, item: QListWidgetItem) -> None:
        path_str = item.data(Qt.ItemDataRole.UserRole)
        self._current_yaml_path = Path(path_str)
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
            variants_str = ", ".join(entity.get("variants", []))
            self._entity_table.setItem(row, 4, QTableWidgetItem(variants_str))

    def _on_set_current(self) -> None:
        if self._current_yaml_path and self._evidence_set:
            self._svc.set_current(self._evidence_set, self._current_yaml_path)
            self._refresh_history()

    def _on_save_entities(self) -> None:
        if not self._current_yaml_path:
            return
        entities = []
        for row in range(self._entity_table.rowCount()):
            def cell(c):
                item = self._entity_table.item(row, c)
                return item.text() if item else ""
            variants_raw = cell(4)
            variants = [v.strip() for v in variants_raw.split(",") if v.strip()]
            entities.append({
                "entity_type": cell(0),
                "original": cell(1),
                "placeholder": cell(2),
                "fake": cell(3),
                "variants": variants,
            })
        self._svc.save_entity_yaml(self._evidence_set, self._current_yaml_path, entities)
        logger.info("Saved entity YAML: %s", self._current_yaml_path.name)

    def _on_generate_fakes(self) -> None:
        if not self._current_yaml_path or not self._evidence_set:
            return
        lang = self._evidence_set.anon_language
        self._svc.generate_fakes(self._current_yaml_path, lang)
        self._load_entities_to_table(self._current_yaml_path)

    def _on_generate_yaml(self) -> None:
        if not self._evidence_set:
            QMessageBox.warning(self, "No set", "Select an evidence set first.")
            return
        from evidmgr.gui.workers import AnonExtractWorker  # noqa: PLC0415

        # Simple doc selection dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("Select documents")
        dlg.resize(400, 300)
        lv = QVBoxLayout(dlg)
        doc_list = QListWidget()
        doc_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        docs_dir = self._evidence_set.path / "docs"
        if docs_dir.exists():
            for d in docs_dir.iterdir():
                if d.is_dir():
                    item = QListWidgetItem(d.name)
                    item.setData(Qt.ItemDataRole.UserRole, d.name)
                    doc_list.addItem(item)
        lv.addWidget(doc_list)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lv.addWidget(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        selected = [item.data(Qt.ItemDataRole.UserRole) for item in doc_list.selectedItems()]
        if not selected:
            return

        worker = AnonExtractWorker(self._svc, self._evidence_set, selected)
        worker.finished.connect(lambda path: (
            self._refresh_history(),
            self._signals.anon_yaml_created.emit(self._evidence_set.slug),
        ))
        worker.error.connect(lambda msg: QMessageBox.critical(self, "Extraction failed", msg))
        self._workers.append(worker)
        worker.start()
