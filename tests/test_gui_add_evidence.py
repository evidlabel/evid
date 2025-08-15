import pytest
from PyQt6.QtWidgets import QApplication
from unittest.mock import patch
from evid.gui.tabs.add_evidence import AddEvidenceTab
import sys


@pytest.fixture
def add_tab(tmp_path):
    app = QApplication(sys.argv)  # Required for PyQt
    tab = AddEvidenceTab(tmp_path)
    yield tab
    app.quit()


@patch("PyQt6.QtWidgets.QMessageBox.warning")
def test_add_evidence_missing_fields(mock_warning, add_tab):
    # Simulate missing fields by not filling anything
    add_tab.dataset_combo.clear()  # No dataset selected
    add_tab.add_evidence()
    mock_warning.assert_called_once()


def test_create_dataset(add_tab, tmp_path):
    dataset_name = "test_dataset"
    add_tab.new_dataset_input.setText(dataset_name)
    add_tab.create_dataset()

    assert dataset_name in add_tab.get_datasets()
    assert (tmp_path / dataset_name).exists()
