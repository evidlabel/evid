import pytest
from unittest.mock import patch
from evid.gui.tabs.browse_evidence import BrowseEvidenceTab
from pathlib import Path
import yaml

@pytest.fixture
def browse_tab(qt_app, tmp_path):
    tab = BrowseEvidenceTab(tmp_path)
    yield tab

def test_load_metadata(browse_tab, tmp_path):
    dataset = tmp_path / "test_ds"
    dataset.mkdir()
    uuid_dir = dataset / "uuid1"
    uuid_dir.mkdir()
    info_path = uuid_dir / "info.yml"
    info_data = {
        "original_name": "test.pdf",
        "uuid": "uuid1",
        "time_added": "2023-01-01",
        "dates": "2023-01-01",
        "title": "Test",
        "authors": "Author",
        "tags": "",
        "label": "test",
        "url": ""
    }
    info_path.write_text(yaml.dump(info_data))
    browse_tab.dataset_combo.addItem("test_ds")
    browse_tab.load_metadata()
    assert browse_tab.table.rowCount() == 1
    assert browse_tab.table.item(0, 1).text() == "test"

def test_filter_metadata(browse_tab):
    browse_tab.metadata_entries = [(None, {"title": "Test", "authors": "Author", "time_added": "2023-01-01", "original_name": "test.pdf", "uuid": "uuid1", "label": "test"})]
    browse_tab.search_input.setText("Test")
    browse_tab.filter_metadata()
    assert browse_tab.table.rowCount() == 1

# Add more tests for open_directory, create_labels, generate_bibtex, run_rebut
