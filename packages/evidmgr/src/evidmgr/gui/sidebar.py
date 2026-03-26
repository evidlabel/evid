"""Sidebar: set list + 3-state anon mode control."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from evidmgr.gui.signals import AppSignals
    from evidmgr.models import AnonMode, EvidenceSet
    from evidmgr.services.set_manager import SetManager


class Sidebar(QWidget):
    def __init__(
        self,
        set_manager: "SetManager",
        signals: "AppSignals",
    ) -> None:
        super().__init__()
        self._set_manager = set_manager
        self._signals = signals
        self._sets: list["EvidenceSet"] = []
        self._active_set: "EvidenceSet | None" = None

        self.setFixedWidth(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Set list
        layout.addWidget(QLabel("Evidence Sets"))
        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_set_clicked)
        layout.addWidget(self._list)

        # New set button
        new_btn = QPushButton("+ New set")
        new_btn.clicked.connect(self._on_new_set)
        layout.addWidget(new_btn)

        # Anon mode (only shown for anon sets)
        self._anon_widget = QWidget()
        anon_layout = QVBoxLayout(self._anon_widget)
        anon_layout.setContentsMargins(0, 8, 0, 0)
        anon_layout.addWidget(QLabel("Anon mode:"))
        self._anon_buttons: list[QPushButton] = []
        btn_row = QHBoxLayout()
        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)
        for i, label in enumerate(["Real", "Placeholder", "Fake"]):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(26)
            self._btn_group.addButton(btn, i)
            self._anon_buttons.append(btn)
            btn_row.addWidget(btn)
        self._anon_buttons[0].setChecked(True)  # default: Real
        self._btn_group.idClicked.connect(self._on_anon_mode_changed)
        anon_layout.addLayout(btn_row)
        layout.addWidget(self._anon_widget)
        self._anon_widget.hide()

        self.refresh()

    # ── public ──────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        self._sets = self._set_manager.list_sets()
        self._list.clear()
        for s in self._sets:
            item = QListWidgetItem(s.name)
            item.setData(Qt.ItemDataRole.UserRole, s.slug)
            self._list.addItem(item)

    def active_set(self) -> "EvidenceSet | None":
        return self._active_set

    def anon_mode(self) -> "AnonMode":
        from evidmgr.models import AnonMode  # noqa: PLC0415

        idx = self._btn_group.checkedId()
        return [AnonMode.REAL, AnonMode.PLACEHOLDER, AnonMode.FAKE][max(0, idx)]

    # ── private ──────────────────────────────────────────────────────────────

    def _on_set_clicked(self, item: QListWidgetItem) -> None:
        from evidmgr.models import SetType  # noqa: PLC0415

        slug = item.data(Qt.ItemDataRole.UserRole)
        self._active_set = self._set_manager.load_set(slug)

        # Show/hide anon controls
        is_anon = self._active_set.set_type == SetType.ANON
        self._anon_widget.setVisible(is_anon)
        if is_anon:
            self._anon_buttons[0].setChecked(True)  # reset to Real on set change

        self._signals.set_selected.emit(slug)

    def _on_anon_mode_changed(self, btn_id: int) -> None:
        from evidmgr.models import AnonMode  # noqa: PLC0415

        modes = [AnonMode.REAL, AnonMode.PLACEHOLDER, AnonMode.FAKE]
        self._signals.anon_mode_changed.emit(modes[btn_id].value)

    def _on_new_set(self) -> None:
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QComboBox, QLineEdit  # noqa: PLC0415

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
