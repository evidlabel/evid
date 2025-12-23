"""Test GUI browse evidence tab."""

import pytest
from evid.gui.tabs.browse_evidence import BrowseEvidenceTab
import yaml
from PySide6.QtWidgets import QTableWidgetItem
import os
from unittest.mock import patch


@pytest.fixture
def browse_tab(tmp_path):
    tab = BrowseEvidenceTab(tmp_path)
    yield tab


def test_init_ui(browse_tab):
    assert browse_tab.dataset_combo is not None
    assert browse_tab.table is not None


def test_get_datasets(browse_tab, tmp_path):
    (tmp_path / "test_ds").mkdir()
    datasets = browse_tab.get_datasets()
    assert "test_ds" in datasets


def test_load_metadata(browse_tab, tmp_path):
    dataset = "test_ds"
    (tmp_path / dataset).mkdir()
    uuid_dir = tmp_path / dataset / "uuid1"
    uuid_dir.mkdir()
    info_data = {
        "original_name": "test.pdf",
        "uuid": "uuid1",
        "time_added": "2023-01-01",
        "dates": "2023-01-01",
        "title": "Test",
        "authors": "Author",
        "tags": "",
        "label": "test",
        "url": "",
    }
    with (uuid_dir / "info.yml").open("w") as f:
        yaml.dump(info_data, f)
    browse_tab.dataset_combo.addItem(dataset)
    browse_tab.dataset_combo.setCurrentText(dataset)
    browse_tab.load_metadata()
    assert browse_tab.table.rowCount() == 1


def test_filter_metadata(browse_tab, tmp_path):
    # Setup metadata
    browse_tab.metadata_entries = [
        (
            "2023-01-01",
            {
                "title": "Test Doc",
                "authors": "Author",
                "time_added": "2023-01-01",
                "uuid": "uuid1",
                "original_name": "test.pdf",
                "label": "test",
            },
        )
    ]
    browse_tab.filter_metadata()
    assert browse_tab.table.rowCount() == 1
    # Test search
    browse_tab.search_input.setText("Test")
    browse_tab.filter_metadata()
    assert browse_tab.table.rowCount() == 1
    browse_tab.search_input.setText("Nonexistent")
    browse_tab.filter_metadata()
    assert browse_tab.table.rowCount() == 0


def test_open_directory(browse_tab, tmp_path):
    dataset = "test_ds"
    (tmp_path / dataset).mkdir()
    uuid_dir = tmp_path / dataset / "uuid1"
    uuid_dir.mkdir()
    browse_tab.dataset_combo.addItem(dataset)
    browse_tab.dataset_combo.setCurrentText(dataset)
    # Add row to table
    browse_tab.table.insertRow(0)
    browse_tab.table.setItem(0, 4, QTableWidgetItem("uuid1"))
    # Select the row
    browse_tab.table.selectRow(0)
    with patch("subprocess.run") as mock_run:
        browse_tab.open_directory()
        mock_run.assert_called_once()


def test_create_labels(browse_tab, tmp_path):
    dataset = "test_ds"
    (tmp_path / dataset).mkdir()
    uuid_dir = tmp_path / dataset / "uuid1"
    uuid_dir.mkdir()
    pdf_file = uuid_dir / "test.pdf"
    MINIMAL_PDF = b"%PDF-1.0\n%%EOF"
    pdf_file.write_bytes(MINIMAL_PDF)
    browse_tab.dataset_combo.addItem(dataset)
    browse_tab.dataset_combo.setCurrentText(dataset)
    # Add row to table
    browse_tab.table.insertRow(0)
    browse_tab.table.setItem(0, 3, QTableWidgetItem("test.pdf"))
    browse_tab.table.setItem(0, 4, QTableWidgetItem("uuid1"))
    browse_tab.table.selectRow(0)
    with patch("evid.gui.tabs.browse_evidence.create_label") as mock_create:
        browse_tab.create_labels()
        mock_create.assert_called_once_with(pdf_file, dataset, "uuid1")


@pytest.mark.skipif(
    os.environ.get("HEADLESS") == "1"
    or os.environ.get("QT_QPA_PLATFORM") == "offscreen"
    or os.environ.get("CI") == "true",
    reason="Skipped in headless or CI mode",
)
def test_generate_bibtex(browse_tab, tmp_path):
    dataset = "test_ds"
    (tmp_path / dataset).mkdir()
    uuid_dir = tmp_path / dataset / "uuid1"
    uuid_dir.mkdir()
    typ_file = uuid_dir / "label.typ"
    typ_file.write_text("dummy typst content")
    browse_tab.dataset_combo.addItem(dataset)
    browse_tab.dataset_combo.setCurrentText(dataset)
    # Add row to table
    browse_tab.table.insertRow(0)
    browse_tab.table.setItem(0, 3, QTableWidgetItem("test.pdf"))
    browse_tab.table.setItem(0, 4, QTableWidgetItem("uuid1"))
    browse_tab.table.selectRow(0)
    with patch(
        "evid.gui.tabs.browse_evidence.generate_bib_from_typ", return_value=(True, "")
    ) as mock_gen:
        browse_tab.generate_bibtex()
        mock_gen.assert_called_once()


def test_run_rebut(browse_tab, tmp_path):
    dataset = "test_ds"
    (tmp_path / dataset).mkdir()
    uuid_dir = tmp_path / dataset / "uuid1"
    uuid_dir.mkdir()
    workdir = uuid_dir
    browse_tab.dataset_combo.addItem(dataset)
    browse_tab.dataset_combo.setCurrentText(dataset)
    # Add row to table
    browse_tab.table.insertRow(0)
    browse_tab.table.setItem(0, 4, QTableWidgetItem("uuid1"))
    browse_tab.table.selectRow(0)
    with patch("evid.core.rebut_doc.rebut_doc") as mock_rebut:
        browse_tab.run_rebut()
        mock_rebut.assert_called_once_with(workdir)
