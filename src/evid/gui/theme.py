"""Theme helpers — adapted from evid.gui.main."""

from PySide6.QtCore import QEvent, QObject, Qt
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


class _ThemedArrowFilter(QObject):
    """Restores left_ptr if a style sets pointing_hand on hover."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() in (
            QEvent.Type.Enter,
            QEvent.Type.HoverEnter,
            QEvent.Type.Polish,
        ):
            if (
                isinstance(obj, QWidget)
                and obj.cursor().shape() != Qt.CursorShape.ArrowCursor
            ):
                obj.setCursor(Qt.CursorShape.ArrowCursor)
        return False


def use_themed_arrow(widget: QWidget) -> None:
    """Use left_ptr instead of pointing_hand.

    Xcursor looks up ``pointing_hand``; Yaru/Adwaita often only ship ``hand2``
    / ``pointer`` at the scaled size, so Qt falls back to a 24px bitmap.
    ``ArrowCursor`` is ``left_ptr``, which the theme has. Styles that swap
    to pointing_hand on hover are pinned back on enter.
    """
    widget.setCursor(Qt.CursorShape.ArrowCursor)
    filt = widget.findChild(_ThemedArrowFilter, "themed_arrow")
    if filt is None:
        filt = _ThemedArrowFilter(widget)
        filt.setObjectName("themed_arrow")
        widget.installEventFilter(filt)


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


def tag_pill_styles() -> dict[str, str]:
    """Stylesheet fragments for TagPill states (default / active / carried)."""
    if is_dark_mode():
        return {
            "default": (
                "QPushButton{border-radius:10px;padding:2px 8px;"
                "border:1px solid #666;background:#3a3a3a;color:#dcdcdc;font-size:11px;}"
                "QPushButton:hover{background:#4a4a4a;}"
            ),
            "active": (
                "QPushButton{border-radius:10px;padding:2px 8px;"
                "border:1px solid #005a9e;background:#0078d4;color:#fff;font-size:11px;}"
                "QPushButton:hover{background:#006cbe;}"
            ),
            "carried": (
                "QPushButton{border-radius:10px;padding:2px 8px;"
                "border:1px solid #2e7d32;background:#1e3a22;color:#a5d6a7;font-size:11px;}"
                "QPushButton:hover{background:#2a4f2e;}"
            ),
        }
    return {
        "default": (
            "QPushButton{border-radius:10px;padding:2px 8px;"
            "border:1px solid #999;background:#e8e8e8;color:#222;font-size:11px;}"
            "QPushButton:hover{background:#d0d0d0;}"
        ),
        "active": (
            "QPushButton{border-radius:10px;padding:2px 8px;"
            "border:1px solid #005a9e;background:#0078d4;color:#fff;font-size:11px;}"
            "QPushButton:hover{background:#006cbe;}"
        ),
        "carried": (
            "QPushButton{border-radius:10px;padding:2px 8px;"
            "border:1px solid #2e7d32;background:#c8e6c9;color:#1b5e20;font-size:11px;}"
            "QPushButton:hover{background:#b5ddb7;}"
        ),
    }


def muted_label_stylesheet() -> str:
    return (
        "color: #888; font-size: 11px;"
        if not is_dark_mode()
        else ("color: #aaa; font-size: 11px;")
    )


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
