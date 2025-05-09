import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QTabWidget
from PyQt6.QtGui import QPalette, QColor
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

        # Set dark theme
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#2e2e2e"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#3e3e3e"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#ffffff"))
        self.setPalette(palette)

        # Setup tabs
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.add_tab = AddEvidenceTab(self.directory)
        self.browse_tab = BrowseEvidenceTab(self.directory)

        self.tabs.addTab(self.add_tab, "Add")
        self.tabs.addTab(self.browse_tab, "Browse")


def main(directory=DEFAULT_DIR):
    app = QApplication(sys.argv)
    window = EvidenceManagerApp(Path(directory))
    window.show()
    sys.exit(app.exec())
