import pytest
from PyQt6.QtWidgets import QApplication
from evid.gui.tabs.add_evidence import AddEvidenceTab
from pathlib import Path
import sys


@pytest.fixture
def add_tab(tmp_path):
    app = QApplication(sys.argv)  # Required for PyQt
    tab = AddEvidenceTab(tmp_path)
    yield tab
    app.quit()


@pytest.mark.skip("Skipping test_add_evidence for now")
def test_add_evidence_missing_fields(add_tab):
    # Simulate missing fields by not filling anything
    add_tab.dataset_combo.clear()  # No dataset selected
    result = add_tab.add_evidence()
    assert result is None  # Should return None due to validation


@pytest.mark.skip("Skipping test_create_dataset for now")
def test_create_dataset(add_tab, tmp_path):
    dataset_name = "test_dataset"
    add_tab.new_dataset_input.setText(dataset_name)
    add_tab.create_dataset()

    assert dataset_name in add_tab.get_datasets()
    assert (tmp_path / dataset_name).exists()
