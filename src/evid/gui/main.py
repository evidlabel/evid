"""Main GUI application."""

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

from evid import DEFAULT_DIR

from .tabs.add_evidence import AddEvidenceTab
from .tabs.browse_evidence import BrowseEvidenceTab


class EvidenceManagerApp(QMainWindow):
    """Main application window for evid GUI."""

    def __init__(self, directory: Path):
        super().__init__()
        self.directory = directory
        self.setWindowTitle("evid")
        self.resize(1400, 900)

        # Detect system theme and apply accordingly
        self.apply_theme()

        # Setup tabs
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.add_tab = AddEvidenceTab(self.directory)
        self.browse_tab = BrowseEvidenceTab(self.directory)

        self.tabs.addTab(self.add_tab, "Add")
        self.tabs.addTab(self.browse_tab, "Browse")
        self.tabs.setCurrentIndex(1)  # Set Browse tab as active initially

        # Setup keyboard shortcuts
        self.setup_shortcuts()

    def is_dark_mode(self):
        """Detect if system prefers dark mode."""
        try:
            from PySide6.QtGui import QGuiApplication

            if hasattr(QGuiApplication.styleHints(), "colorScheme"):
                return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        except AttributeError:
            pass
        # Fallback: assume light mode
        return False

    def apply_theme(self):
        """Apply light or dark theme based on system preference."""
        if self.is_dark_mode():
            self.set_dark_theme()
        else:
            self.set_light_theme()

    def set_dark_theme(self):
        """Apply a consistent dark theme."""
        palette = QPalette()
        # Background colors
        palette.setColor(QPalette.ColorRole.Window, QColor("#2d2d2d"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#2d2d2d"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#333333"))
        # Text colors
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#dcdcdc"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#dcdcdc"))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#dcdcdc"))
        # Button and highlight colors
        palette.setColor(QPalette.ColorRole.Button, QColor("#4a4a4a"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#dcdcdc"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#0078d4"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#dcdcdc"))
        # Disabled elements
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#888888"))
        palette.setColor(QPalette.ColorRole.Light, QColor("#555555"))
        palette.setColor(QPalette.ColorRole.Mid, QColor("#444444"))
        palette.setColor(QPalette.ColorRole.Dark, QColor("#333333"))
        # Tooltip background
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
        # Use default light colors
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
        """Setup keyboard shortcuts for tab navigation, app closing, labeling, and BibTeX generation."""
        # Ctrl+PageUp / Ctrl+PageDown to cycle between tabs
        prev_tab = QShortcut(QKeySequence("Ctrl+PageUp"), self)
        prev_tab.activated.connect(
            lambda: self.tabs.setCurrentIndex(
                (self.tabs.currentIndex() - 1) % self.tabs.count()
            )
        )
        prev_tab.setContext(Qt.ShortcutContext.ApplicationShortcut)

        next_tab = QShortcut(QKeySequence("Ctrl+PageDown"), self)
        next_tab.activated.connect(
            lambda: self.tabs.setCurrentIndex(
                (self.tabs.currentIndex() + 1) % self.tabs.count()
            )
        )
        next_tab.setContext(Qt.ShortcutContext.ApplicationShortcut)

        # Ctrl+W to close the application
        QShortcut(QKeySequence("Ctrl+W"), self, self.close)

        # Ctrl+L to trigger labeling in Browse tab
        QShortcut(
            QKeySequence("Ctrl+L"),
            self,
            lambda: (
                self.browse_tab.create_labels()
                if self.tabs.currentWidget() == self.browse_tab
                else None
            ),
        )

        # Ctrl+B to trigger BibTeX generation in Browse tab
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
    # Check for headless mode
    headless = (
        os.environ.get("QT_QPA_PLATFORM") == "offscreen"
        or os.environ.get("HEADLESS") == "1"
    )
    app = QApplication(sys.argv)
    window = EvidenceManagerApp(Path(directory))
    window.show()
    if headless:
        # In headless mode, don't start the event loop
        return
    sys.exit(app.exec())
