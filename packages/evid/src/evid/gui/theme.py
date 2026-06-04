"""Theme helpers — adapted from evid.gui.main."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QWidget


def is_dark_mode() -> bool:
    try:
        from PySide6.QtGui import QGuiApplication

        if hasattr(QGuiApplication.styleHints(), "colorScheme"):
            return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:
        pass
    return False


def apply_theme(widget: QWidget) -> None:
    if is_dark_mode():
        set_dark_theme(widget)
    else:
        set_light_theme(widget)


def set_dark_theme(widget: QWidget) -> None:
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
    widget.setPalette(palette)
    widget.setStyleSheet("""
        QToolTip { background-color: #2d2d2d; color: #dcdcdc; border: 1px solid #555; }
        QComboBox, QLineEdit, QTextEdit, QTableWidget {
            background-color: #2d2d2d; color: #dcdcdc; border: 1px solid #555; }
        QLineEdit { height: 28px; padding: 0 10px; font-size: 13px; }
        QPlainTextEdit {
            background: #1a1a1a; color: #b0c4b0; font-family: monospace;
            font-size: 11px; border: none; }
        QPushButton {
            background-color: #4a4a4a; color: #dcdcdc; border: 1px solid #555; }
        QPushButton:hover { background-color: #0078d4; }
        QTabBar::tab { background: #2d2d2d; color: #aaa; padding: 5px; }
        QTabBar::tab:selected { background: #0078d4; color: #dcdcdc; }
        QHeaderView::section {
            background-color: #333; color: #aaa; border: 1px solid #444; }
        QLabel { color: #dcdcdc; }
        QListWidget { background-color: #2d2d2d; color: #dcdcdc; border: 1px solid #555; }
        QSplitter::handle { background-color: #444; }
    """)


def set_light_theme(widget: QWidget) -> None:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#f0f0f0"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#f7f7f7"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#000000"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#000000"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#e0e0e0"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#000000"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#0078d4"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    widget.setPalette(palette)
    widget.setStyleSheet("""
        QLineEdit { height: 28px; padding: 0 10px; font-size: 13px; }
        QPushButton:hover { background-color: #0078d4; color: #fff; }
        QTabBar::tab:selected { background: #0078d4; color: #fff; }
    """)
