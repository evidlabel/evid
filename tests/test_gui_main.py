"""Headless GUI smoke tests for evidmgr."""

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


def test_main_window_creates(qapp, tmp_path):
    from evid.config import EvidConfig
    from evid.gui.main_window import EvidMgrWindow

    config = EvidConfig(data_dir=tmp_path)
    window = EvidMgrWindow(config=config)
    assert window is not None
    assert window.windowTitle() == "Evidence Manager"
    window.close()


def test_main_window_creates_without_vec_extra(qapp, tmp_path, monkeypatch):
    from evid import extras
    from evid.config import EvidConfig
    from evid.gui.main_window import EvidMgrWindow

    monkeypatch.setattr(extras, "has_vec", lambda: False)
    config = EvidConfig(data_dir=tmp_path)
    window = EvidMgrWindow(config=config)
    assert window._vec_service is None
    assert not window._docs_tab._index_btn.isEnabled()
    assert not window._search_tab._sub_tabs.isTabEnabled(1)
    assert window._search_tab._sub_tabs.currentIndex() == 0
    window.close()


def test_gui_callback_does_not_mask_vec_import_error(monkeypatch, capsys):
    import evid.cli.callbacks as cb
    import evid.gui.main_window as mw
    from evid import extras

    monkeypatch.setattr(extras, "has_gui", lambda: True)

    def _boom(*_a, **_k):
        raise ImportError("Vector search requires the vec extra")

    monkeypatch.setattr(mw, "main", _boom)
    with pytest.raises(ImportError, match="vec extra"):
        cb.gui_callback()
    assert "evid[gui]" not in capsys.readouterr().out


def test_main_window_help_button_opens_dialog(qapp, tmp_path):
    from unittest.mock import patch

    from PySide6.QtWidgets import QLabel

    from evid.config import EvidConfig
    from evid.gui.main_window import EvidMgrWindow, HelpDialog

    config = EvidConfig(data_dir=tmp_path)
    window = EvidMgrWindow(config=config)
    btn = window._help_btn
    assert btn.text() == "Help"

    with patch.object(HelpDialog, "exec", return_value=0) as exec_mock:
        btn.click()
    exec_mock.assert_called_once()
    window.close()

    dlg = HelpDialog()
    assert dlg.windowTitle() == "Help"
    body = dlg.findChild(QLabel, "help_body")
    assert body is not None
    text = body.text().lower()
    assert "tabs" in text
    assert "shortcuts" in text
    assert "ctrl+pageup" in text
    assert "alt+drag" in text
    assert "#lab" in text
    assert "-d" not in text
    assert "workdir" not in text
    dlg.close()


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


def test_docs_tab_loads_selected_set_on_startup(qapp, tmp_path):
    from evid.config import EvidConfig
    from evid.gui.main_window import EvidMgrWindow

    config = EvidConfig(data_dir=tmp_path)
    window = EvidMgrWindow(config=config)
    window._set_manager.create_set("Startup Set")
    window._sidebar.refresh()
    window._sidebar.select_first()
    assert window._docs_tab._evidence_set is not None
    assert window._docs_tab._evidence_set.slug == window._sidebar.active_set().slug
    window.close()


def test_docs_table_has_no_row_hover_tooltip(qapp, tmp_path):
    """A table-level QToolTip steals the first right-click after a hover."""
    from evid.config import EvidConfig
    from evid.gui.main_window import EvidMgrWindow

    config = EvidConfig(data_dir=tmp_path)
    window = EvidMgrWindow(config=config)
    table = window._docs_tab._table
    assert table.toolTip() == ""
    assert table.viewport().toolTip() == ""
    window.close()


def test_hover_tooltip_is_click_through(qapp, tmp_path):
    """QTipLabel must ignore mouse events so right-click reaches the table."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QToolTip

    from evid.config import EvidConfig
    from evid.gui.main_window import EvidMgrWindow

    config = EvidConfig(data_dir=tmp_path)
    window = EvidMgrWindow(config=config)
    window.show()
    qapp.processEvents()
    QToolTip.showText(window.mapToGlobal(window.rect().center()), "row hover", window)
    qapp.processEvents()
    tips = [
        w for w in qapp.topLevelWidgets() if w.inherits("QTipLabel") and w.isVisible()
    ]
    assert tips, "expected a visible hover tooltip"
    for tip in tips:
        assert tip.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    QToolTip.hideText()
    qapp.processEvents()
    window.close()


def _write_doc(set_path, doc_uuid: str, label: str = "Test doc", **info_extra) -> None:
    import yaml

    doc_dir = set_path / "docs" / doc_uuid
    doc_dir.mkdir(parents=True)
    payload = {
        "label": label,
        "tags": "",
        "title": label,
        "authors": "",
        "dates": "2024",
        "url": "",
    }
    payload.update(info_extra)
    with (doc_dir / "info.yml").open("w") as f:
        yaml.safe_dump(payload, f)
    with (doc_dir / "evid_meta.yml").open("w") as f:
        yaml.safe_dump({"notes": "", "indexed": False}, f)


def _context_menu_stub():
    from unittest.mock import MagicMock

    mock_menu = MagicMock()
    mock_menu.exec.return_value = None
    mock_menu.addAction.return_value = MagicMock()
    mock_menu.addMenu.return_value = MagicMock()
    mock_menu.addSeparator.return_value = None
    return mock_menu


def test_docs_right_click_opens_menu_on_unselected_row(qapp, tmp_path):
    """Right-click must select the hovered row and still open the menu."""
    from unittest.mock import patch

    from evid.config import EvidConfig
    from evid.gui.main_window import EvidMgrWindow

    config = EvidConfig(data_dir=tmp_path)
    window = EvidMgrWindow(config=config)
    evidence_set = window._set_manager.create_set("Case")
    _write_doc(evidence_set.path, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    window._sidebar.refresh()
    window._sidebar.select_first()
    qapp.processEvents()

    tab = window._docs_tab
    table = tab._table
    assert table.rowCount() == 1
    table.clearSelection()
    item = table.item(0, 2)
    assert item is not None
    # customContextMenuRequested emits viewport coordinates.
    vp_pos = table.visualItemRect(item).center()

    mock_menu = _context_menu_stub()
    with patch("evid.gui.tabs.docs_tab.QMenu", return_value=mock_menu):
        tab._on_context_menu(vp_pos)

    assert table.item(0, 2).isSelected()
    mock_menu.exec.assert_called_once()
    window.close()


def test_docs_right_click_keeps_filtered_selection(qapp, tmp_path):
    """Right-click on a non-first filtered row must not jump to row 0.

    After the docs-tab filter rebuilds the table, Qt delivers the context-menu
    event through the viewport. Mapping that pos as table-widget coordinates
    hits the header offset and selects the top remaining row.
    """
    from unittest.mock import patch

    from PySide6.QtGui import QContextMenuEvent

    from evid.config import EvidConfig
    from evid.gui.main_window import EvidMgrWindow

    config = EvidConfig(data_dir=tmp_path)
    window = EvidMgrWindow(config=config)
    evidence_set = window._set_manager.create_set("Case")
    _write_doc(
        evidence_set.path,
        "aaaaaaaa-bbbb-cccc-dddd-111111111111",
        label="Alpha report",
        time_added="2024-01-01",
    )
    _write_doc(
        evidence_set.path,
        "aaaaaaaa-bbbb-cccc-dddd-222222222222",
        label="Beta report",
        time_added="2024-01-02",
    )
    _write_doc(
        evidence_set.path,
        "aaaaaaaa-bbbb-cccc-dddd-333333333333",
        label="Gamma report",
        time_added="2024-01-03",
    )
    window._sidebar.refresh()
    window._sidebar.select_first()
    window.resize(1400, 900)
    window.show()
    qapp.processEvents()

    tab = window._docs_tab
    table = tab._table
    tab._filter.setText("report")
    qapp.processEvents()
    assert table.rowCount() == 3
    table.selectRow(1)
    qapp.processEvents()
    assert table.item(1, 2).text() == "Beta report"

    item = table.item(1, 2)
    assert item is not None
    vp_pos = table.visualItemRect(item).center()
    global_pos = table.viewport().mapToGlobal(vp_pos)

    mock_menu = _context_menu_stub()
    with patch("evid.gui.tabs.docs_tab.QMenu", return_value=mock_menu):
        ev = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, vp_pos, global_pos)
        qapp.sendEvent(table.viewport(), ev)
        qapp.processEvents()

    selected = [i.row() for i in table.selectionModel().selectedRows()]
    assert selected == [1], f"right-click jumped selection to {selected}"
    assert table.item(1, 2).text() == "Beta report"
    mock_menu.exec.assert_called_once()
    window.close()


def test_detail_pane_coerces_list_authors_and_tags(qapp, tmp_path):
    """info.yml may store authors/tags/dates as YAML lists; the form is text."""
    from evid.config import EvidConfig
    from evid.gui.main_window import EvidMgrWindow

    config = EvidConfig(data_dir=tmp_path)
    window = EvidMgrWindow(config=config)
    evidence_set = window._set_manager.create_set("Case")
    _write_doc(
        evidence_set.path,
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        authors=["Alice", "Bob"],
        tags=["urgent", "review"],
        dates=["2024-01-01", "2024-06-01"],
    )
    window._sidebar.refresh()
    window._sidebar.select_first()
    qapp.processEvents()

    tab = window._docs_tab
    tab._table.selectRow(0)
    qapp.processEvents()

    assert tab._detail_authors.text() == "Alice, Bob"
    assert tab._detail_tags.text() == "urgent, review"
    assert tab._detail_dates.text() == "2024-01-01, 2024-06-01"
    window.close()
