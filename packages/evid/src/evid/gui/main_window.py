"""EvidMgrWindow — main application window."""

from __future__ import annotations

import logging
import os
import sys

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from evid.config import EvidConfig
from evid.gui.sidebar import Sidebar
from evid.gui.signals import AppSignals
from evid.gui.theme import apply_theme
from evid.services.doc_ingester import DocIngester
from evid.services.set_manager import SetManager
from evid.services.tag_service import TagService
from evid.services.vec_service import VecService

logger = logging.getLogger(__name__)


class _QtLogHandler(QObject, logging.Handler):
    """Thread-safe logging handler that appends to a QPlainTextEdit.

    Uses a Qt signal so that log records emitted from background threads are
    delivered to the widget on the GUI thread via AutoConnection.
    """

    _message = Signal(str)

    def __init__(self, widget: QPlainTextEdit) -> None:
        QObject.__init__(self)
        logging.Handler.__init__(self)
        self._widget = widget
        self.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        self._message.connect(self._append)

    def _append(self, msg: str) -> None:
        try:
            self._widget.appendPlainText(msg)
            self._widget.verticalScrollBar().setValue(
                self._widget.verticalScrollBar().maximum()
            )
        except RuntimeError:
            pass  # widget already deleted (e.g. test teardown)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._message.emit(self.format(record))
        except Exception:
            self.handleError(record)


class _TabCycleFilter(QObject):
    def __init__(self, stack_widget, tab_bar) -> None:
        super().__init__()
        self._stack = stack_widget
        self._tab_bar = tab_bar

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
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


class EvidWindow(QMainWindow):
    def __init__(self, config: EvidConfig | None = None) -> None:
        super().__init__()
        self._config = config or EvidConfig.load()
        data_dir = self._config.data_dir
        data_dir.mkdir(parents=True, exist_ok=True)

        # ── services ──────────────────────────────────────────────────────
        self._set_manager = SetManager(data_dir)
        self._vec_service = VecService()
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

        from PySide6.QtWidgets import QStackedWidget, QTabBar

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
        stdout_handler.setFormatter(
            logging.Formatter("%(levelname)s %(name)s: %(message)s")
        )
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        root.addHandler(self._log_handler)
        root.addHandler(stdout_handler)

        self._setup_shortcuts()
        self._sidebar.select_first()

    def _setup_tabs(self) -> None:
        from evid.gui.tabs.docs_tab import DocsTab
        from evid.gui.tabs.search_tab import SearchTab

        self._docs_tab = DocsTab(
            self._ingester, self._vec_service, self._signals, self._tag_service
        )
        self._search_tab = SearchTab(
            self._vec_service, self._tag_service, self._signals
        )

        for label, widget in [
            ("Docs", self._docs_tab),
            ("Search", self._search_tab),
        ]:
            self._tab_bar.addTab(label)
            self._stack.addWidget(widget)

        self._signals.copy_doc_to_set.connect(self._on_copy_doc_to_set)
        self._signals.doc_navigate.connect(self._on_doc_navigate)
        self._signals.doc_ingested.connect(self._on_doc_ingested)
        self._signals.labels_updated.connect(self._on_labels_updated)
        self._signals.ingestion_error.connect(self._on_ingestion_error)

    def _on_copy_doc_to_set(self, src_slug: str, doc_uuid: str, dest_slug: str) -> None:
        try:
            src_set = self._set_manager.load_set(src_slug)
            dest_set = self._set_manager.load_set(dest_slug)
            src_doc_dir = src_set.path / "docs" / doc_uuid
            if not src_doc_dir.exists():
                logger.warning(
                    "Copy requested but src doc dir missing: %s", src_doc_dir
                )
                return
            self._docs_tab.start_copy_doc(src_doc_dir, dest_set)
        except Exception:
            logger.exception("Failed to start copy of %s → %s", doc_uuid, dest_slug)

    def _on_doc_navigate(self, uuid: str) -> None:
        self._tab_bar.setCurrentIndex(0)  # Docs tab
        self._docs_tab.navigate_to_doc(uuid)

    def _on_doc_ingested(self, set_slug: str, doc_uuid: str) -> None:
        if self._sidebar.active_set() and self._sidebar.active_set().slug == set_slug:
            self._docs_tab.reload_current_set()

    def _on_labels_updated(self, set_slug: str, doc_uuid: str) -> None:
        if self._sidebar.active_set() and self._sidebar.active_set().slug == set_slug:
            self._docs_tab.reload_current_set()

    def _on_ingestion_error(self, msg: str) -> None:
        logger.error("Ingestion error: %s", msg)
        self.statusBar().showMessage(f"Ingest failed: {msg[:120]}", 8000)

    def closeEvent(self, event) -> None:
        try:
            self._docs_tab.shutdown()
        except Exception:
            logger.exception("Error shutting down docs tab")
        super().closeEvent(event)

    def _setup_shortcuts(self) -> None:
        self._tab_filter = _TabCycleFilter(self._stack, self._tab_bar)
        QApplication.instance().installEventFilter(self._tab_filter)
        QShortcut(QKeySequence("Ctrl+W"), self, self.close)


def main(db_dir: Path | None = None) -> None:
    from pathlib import Path as _Path

    headless = (
        os.environ.get("QT_QPA_PLATFORM") == "offscreen"
        or os.environ.get("HEADLESS") == "1"
    )
    config = None
    if db_dir is not None:
        config = EvidConfig.load()
        config.data_dir = _Path(db_dir)
    app = QApplication(sys.argv)
    window = EvidWindow(config=config)
    window.show()
    if not headless:
        sys.exit(app.exec())


# Backward-compatible alias
EvidMgrWindow = EvidWindow
