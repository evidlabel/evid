import pytest
from PyQt6.QtWidgets import QApplication
from evid.gui.tabs.browse_evidence import BrowseEvidenceTab
import yaml
import sys


@pytest.fixture
def browse_tab(tmp_path):
    app = QApplication(sys.argv)
    tab = BrowseEvidenceTab(tmp_path)
    yield tab
    app.quit()


@pytest.fixture
def setup_dataset(tmp_path):
    dataset_path = tmp_path / "test_dataset"
    entry = dataset_path / "uuid"
    entry.mkdir(parents=True)
    with (entry / "info.yml").open("w") as f:
        yaml.dump(
            {
                "authors": "Author",
                "label": "Test",
                "time_added": "2023-01-01",
                "original_name": "test.pdf",
                "uuid": "uuid",
            },
            f,
        )
    return "test_dataset"


@pytest.mark.skip("Skipping test_load_metadata for now")
def test_load_metadata_valid(browse_tab, setup_dataset):
    browse_tab.dataset_combo.addItem(setup_dataset)
    browse_tab.load_metadata()

    assert browse_tab.table.rowCount() == 1
    assert browse_tab.table.item(0, 0).text() == "Author"
    assert browse_tab.table.item(0, 1).text() == "Test"


@pytest.mark.skip("Skipping test_load_metadata for now")
def test_load_metadata_empty_info(browse_tab, tmp_path):
    dataset_path = tmp_path / "empty_dataset"
    entry = dataset_path / "uuid"
    entry.mkdir(parents=True)
    (entry / "info.yml").touch
