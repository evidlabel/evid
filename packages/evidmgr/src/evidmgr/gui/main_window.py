"""EvidMgrWindow — main application window."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from evidmgr.config import EvidmgrConfig
from evidmgr.gui.signals import AppSignals
from evidmgr.gui.sidebar import Sidebar
from evidmgr.gui.theme import apply_theme
from evidmgr.services.anon_service import AnonService
from evidmgr.services.doc_ingester import DocIngester
from evidmgr.services.set_manager import SetManager
from evidmgr.services.tag_service import TagService
from evidmgr.services.vec_service import VecService

logger = logging.getLogger(__name__)


class _QtLogHandler(logging.Handler):
    def __init__(self, widget: QPlainTextEdit) -> None:
        super().__init__()
        self._widget = widget
        self.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self._widget.appendPlainText(msg)
        self._widget.verticalScrollBar().setValue(self._widget.verticalScrollBar().maximum())


class _TabCycleFilter(QObject):
    def __init__(self, stack_widget, tab_bar) -> None:
        super().__init__()
        self._stack = stack_widget
        self._tab_bar = tab_bar

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if (
            event.type() == QEvent.Type.KeyPress
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            count = self._stack.count()
            idx = self._stack.currentIndex()
            if event.key() == Qt.Key.Key_PageUp:
                self._tab_bar.setCurrentIndex((idx - 1) % count)
                return True
            if event.key() == Qt.Key.Key_PageDown:
                self._tab_bar.setCurrentIndex((idx + 1) % count)
                return True
        return False


class EvidMgrWindow(QMainWindow):
    def __init__(self, config: EvidmgrConfig | None = None) -> None:
        super().__init__()
        self._config = config or EvidmgrConfig.load()
        data_dir = self._config.data_dir
        data_dir.mkdir(parents=True, exist_ok=True)

        # ── services ──────────────────────────────────────────────────────
        self._set_manager = SetManager(data_dir)
        self._vec_service = VecService()
        self._anon_service = AnonService()
        self._tag_service = TagService(data_dir)
        self._ingester = DocIngester(vec_service=self._vec_service)
        self._signals = AppSignals()

        self.setWindowTitle("Evidence Manager")
        self.resize(1400, 900)
        apply_theme(self)

        # ── central widget ────────────────────────────────────────────────
        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Horizontal: sidebar + content
        h_splitter = QSplitter(Qt.Orientation.Horizontal)

        self._sidebar = Sidebar(self._set_manager, self._signals)
        h_splitter.addWidget(self._sidebar)

        # Right side: stacked tabs + tab bar
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        from PySide6.QtWidgets import QStackedWidget, QTabBar  # noqa: PLC0415
        self._tab_bar = QTabBar()
        self._stack = QStackedWidget()

        self._setup_tabs()
        self._tab_bar.currentChanged.connect(self._stack.setCurrentIndex)

        right_layout.addWidget(self._tab_bar)
        right_layout.addWidget(self._stack)

        # Vertical: content + log pane
        v_splitter = QSplitter(Qt.Orientation.Vertical)
        v_splitter.addWidget(right_widget)

        self._log_pane = QPlainTextEdit()
        self._log_pane.setReadOnly(True)
        self._log_pane.setMaximumBlockCount(200)
        v_splitter.addWidget(self._log_pane)
        line_h = self._log_pane.fontMetrics().lineSpacing()
        v_splitter.setSizes([900 - line_h * 4, line_h * 4])
        v_splitter.setCollapsible(1, False)

        h_splitter.addWidget(v_splitter)
        h_splitter.setSizes([220, 1180])
        h_splitter.setCollapsible(0, False)

        main_layout.addWidget(h_splitter)
        self.setCentralWidget(central)

        # ── logging ───────────────────────────────────────────────────────
        self._log_handler = _QtLogHandler(self._log_pane)
        self._log_handler.setLevel(logging.DEBUG)
        stdout_handler = logging.StreamHandler()
        stdout_handler.setLevel(logging.DEBUG)
        stdout_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        root.addHandler(self._log_handler)
        root.addHandler(stdout_handler)

        self._setup_shortcuts()
        self._sidebar.select_first()

    def _setup_tabs(self) -> None:
        from evidmgr.gui.tabs.docs_tab import DocsTab  # noqa: PLC0415
        from evidmgr.gui.tabs.search_tab import SearchTab  # noqa: PLC0415
        from evidmgr.gui.tabs.prompt_tab import PromptTab  # noqa: PLC0415

        self._docs_tab = DocsTab(self._ingester, self._vec_service, self._signals, self._tag_service)
        self._search_tab = SearchTab(self._vec_service, self._tag_service, self._signals)
        self._prompt_tab = PromptTab(self._tag_service, self._signals)

        for label, widget in [
            ("Docs", self._docs_tab),
            ("Search", self._search_tab),
            ("Prompts", self._prompt_tab),
        ]:
            self._tab_bar.addTab(label)
            self._stack.addWidget(widget)

    def _setup_shortcuts(self) -> None:
        self._tab_filter = _TabCycleFilter(self._stack, self._tab_bar)
        QApplication.instance().installEventFilter(self._tab_filter)
        QShortcut(QKeySequence("Ctrl+W"), self, self.close)


def main() -> None:
    headless = (
        os.environ.get("QT_QPA_PLATFORM") == "offscreen"
        or os.environ.get("HEADLESS") == "1"
    )
    app = QApplication(sys.argv)
    window = EvidMgrWindow()
    window.show()
    if not headless:
        sys.exit(app.exec())
