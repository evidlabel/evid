"""Bottom-right corner hint that raises the hidden evid window."""

from __future__ import annotations

import ctypes

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

_HINT_SIZE = 28


class CornerHint(QWidget):
    """Tiny always-on-top hotspot. Dwell or click emits *activated*."""

    activated = Signal()

    def __init__(self, dwell_ms: int = 200, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dwell_ms = dwell_ms
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.activated.emit)
        self.setObjectName("evid_corner_hint")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(_HINT_SIZE, _HINT_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("evid")
        self._logo = QPixmap()

    def park(self) -> None:
        """Sit in the bottom-right corner of the current screen."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.geometry()
        self.move(
            geo.x() + geo.width() - _HINT_SIZE, geo.y() + geo.height() - _HINT_SIZE
        )

    def showEvent(self, event: QEvent) -> None:
        self.park()
        super().showEvent(event)

    def paintEvent(self, event: QEvent) -> None:
        if self._logo.isNull():
            from evid.gui.logo import jura_pixmap

            self._logo = jura_pixmap(_HINT_SIZE)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not self._logo.isNull():
            painter.drawPixmap(self.rect(), self._logo)
        painter.end()

    def enterEvent(self, event: QEvent) -> None:
        self._timer.start(self._dwell_ms)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._timer.stop()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._timer.stop()
            self.activated.emit()
        super().mousePressEvent(event)


class CornerWatcher(QObject):
    """Poll the pointer and fire when it dwells in the bottom-right corner.

    Native Wayland Qt does not report a global cursor. On a Wayland session
    with XWayland we use XQueryPointer instead of switching the whole GUI to
    xcb (which makes fonts grainy under GNOME fractional scaling).
    """

    activated = Signal()

    def __init__(
        self,
        margin: int = 16,
        dwell_ms: int = 200,
        interval_ms: int = 50,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._margin = margin
        self._in_corner = False
        self._fired = False
        self._dwell = QTimer(self)
        self._dwell.setSingleShot(True)
        self._dwell.timeout.connect(self._fire)
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._check)
        self._poll.start(interval_ms)
        self._dwell_ms = dwell_ms

    def stop(self) -> None:
        self._poll.stop()
        self._dwell.stop()

    def _check(self) -> None:
        if _cursor_in_bottom_right(self._margin):
            if not self._in_corner:
                self._in_corner = True
                self._dwell.start(self._dwell_ms)
            return
        self._in_corner = False
        self._fired = False
        self._dwell.stop()

    def _fire(self) -> None:
        if self._fired:
            return
        self._fired = True
        self.activated.emit()


def _qt_platform() -> str:
    app = QGuiApplication.instance()
    if app is None:
        return ""
    return app.platformName()


class _X11Display:
    def __init__(self) -> None:
        self._xlib = None
        self._dpy = None
        self._root = 0
        self._dead = False

    def pos(self) -> tuple[int, int] | None:
        if self._dead:
            return None
        try:
            if self._dpy is None:
                xlib = ctypes.CDLL("libX11.so.6")
                xlib.XOpenDisplay.restype = ctypes.c_void_p
                xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
                xlib.XDefaultRootWindow.restype = ctypes.c_ulong
                xlib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
                xlib.XQueryPointer.restype = ctypes.c_int
                xlib.XQueryPointer.argtypes = [
                    ctypes.c_void_p,
                    ctypes.c_ulong,
                    ctypes.POINTER(ctypes.c_ulong),
                    ctypes.POINTER(ctypes.c_ulong),
                    ctypes.POINTER(ctypes.c_int),
                    ctypes.POINTER(ctypes.c_int),
                    ctypes.POINTER(ctypes.c_int),
                    ctypes.POINTER(ctypes.c_int),
                    ctypes.POINTER(ctypes.c_uint),
                ]
                dpy = xlib.XOpenDisplay(None)
                if not dpy:
                    self._dead = True
                    return None
                self._xlib = xlib
                self._dpy = dpy
                self._root = xlib.XDefaultRootWindow(dpy)
            root_r = ctypes.c_ulong()
            child = ctypes.c_ulong()
            rx = ctypes.c_int()
            ry = ctypes.c_int()
            wx = ctypes.c_int()
            wy = ctypes.c_int()
            mask = ctypes.c_uint()
            ok = self._xlib.XQueryPointer(
                self._dpy,
                self._root,
                root_r,
                child,
                rx,
                ry,
                wx,
                wy,
                mask,
            )
            if not ok:
                return None
            return rx.value, ry.value
        except OSError:
            self._dead = True
            return None


_X11 = _X11Display()


def x11_pointer() -> tuple[int, int] | None:
    """Global pointer via XWayland, or None if X11 is unavailable."""
    return _X11.pos()


def _pointer_pos() -> QPoint:
    if _qt_platform() == "wayland":
        xy = x11_pointer()
        if xy is not None:
            return QPoint(xy[0], xy[1])
    return QCursor.pos()


def _cursor_in_bottom_right(margin: int) -> bool:
    pos = _pointer_pos()
    screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
    if screen is None:
        return False
    geo = screen.geometry()
    return (
        pos.x() >= geo.x() + geo.width() - margin
        and pos.y() >= geo.y() + geo.height() - margin
    )
