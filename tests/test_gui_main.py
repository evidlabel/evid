import pytest
from PyQt6.QtWidgets import QApplication
from evid.gui.main import EvidenceManagerApp, main


@pytest.fixture
def app(qtbot):
    test_app = QApplication.instance()
    if not test_app:
        test_app = QApplication([""])
    yield test_app
    test_app.quit()


def test_evidence_manager_app_init(app, tmp_path):
    window = EvidenceManagerApp(tmp_path)
    assert window.windowTitle() == "evid"
    assert window.tabs.count() == 2
    assert window.tabs.tabText(0) == "Add"
    assert window.tabs.tabText(1) == "Browse"


def test_set_dark_theme(app, tmp_path):
    window = EvidenceManagerApp(tmp_path)
    palette = window.palette()
    assert palette.color(palette.ColorRole.Window).name() == "#2e2e2e"


def test_main(tmp_path):
    with patch("sys.exit") as mock_exit:
        with patch("PyQt6.QtWidgets.QApplication.exec") as mock_exec:
            main(tmp_path)
        mock_exec.assert_called_once()
