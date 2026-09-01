"""jura.sh mark for the window, tray, and corner hint."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PKG = "evid.gui.assets"


def logo_svg_path() -> Path:
    return Path(str(files(_PKG).joinpath("jura.svg")))


def logo_png_path() -> Path:
    return Path(str(files(_PKG).joinpath("jura.png")))


def jura_pixmap(size: int) -> QPixmap:
    svg = logo_svg_path()
    if svg.is_file():
        renderer = QSvgRenderer(str(svg))
        if renderer.isValid():
            pm = QPixmap(size, size)
            pm.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pm)
            renderer.render(painter)
            painter.end()
            return pm
    png = logo_png_path()
    if png.is_file():
        return QPixmap(str(png)).scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return QPixmap()


def jura_icon() -> QIcon:
    icon = QIcon()
    png = logo_png_path()
    if png.is_file():
        icon.addFile(str(png))
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = jura_pixmap(size)
        if not pm.isNull():
            icon.addPixmap(pm)
    return icon
