"""Test GUI add evidence tab."""

from unittest.mock import MagicMock, patch

import pytest

from evid.gui.tabs.add_evidence import AddEvidenceTab


@pytest.fixture
def add_tab(qapp, tmp_path):
    import os

    saved = {k: os.environ.pop(k, None) for k in ("QT_QPA_PLATFORM", "HEADLESS", "CI")}
    try:
        tab = AddEvidenceTab(tmp_path)
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    return tab


def test_init_ui(add_tab):
    assert add_tab.dataset_combo is not None
    assert add_tab.file_input is not None


def test_get_datasets(add_tab, tmp_path):
    # Create a dataset
    (tmp_path / "test_ds").mkdir()
    datasets = add_tab.get_datasets()
    assert "test_ds" in datasets


def test_create_dataset(add_tab, tmp_path):
    add_tab.new_dataset_input.setText("new_ds")
    add_tab.create_dataset()
    assert (tmp_path / "new_ds").exists()
    assert "new_ds" in add_tab.get_datasets()


def test_prefill_fields_uses_pdf_title_as_label(add_tab, tmp_path):
    pdf_path = tmp_path / "248080.pdf"
    pdf_path.write_bytes(b"%PDF-1.0\n%%EOF")
    with patch("evid.gui.tabs.add_evidence.pypdf.PdfReader") as mock_reader:
        mock_meta = MagicMock()
        mock_meta.get.side_effect = lambda key, default=None: {
            "/Title": "Bekendtgørelse af barnets lov",
        }.get(key, default)
        mock_reader.return_value.metadata = mock_meta
        add_tab.prefill_fields(pdf_path)
        assert add_tab.title_input.text() == "248080"
        assert add_tab.label_input.text() == "bekendtgørelse_af_barnets_lov"


def test_prefill_fields_fallback_to_filename_when_no_pdf_title(add_tab, tmp_path):
    pdf_path = tmp_path / "248080.pdf"
    pdf_path.write_bytes(b"%PDF-1.0\n%%EOF")
    with patch("evid.gui.tabs.add_evidence.pypdf.PdfReader") as mock_reader:
        mock_meta = MagicMock()
        mock_meta.get.return_value = None
        mock_reader.return_value.metadata = mock_meta
        add_tab.prefill_fields(pdf_path)
        assert add_tab.title_input.text() == "248080"
        assert add_tab.label_input.text() == "248080"


def test_add_evidence(add_tab, tmp_path):
    add_tab.dataset_combo.addItem("test_ds")
    add_tab.dataset_combo.setCurrentText("test_ds")
    (tmp_path / "test_ds").mkdir()
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"%PDF-1.0\n%%EOF")
    add_tab.file_input.setText(str(pdf_path))
    add_tab.title_input.setText("Title")
    add_tab.authors_input.setText("Author")
    add_tab.dates_input.setText("2023-01-01")
    with patch("evid.gui.tabs.add_evidence.shutil.copy2"):
        with patch("evid.gui.tabs.add_evidence.yaml.dump"):
            add_tab.add_evidence()
        # Check if info.yml is created
        unique_dirs = list((tmp_path / "test_ds").iterdir())
        assert len(unique_dirs) == 1
        assert (unique_dirs[0] / "info.yml").exists()
