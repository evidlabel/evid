"""Main GUI application."""

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from evid import DEFAULT_DIR

from .tabs.add_evidence import AddEvidenceTab
from .tabs.browse_evidence import BrowseEvidenceTab


class _QtLogHandler(logging.Handler):
    """Append log records to a QPlainTextEdit."""

    def __init__(self, widget: QPlainTextEdit):
        super().__init__()
        self._widget = widget
        self.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    def emit(self, record):
        msg = self.format(record)
        self._widget.appendPlainText(msg)
        self._widget.verticalScrollBar().setValue(
            self._widget.verticalScrollBar().maximum()
        )


class _TabCycleFilter(QObject):
    """Intercept Ctrl+PageUp/Down globally to cycle tabs."""

    def __init__(self, tabs):
        super().__init__()
        self._tabs = tabs

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Type.KeyPress and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_PageUp:
                self._tabs.setCurrentIndex((self._tabs.currentIndex() - 1) % self._tabs.count())
                return True
            if event.key() == Qt.Key.Key_PageDown:
                self._tabs.setCurrentIndex((self._tabs.currentIndex() + 1) % self._tabs.count())
                return True
        return False


class EvidenceManagerApp(QMainWindow):
    """Main application window for evid GUI."""

    def __init__(self, directory: Path):
        super().__init__()
        self.directory = directory
        self.setWindowTitle("evid")
        self.resize(1400, 900)

        self.apply_theme()

        # Central widget: tabs + log pane
        central = QWidget()
        vbox = QVBoxLayout(central)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        self.tabs = QTabWidget()
        vbox.addWidget(self.tabs, stretch=1)

        self.log_pane = QPlainTextEdit()
        self.log_pane.setReadOnly(True)
        self.log_pane.setMaximumBlockCount(200)
        line_h = self.log_pane.fontMetrics().lineSpacing()
        self.log_pane.setFixedHeight(line_h * 3 + 10)
        vbox.addWidget(self.log_pane)

        self.setCentralWidget(central)

        # Attach log handler to root logger
        self._log_handler = _QtLogHandler(self.log_pane)
        self._log_handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(self._log_handler)

        self.add_tab = AddEvidenceTab(self.directory)
        self.browse_tab = BrowseEvidenceTab(self.directory)

        self.tabs.addTab(self.add_tab, "Add")
        self.tabs.addTab(self.browse_tab, "Browse")
        self.tabs.setCurrentIndex(1)

        self.setup_shortcuts()

    def is_dark_mode(self):
        """Detect if system prefers dark mode."""
        try:
            from PySide6.QtGui import QGuiApplication

            if hasattr(QGuiApplication.styleHints(), "colorScheme"):
                return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        except AttributeError:
            pass
        return False

    def apply_theme(self):
        if self.is_dark_mode():
            self.set_dark_theme()
        else:
            self.set_light_theme()

    def set_dark_theme(self):
        """Apply a consistent dark theme."""
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#2d2d2d"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#2d2d2d"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#333333"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#dcdcdc"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#dcdcdc"))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#dcdcdc"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#4a4a4a"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#dcdcdc"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#0078d4"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#dcdcdc"))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#888888"))
        palette.setColor(QPalette.ColorRole.Light, QColor("#555555"))
        palette.setColor(QPalette.ColorRole.Mid, QColor("#444444"))
        palette.setColor(QPalette.ColorRole.Dark, QColor("#333333"))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2d2d2d"))
        self.setPalette(palette)
        self.setStyleSheet("""
            QToolTip {
                background-color: #2d2d2d;
                color: #dcdcdc;
                border: 1px solid #555555;
            }
            QComboBox, QLineEdit, QTextEdit, QTableWidget {
                background-color: #2d2d2d;
                color: #dcdcdc;
                border: 1px solid #555555;
            }
            QPlainTextEdit {
                background: #1a1a1a;
                color: #b0c4b0;
                font-family: monospace;
                font-size: 11px;
                border: none;
            }
            QPushButton {
                background-color: #4a4a4a;
                color: #dcdcdc;
                border: 1px solid #555555;
            }
            QPushButton:hover {
                background-color: #0078d4;
            }
            QTabBar::tab {
                background: #2d2d2d;
                color: #aaaaaa;
                padding: 5px;
            }
            QTabBar::tab:selected {
                background: #0078d4;
                color: #dcdcdc;
            }
            QHeaderView::section {
                background-color: #333333;
                color: #aaaaaa;
                border: 1px solid #444444;
            }
            QLabel {
                color: #dcdcdc;
            }
        """)

    def set_light_theme(self):
        """Apply a consistent light theme."""
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#f0f0f0"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#f7f7f7"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#000000"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#000000"))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#000000"))
        palette.setColor(QPalette.ColorRole.Button, QColor("#e0e0e0"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#000000"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#0078d4"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#777777"))
        palette.setColor(QPalette.ColorRole.Light, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Mid, QColor("#c0c0c0"))
        palette.setColor(QPalette.ColorRole.Dark, QColor("#a0a0a0"))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#f0f0f0"))
        self.setPalette(palette)
        self.setStyleSheet("""
            QToolTip {
                background-color: #f0f0f0;
                color: #000000;
                border: 1px solid #a0a0a0;
            }
            QComboBox, QLineEdit, QTextEdit, QTableWidget {
                background-color: #ffffff;
                color: #000000;
                border: 1px solid #a0a0a0;
            }
            QPushButton {
                background-color: #e0e0e0;
                color: #000000;
                border: 1px solid #a0a0a0;
            }
            QPushButton:hover {
                background-color: #0078d4;
            }
            QTabBar::tab {
                background: #f0f0f0;
                color: #000000;
                padding: 5px;
            }
            QTabBar::tab:selected {
                background: #0078d4;
            }
        """)

    def setup_shortcuts(self):
        """Setup keyboard shortcuts."""
        self._tab_filter = _TabCycleFilter(self.tabs)
        QApplication.instance().installEventFilter(self._tab_filter)

        QShortcut(QKeySequence("Ctrl+W"), self, self.close)

        QShortcut(
            QKeySequence("Ctrl+L"),
            self,
            lambda: (
                self.browse_tab.create_labels()
                if self.tabs.currentWidget() == self.browse_tab
                else None
            ),
        )

        QShortcut(
            QKeySequence("Ctrl+B"),
            self,
            lambda: (
                self.browse_tab.generate_bibtex()
                if self.tabs.currentWidget() == self.browse_tab
                else None
            ),
        )


def main(directory=DEFAULT_DIR):
    """Launch the GUI application."""
    headless = (
        os.environ.get("QT_QPA_PLATFORM") == "offscreen"
        or os.environ.get("HEADLESS") == "1"
    )
    app = QApplication(sys.argv)
    window = EvidenceManagerApp(Path(directory))
    window.show()
    if headless:
        return
    sys.exit(app.exec())
