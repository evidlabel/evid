"""EvidMgrWindow — main application window."""

from __future__ import annotations

import logging
import os
import sys

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from evid import extras
from evid.config import EvidConfig
from evid.gui.sidebar import Sidebar
from evid.gui.signals import AppSignals
from evid.gui.theme import apply_theme
from evid.services.doc_ingester import DocIngester
from evid.services.set_manager import SetManager
from evid.services.tag_service import TagService
from evid.services.vec_service import VecService

logger = logging.getLogger(__name__)

_HELP_HTML = """
<p>Humans and agents share one legal document set.
Cited wording is always verbatim.</p>
<p><b>Tabs</b><br>
Docs — ingest, label, tags<br>
Search — vec, meta, text</p>
<p><b>Shortcuts</b></p>
<table>
<tr><td>Ctrl+PageUp / PageDown</td><td style="padding-left:16px">cycle tabs</td></tr>
<tr><td>Ctrl+W</td><td style="padding-left:16px">hide to the bottom-right corner</td></tr>
<tr><td>F1</td><td style="padding-left:16px">help</td></tr>
<tr><td>Alt+drag a row onto a set</td><td style="padding-left:16px">copy document</td></tr>
</table>
<p><b>Docs</b> — Ingest PDF · Add from URL · Index · Label (#lab) · Open dir</p>
<p>Close hides the window; the process stays running. Hover or click the
bottom-right corner hint (or the tray icon) to bring it back. Quit from the
tray or the hint's right-click menu.</p>
"""


class HelpDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Help")
        self.setModal(True)
        apply_theme(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(8)
        body = QLabel()
        body.setObjectName("help_body")
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setText(_HELP_HTML)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(body)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self.setMinimumWidth(440)


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


class _ClickThroughTooltips(QObject):
    """Let mouse clicks pass through hover tooltips.

    QTipLabel is a top-level popup. The first click (including right-click)
    otherwise dismisses it instead of reaching the widget underneath, so
    table context menus fail after a row hover.
    """

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj.inherits("QTipLabel"):
            obj.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        return False


class EvidWindow(QMainWindow):
    def __init__(
        self,
        config: EvidConfig | None = None,
        hide_on_close: bool = False,
    ) -> None:
        super().__init__()
        self._config = config or EvidConfig.load()
        self._hide_on_close = hide_on_close
        self._quit_requested = False
        data_dir = self._config.data_dir
        data_dir.mkdir(parents=True, exist_ok=True)

        # ── services ──────────────────────────────────────────────────────
        self._set_manager = SetManager(data_dir)
        self._vec_service = VecService() if extras.has_vec() else None
        self._tag_service = TagService(data_dir)
        self._ingester = DocIngester(vec_service=self._vec_service)
        self._signals = AppSignals()

        self.setWindowTitle("Evidence Manager")
        self.setWindowIcon(_evid_icon())
        apply_theme(self)
        _place_bottom_right_quarter(self)

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

        top_bar = QWidget()
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(0, 0, 4, 0)
        top_layout.setSpacing(4)
        top_layout.addWidget(self._tab_bar, 1)
        self._help_btn = QPushButton("Help")
        self._help_btn.setToolTip("Shortcuts and GUI overview (F1)")
        self._help_btn.clicked.connect(self._on_help)
        top_layout.addWidget(self._help_btn)
        right_layout.addWidget(top_bar)
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
        self._setup_background()

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

    def _on_help(self) -> None:
        HelpDialog(self).exec()

    def _setup_background(self) -> None:
        if not self._hide_on_close:
            return
        from evid.gui.corner_hint import CornerHint, CornerWatcher

        self._corner_hint = CornerHint()
        self._corner_hint.activated.connect(self.reveal)
        self._corner_hint.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        quit_action = QAction("Quit evid", self._corner_hint)
        quit_action.triggered.connect(self.request_quit)
        self._corner_hint.addAction(quit_action)
        self._corner_watcher = CornerWatcher(parent=self)
        self._corner_watcher.activated.connect(self.reveal)

    def _show_corner_hint(self) -> None:
        hint = getattr(self, "_corner_hint", None)
        if hint is None:
            return
        hint.park()
        hint.show()

    def _hide_corner_hint(self) -> None:
        hint = getattr(self, "_corner_hint", None)
        if hint is not None:
            hint.hide()

    def reveal(self) -> None:
        """Show in the bottom-right quarter and raise."""
        self._hide_corner_hint()
        if self.isMaximized():
            self.showNormal()
        self.show()
        _schedule_bottom_right_quarter(self)
        self.raise_()
        self.activateWindow()
        handle = self.windowHandle()
        if handle is not None:
            handle.requestActivate()

    def request_quit(self) -> None:
        """Really close the window (tray Quit)."""
        self._quit_requested = True
        instance = getattr(self, "_instance", None)
        if instance is not None:
            instance.release()
            self._instance = None
        self.close()
        app = QApplication.instance()
        if app is not None and self._hide_on_close:
            app.quit()

    def closeEvent(self, event) -> None:
        if self._hide_on_close and not self._quit_requested:
            event.ignore()
            self.hide()
            self._show_corner_hint()
            return
        self._hide_corner_hint()
        watcher = getattr(self, "_corner_watcher", None)
        if watcher is not None:
            watcher.stop()
        hint = getattr(self, "_corner_hint", None)
        if hint is not None:
            hint.close()
        try:
            self._docs_tab.shutdown()
        except Exception:
            logger.exception("Error shutting down docs tab")
        app = QApplication.instance()
        if app is not None:
            if hasattr(self, "_tab_filter"):
                app.removeEventFilter(self._tab_filter)
            if hasattr(self, "_tooltip_filter"):
                app.removeEventFilter(self._tooltip_filter)
        super().closeEvent(event)

    def _setup_shortcuts(self) -> None:
        self._tab_filter = _TabCycleFilter(self._stack, self._tab_bar)
        self._tooltip_filter = _ClickThroughTooltips(self)
        app = QApplication.instance()
        app.installEventFilter(self._tab_filter)
        app.installEventFilter(self._tooltip_filter)
        QShortcut(QKeySequence("Ctrl+W"), self, self.close)
        QShortcut(QKeySequence("F1"), self, self._on_help)


def _print_startup_banner(data_dir: Path) -> None:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    body = Text()
    body.append("Welcome to evid", style="bold cyan")
    body.append(" — PDF evidence management\n\n")
    body.append("Dataset directory: ", style="bold")
    body.append(str(data_dir), style="green")
    body.append("\n\nClose hides; bottom-right corner (or tray) raises. ")
    body.append("Keep this process running. Quit from the tray.")
    Console().print(Panel(body, border_style="cyan", expand=False))


def _evid_icon() -> QIcon:
    from evid.gui.logo import jura_icon

    return jura_icon()


def _install_tray(window: EvidWindow) -> None:
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return
    tray = QSystemTrayIcon(_evid_icon(), window)
    tray.setToolTip("evid")
    menu = QMenu()
    menu.addAction("Show", window.reveal)
    menu.addAction("Hide", window.close)
    menu.addAction("Quit", window.request_quit)
    tray.setContextMenu(menu)

    def _activated(reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if window.isVisible():
                window.close()
            else:
                window.reveal()

    tray.activated.connect(_activated)
    tray.show()
    window._tray = tray


def bootstrap_gui(
    app: QApplication,
    config: EvidConfig | None = None,
    *,
    background: bool,
    instance_name: str = "evid-gui",
) -> EvidWindow | None:
    """Create the GUI window, or None if another instance is already running."""
    instance = None
    if background:
        from evid.gui.single_instance import GuiInstance

        instance = GuiInstance.acquire(instance_name)
        if instance is None:
            return None
        app.setQuitOnLastWindowClosed(False)
    window = EvidWindow(config=config, hide_on_close=background)
    if instance is not None:
        instance.raise_requested.connect(window.reveal)
        window._instance = instance
        _install_tray(window)
    return window


def bottom_right_quarter(area: QRect, minimum: QSize | None = None) -> QRect:
    """Half the work area, parked on the bottom-right.

    If *minimum* is larger than a quarter, the rect grows but stays in the
    corner and is clamped to *area*.
    """
    width = area.width() // 2
    height = area.height() // 2
    if minimum is not None:
        width = max(width, minimum.width())
        height = max(height, minimum.height())
    width = min(width, area.width())
    height = min(height, area.height())
    return QRect(
        area.x() + area.width() - width,
        area.y() + area.height() - height,
        width,
        height,
    )


def _place_bottom_right_quarter(window: QWidget) -> None:
    screen = window.screen() or QGuiApplication.primaryScreen()
    if screen is None:
        return
    hint = window.minimumSizeHint()
    minimum = QSize(
        max(window.minimumWidth(), hint.width()),
        max(window.minimumHeight(), hint.height()),
    )
    window.setGeometry(bottom_right_quarter(screen.availableGeometry(), minimum))


def _schedule_bottom_right_quarter(window: QWidget) -> None:
    """Pin now and again after mutter's first configure (which resets to 0,0)."""
    _place_bottom_right_quarter(window)
    for ms in (0, 50, 200, 400):
        QTimer.singleShot(ms, window, lambda w=window: _place_bottom_right_quarter(w))


def prefer_x11_hot_corner() -> None:
    """Use XWayland so the compositor honors window position.

    GNOME on Wayland ignores xdg-toplevel move requests, so the window lands
    at the top-left. XWayland (xcb) accepts setGeometry. Do not override an
    explicit QT_QPA_PLATFORM (tests use offscreen).
    """
    if os.environ.get("QT_QPA_PLATFORM"):
        return
    if os.environ.get("WAYLAND_DISPLAY") and os.environ.get("DISPLAY"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"


def main(db_dir: Path | None = None) -> None:
    from pathlib import Path as _Path

    prefer_x11_hot_corner()
    headless = (
        os.environ.get("QT_QPA_PLATFORM") == "offscreen"
        or os.environ.get("HEADLESS") == "1"
    )
    config = None
    if db_dir is not None:
        config = EvidConfig.load()
        config.data_dir = _Path(db_dir)
    _print_startup_banner((config or EvidConfig.load()).data_dir)
    app = QApplication(sys.argv)
    app.setApplicationName("evid")
    app.setWindowIcon(_evid_icon())
    window = bootstrap_gui(app, config, background=not headless)
    if window is None:
        sys.exit(0)
    window.reveal()
    if not headless:
        sys.exit(app.exec())


# Backward-compatible alias
EvidMgrWindow = EvidWindow
