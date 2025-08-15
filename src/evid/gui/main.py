import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QTabWidget
from PyQt6.QtGui import QPalette, QColor, QKeySequence
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QShortcut
from pathlib import Path
from .tabs.add_evidence import AddEvidenceTab
from .tabs.browse_evidence import BrowseEvidenceTab
from evid import DEFAULT_DIR


class EvidenceManagerApp(QMainWindow):
    def __init__(self, directory: Path):
        super().__init__()
        self.directory = directory
        self.setWindowTitle("evid")
        self.resize(800, 600)

        # Enforce dark theme across all platforms
        self.set_dark_theme()

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

    def set_dark_theme(self):
        """Apply a consistent dark theme to the application."""
        palette = QPalette()
        # Background colors
        palette.setColor(QPalette.ColorRole.Window, QColor("#2e2e2e"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#3e3e3e"))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#353535"))
        # Text colors
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#ffffff"))
        # Button and highlight colors
        palette.setColor(QPalette.ColorRole.Button, QColor("#4a4a4a"))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#0078d4"))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        # Disabled elements
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#888888"))
        palette.setColor(QPalette.ColorRole.Light, QColor("#555555"))
        palette.setColor(QPalette.ColorRole.Mid, QColor("#444444"))
        palette.setColor(QPalette.ColorRole.Dark, QColor("#333333"))
        # Tooltip background
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2e2e2e"))

        self.setPalette(palette)
        # Ensure stylesheet enforces dark theme for elements not covered by palette
        self.setStyleSheet("""
            QToolTip { background-color: #2e2e2e; color: #ffffff; border: 1px solid #555555; }
            QComboBox, QLineEdit, QTextEdit, QTableWidget { 
                background-color: #3e3e3e; 
                color: #ffffff; 
                border: 1px solid #555555; 
            }
            QPushButton { 
                background-color: #4a4a4a; 
                color: #ffffff; 
                border: 1px solid #555555; 
            }
            QPushButton:hover { 
                background-color: #0078d4; 
            }
            QTabBar::tab { 
                background: #3e3e3e; 
                color: #ffffff; 
                padding: 5px; 
            }
            QTabBar::tab:selected { 
                background: #0078d4; 
            }
        """)

    def setup_shortcuts(self):
        """Setup keyboard shortcuts for tab navigation, app closing, labeling, and BibTeX generation."""
        # Ctrl+PageUp to switch to Add tab
        add_tab_shortcut = QShortcut(
            QKeySequence("Ctrl+PageUp"),
            self,
            lambda: self.tabs.setCurrentIndex(0),
        )
        add_tab_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)

        # Ctrl+PageDown to switch to Browse tab
        browse_tab_shortcut = QShortcut(
            QKeySequence("Ctrl+PageDown"),
            self,
            lambda: self.tabs.setCurrentIndex(1),
        )
        browse_tab_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)

        # Ctrl+W to close the application
        QShortcut(QKeySequence("Ctrl+W"), self, self.close)

        # Ctrl+L to trigger labeling in Browse tab
        QShortcut(
            QKeySequence("Ctrl+L"),
            self,
            lambda: self.browse_tab.create_labels()
            if self.tabs.currentWidget() == self.browse_tab
            else None,
        )

        # Ctrl+B to trigger BibTeX generation in Browse tab
        QShortcut(
            QKeySequence("Ctrl+B"),
            self,
            lambda: self.browse_tab.generate_bibtex()
            if self.tabs.currentWidget() == self.browse_tab
            else None,
        )


def main(directory=DEFAULT_DIR):
    app = QApplication(sys.argv)
    window = EvidenceManagerApp(Path(directory))
    window.show()
    sys.exit(app.exec())



