"""Hide-on-close, corner hint, and single-instance raise for the GUI."""

import os

import pytest

pytest.importorskip("PySide6")

pytestmark = pytest.mark.skipif(
    os.environ.get("CI") != "true" and os.environ.get("HEADLESS") != "1",
    reason="GUI tests require headless/CI env (set HEADLESS=1)",
)


@pytest.fixture(scope="module")
def qapp():
    import sys

    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


def test_hide_on_close_keeps_window_alive(qapp, tmp_path, qtbot):
    from evid.config import EvidConfig
    from evid.gui.main_window import EvidWindow

    window = EvidWindow(config=EvidConfig(data_dir=tmp_path), hide_on_close=True)
    window.show()
    qapp.processEvents()
    assert window.isVisible()

    window.close()
    qapp.processEvents()

    assert not window.isVisible()
    window.reveal()
    qapp.processEvents()
    assert window.isVisible()
    assert not window.isMaximized()
    from PySide6.QtGui import QGuiApplication

    area = QGuiApplication.primaryScreen().availableGeometry()

    def _in_bottom_right() -> bool:
        geo = window.geometry()
        return geo.right() >= area.center().x() and geo.bottom() >= area.center().y()

    qtbot.waitUntil(_in_bottom_right, timeout=1000)

    window.request_quit()
    qapp.processEvents()


def test_bottom_right_quarter_is_half_size_in_the_corner():
    from PySide6.QtCore import QRect, QSize

    from evid.gui.main_window import bottom_right_quarter

    assert bottom_right_quarter(QRect(0, 32, 3072, 1696)) == QRect(1536, 880, 1536, 848)
    assert bottom_right_quarter(QRect(0, 0, 800, 800), QSize(853, 751)) == QRect(
        0, 49, 800, 751
    )


def test_corner_hint_dwell_emits_activated(qapp, qtbot):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QEnterEvent
    from PySide6.QtWidgets import QApplication

    from evid.gui.corner_hint import CornerHint

    hint = CornerHint(dwell_ms=40)
    qtbot.addWidget(hint)
    hint.show()
    qapp.processEvents()

    local = QPointF(hint.rect().center())
    global_pos = QPointF(hint.mapToGlobal(hint.rect().center()))
    with qtbot.waitSignal(hint.activated, timeout=400):
        QApplication.sendEvent(hint, QEnterEvent(local, local, global_pos))


def test_corner_hint_click_emits_activated(qapp, qtbot):
    from PySide6.QtCore import Qt

    from evid.gui.corner_hint import CornerHint

    hint = CornerHint(dwell_ms=10_000)
    qtbot.addWidget(hint)
    hint.show()
    qapp.processEvents()

    with qtbot.waitSignal(hint.activated, timeout=400):
        qtbot.mouseClick(hint, Qt.MouseButton.LeftButton)


def test_corner_hint_parks_bottom_right(qapp, qtbot):
    from PySide6.QtGui import QGuiApplication

    from evid.gui.corner_hint import CornerHint

    hint = CornerHint()
    qtbot.addWidget(hint)
    hint.park()
    hint.show()
    qapp.processEvents()

    screen = QGuiApplication.primaryScreen().geometry()
    geo = hint.frameGeometry()
    assert geo.right() == screen.right()
    assert geo.bottom() == screen.bottom()
    assert geo.width() == 28
    assert geo.height() == 28


def test_hide_on_close_shows_corner_hint(qapp, tmp_path):
    from evid.config import EvidConfig
    from evid.gui.corner_hint import CornerHint
    from evid.gui.main_window import EvidWindow

    window = EvidWindow(config=EvidConfig(data_dir=tmp_path), hide_on_close=True)
    window.show()
    qapp.processEvents()
    hints = [w for w in qapp.topLevelWidgets() if isinstance(w, CornerHint)]
    assert not any(h.isVisible() for h in hints)

    window.close()
    qapp.processEvents()
    hints = [w for w in qapp.topLevelWidgets() if isinstance(w, CornerHint)]
    assert any(h.isVisible() for h in hints)

    window.reveal()
    qapp.processEvents()
    hints = [w for w in qapp.topLevelWidgets() if isinstance(w, CornerHint)]
    assert not any(h.isVisible() for h in hints)

    window.request_quit()
    qapp.processEvents()
    hints = [w for w in qapp.topLevelWidgets() if isinstance(w, CornerHint)]
    assert not any(h.isVisible() for h in hints)


def test_second_instance_asks_primary_to_raise(qapp, qtbot):
    import uuid

    from evid.gui.single_instance import GuiInstance

    name = f"evid-gui-test-{uuid.uuid4().hex}"
    primary = GuiInstance.acquire(name)
    assert primary is not None
    try:
        with qtbot.waitSignal(primary.raise_requested, timeout=1000):
            second = GuiInstance.acquire(name)
            assert second is None
    finally:
        primary.release()


def test_bootstrap_second_instance_raises_existing(qapp, tmp_path, qtbot):
    import uuid

    from evid.config import EvidConfig
    from evid.gui.main_window import bootstrap_gui

    name = f"evid-gui-test-{uuid.uuid4().hex}"
    config = EvidConfig(data_dir=tmp_path)
    first = bootstrap_gui(qapp, config, background=True, instance_name=name)
    assert first is not None
    try:
        first.close()
        qapp.processEvents()
        assert not first.isVisible()
        second = bootstrap_gui(qapp, config, background=True, instance_name=name)
        assert second is None
        qtbot.waitUntil(first.isVisible, timeout=1000)
    finally:
        first.request_quit()
        qapp.processEvents()


def test_cursor_in_bottom_right_reveals_hidden_window(qapp, tmp_path, qtbot):
    from PySide6.QtGui import QCursor, QGuiApplication

    from evid.config import EvidConfig
    from evid.gui.main_window import EvidWindow

    window = EvidWindow(config=EvidConfig(data_dir=tmp_path), hide_on_close=True)
    window.show()
    window.close()
    qapp.processEvents()
    assert not window.isVisible()

    geo = QGuiApplication.primaryScreen().geometry()
    QCursor.setPos(geo.center())
    qapp.processEvents()
    QCursor.setPos(geo.x() + geo.width() - 1, geo.y() + geo.height() - 1)
    try:
        qtbot.waitUntil(window.isVisible, timeout=1500)
    finally:
        window.request_quit()
        qapp.processEvents()


def test_corner_watcher_activates_from_cursor_without_a_hint_widget(qapp, qtbot):
    from PySide6.QtGui import QCursor, QGuiApplication

    from evid.gui.corner_hint import CornerWatcher

    watcher = CornerWatcher(margin=16, dwell_ms=30, interval_ms=15)
    geo = QGuiApplication.primaryScreen().geometry()
    QCursor.setPos(geo.center())
    qapp.processEvents()
    try:
        with qtbot.waitSignal(watcher.activated, timeout=800):
            QCursor.setPos(geo.x() + geo.width() - 1, geo.y() + geo.height() - 1)
    finally:
        watcher.stop()


def test_prefer_x11_hot_corner_sets_xcb_on_wayland(monkeypatch):
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("DISPLAY", ":0")
    from evid.gui.main_window import prefer_x11_hot_corner

    prefer_x11_hot_corner()
    assert os.environ.get("QT_QPA_PLATFORM") == "xcb"


def test_jura_logo_icon_uses_brand_blue(qapp):
    from evid.gui.logo import jura_icon

    pixmap = jura_icon().pixmap(64, 64)
    assert not pixmap.isNull()
    color = pixmap.toImage().pixelColor(2, 2)
    # jura.sh frame is #2f5691, not the old #0078d4 "e" tile
    assert color.red() >= 30
    assert 70 <= color.green() <= 110
    assert 120 <= color.blue() <= 170


def test_x11_pointer_query_does_not_crash():
    from evid.gui.corner_hint import x11_pointer

    pos = x11_pointer()
    assert pos is None or (isinstance(pos, tuple) and len(pos) == 2)
