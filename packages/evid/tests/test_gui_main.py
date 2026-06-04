"""Headless GUI smoke tests for evidmgr."""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("CI") != "true" and os.environ.get("HEADLESS") != "1",
    reason="GUI tests require headless/CI env (set HEADLESS=1)",
)


@pytest.fixture(scope="module")
def qapp():
    import sys

    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


def test_main_window_creates(qapp, tmp_path):
    from evid.config import EvidConfig
    from evid.gui.main_window import EvidMgrWindow

    config = EvidConfig(data_dir=tmp_path)
    window = EvidMgrWindow(config=config)
    assert window is not None
    assert window.windowTitle() == "Evidence Manager"
    window.close()


def test_sidebar_shows_empty_sets(qapp, tmp_path):
    from evid.config import EvidConfig
    from evid.gui.main_window import EvidMgrWindow

    config = EvidConfig(data_dir=tmp_path)
    window = EvidMgrWindow(config=config)
    assert window._sidebar._list.count() == 0
    window.close()


def test_sidebar_create_set(qapp, tmp_path):
    from evid.config import EvidConfig
    from evid.gui.main_window import EvidMgrWindow

    config = EvidConfig(data_dir=tmp_path)
    window = EvidMgrWindow(config=config)
    window._set_manager.create_set("Test Set")
    window._sidebar.refresh()
    assert window._sidebar._list.count() == 1
    window.close()
