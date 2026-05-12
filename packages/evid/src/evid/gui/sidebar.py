"""Sidebar: evidence set list with visual anon state."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

DOC_MIME_TYPE = "application/x-evidmgr-doc"

if TYPE_CHECKING:
    from evid.gui.signals import AppSignals
    from evid.models import EvidenceSet
    from evid.services.set_manager import SetManager

_MODE_COLOR = {
    "real": "#c97a00",
    "placeholder": "#b86800",
    "fake": "#c00000",
}
_MODE_SUFFIX = {
    "real": "",
    "placeholder": " [PH]",
    "fake": " [FAKE]",
}


class Sidebar(QWidget):
    def __init__(
        self,
        set_manager: SetManager,
        signals: AppSignals,
    ) -> None:
        super().__init__()
        self._set_manager = set_manager
        self._signals = signals
        self._sets: list[EvidenceSet] = []
        self._active_set: EvidenceSet | None = None

        self.setFixedWidth(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        layout.addWidget(QLabel("Evidence Sets"))
        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_set_clicked)
        self._list.viewport().setAcceptDrops(True)
        self._list.viewport().installEventFilter(self)
        layout.addWidget(self._list)

        new_btn = QPushButton("+ New set")
        new_btn.clicked.connect(self._on_new_set)
        layout.addWidget(new_btn)

        import_btn = QPushButton("Import evid dir…")
        import_btn.clicked.connect(self._on_import_evid_dir)
        layout.addWidget(import_btn)

        signals.anon_mode_changed.connect(self._on_anon_mode_changed)

        self.refresh()

    # ── public ──────────────────────────────────────────────────────────────

    def refresh(self) -> None:

        self._sets = self._set_manager.list_sets()
        self._list.clear()
        for s in self._sets:
            item = self._make_item(s)
            self._list.addItem(item)
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    def select_first(self) -> None:
        """Select and activate the top set. Call after all signal slots are connected."""
        if self._list.count() > 0:
            item = self._list.item(0)
            self._list.setCurrentItem(item)
            self._on_set_clicked(item)

    def active_set(self) -> EvidenceSet | None:
        return self._active_set

    # ── private ──────────────────────────────────────────────────────────────

    def _make_item(self, s: EvidenceSet) -> QListWidgetItem:
        from evid.models import SetType

        if s.set_type == SetType.ANON:
            mode_val = s.anon_mode.value
            suffix = _MODE_SUFFIX.get(mode_val, "")
            color = _MODE_COLOR.get(mode_val, "#c97a00")
            label = f"[A]{suffix} {s.name}"
            item = QListWidgetItem(label)
            item.setForeground(QBrush(QColor(color)))
            f = item.font()
            f.setBold(True)
            item.setFont(f)
        else:
            item = QListWidgetItem(s.name)

        item.setData(Qt.ItemDataRole.UserRole, s.slug)
        return item

    def _on_set_clicked(self, item: QListWidgetItem) -> None:
        slug = item.data(Qt.ItemDataRole.UserRole)
        self._active_set = self._set_manager.load_set(slug)
        self._signals.set_selected.emit(slug)

    def _on_anon_mode_changed(self, _mode_str: str) -> None:
        """Refresh list items so the active set's mode label stays current."""
        if self._active_set is None:
            return
        try:
            self._active_set = self._set_manager.load_set(self._active_set.slug)
        except Exception:
            return
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == self._active_set.slug:
                new_item = self._make_item(self._active_set)
                # Swap text/visual in-place (QListWidget items can't be replaced, so
                # we update the existing item's display properties directly)
                item.setText(new_item.text())
                item.setForeground(new_item.foreground())
                item.setFont(new_item.font())
                break

    def _on_import_evid_dir(self) -> None:
        from pathlib import Path

        from PySide6.QtWidgets import (
            QComboBox,
            QDialog,
            QDialogButtonBox,
            QFileDialog,
            QFormLayout,
            QLineEdit,
            QMessageBox,
        )

        from evid.services.import_service import (
            import_evid_dir,
            import_evid_dir_single,
        )

        chosen = QFileDialog.getExistingDirectory(self, "Select evid directory")
        if not chosen:
            return
        chosen_path = Path(chosen)

        dlg = QDialog(self)
        dlg.setWindowTitle("Import evid directory")
        form = QFormLayout(dlg)
        name_edit = QLineEdit(chosen_path.name)
        type_combo = QComboBox()
        type_combo.addItems(["normal", "anon"])
        form.addRow("Set name:", name_edit)
        form.addRow("Set type:", type_combo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        set_name = name_edit.text().strip() or chosen_path.name
        set_type = type_combo.currentText()

        try:
            import_evid_dir_single(chosen_path, set_name, self._set_manager, set_type)
            count = 1
        except ValueError:
            sets = import_evid_dir(chosen_path, self._set_manager, set_type)
            count = len(sets)

        self.refresh()
        QMessageBox.information(
            self, "Import complete", f"Imported {count} set(s) from\n{chosen}"
        )

    def _on_new_set(self) -> None:
        from PySide6.QtWidgets import (
            QComboBox,
            QDialog,
            QDialogButtonBox,
            QFormLayout,
            QLineEdit,
        )

        dlg = QDialog(self)
        dlg.setWindowTitle("New Evidence Set")
        form = QFormLayout(dlg)
        name_edit = QLineEdit()
        type_combo = QComboBox()
        type_combo.addItems(["normal", "anon"])
        form.addRow("Name:", name_edit)
        form.addRow("Type:", type_combo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec() == QDialog.DialogCode.Accepted and name_edit.text().strip():
            self._set_manager.create_set(
                name_edit.text().strip(),
                set_type=type_combo.currentText(),
            )
            self.refresh()

    # ── drag-and-drop: accept docs dragged from the docs table ───────────────

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is not self._list.viewport():
            return super().eventFilter(obj, event)
        ev_type = event.type()
        if ev_type == QEvent.Type.DragEnter:
            if event.mimeData().hasFormat(DOC_MIME_TYPE):
                event.acceptProposedAction()
                return True
        elif ev_type == QEvent.Type.DragMove:
            if event.mimeData().hasFormat(DOC_MIME_TYPE):
                item = self._list.itemAt(event.position().toPoint())
                if item:
                    self._list.setCurrentItem(item)
                event.acceptProposedAction()
                return True
        elif ev_type == QEvent.Type.DragLeave:
            # Restore selection to the active set
            self._restore_active_selection()
            return True
        elif ev_type == QEvent.Type.Drop:
            if event.mimeData().hasFormat(DOC_MIME_TYPE):
                item = self._list.itemAt(event.position().toPoint())
                if item:
                    dest_slug = item.data(Qt.ItemDataRole.UserRole)
                    raw = event.mimeData().data(DOC_MIME_TYPE).toStdString()
                    try:
                        payload = json.loads(raw)
                        src_slug = payload["src_slug"]
                        doc_uuid = payload["doc_uuid"]
                    except Exception:
                        event.ignore()
                        return True
                    if dest_slug != src_slug:
                        self._signals.copy_doc_to_set.emit(
                            src_slug, doc_uuid, dest_slug
                        )
                self._restore_active_selection()
                event.acceptProposedAction()
                return True
        return super().eventFilter(obj, event)

    def _restore_active_selection(self) -> None:
        if self._active_set is None:
            return
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == self._active_set.slug:
                self._list.setCurrentItem(item)
                break
