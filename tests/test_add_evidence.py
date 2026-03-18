import hashlib
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from evid.gui.tabs.add_evidence import AddEvidenceTab


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def add_tab(qapp, temp_dir):
    tab = AddEvidenceTab(directory=temp_dir)
    tab.dataset_combo = MagicMock()
    tab.dataset_combo.currentText.return_value = "test_dataset"
    tab.file_input = MagicMock()
    tab.title_input = MagicMock()
    tab.authors_input = MagicMock()
    tab.tags_input = MagicMock()
    tab.dates_input = MagicMock()
    tab.label_input = MagicMock()
    tab.url_input = MagicMock()
    tab.new_dataset_input = MagicMock()
    tab.preview_text = MagicMock()
    return tab


@patch("evid.gui.tabs.add_evidence.QMessageBox")
def test_add_evidence_success_local(mock_msgbox, add_tab, temp_dir):
    content = b"dummy pdf content"
    pdf_path = temp_dir / "test.pdf"
    pdf_path.write_bytes(content)
    add_tab.file_input.text.return_value = str(pdf_path)
    add_tab.title_input.text.return_value = "Test Title"
    add_tab.authors_input.text.return_value = "Test Author"
    add_tab.dates_input.text.return_value = "2023-01-01"
    add_tab.tags_input.text.return_value = ""
    add_tab.label_input.text.return_value = "test_title"
    add_tab.url_input.text.return_value = ""
    add_tab.is_temp_file = False

    dataset_path = temp_dir / "test_dataset"
    dataset_path.mkdir()

    add_tab.add_evidence()

    digest = hashlib.sha256(content).digest()[:16]
    expected_uuid = uuid.UUID(bytes=digest).hex
    assert (dataset_path / expected_uuid / "test.pdf").exists()
    mock_msgbox.critical.assert_not_called()
    mock_msgbox.warning.assert_not_called()


@patch("evid.gui.tabs.add_evidence.subprocess.run")
@patch("evid.gui.tabs.add_evidence.QMessageBox")
def test_add_evidence_duplicate_content(mock_msgbox, mock_run, add_tab, temp_dir):
    content = b"dummy pdf content"
    pdf_path = temp_dir / "test.pdf"
    pdf_path.write_bytes(content)
    add_tab.file_input.text.return_value = str(pdf_path)
    add_tab.title_input.text.return_value = "Test Title"
    add_tab.authors_input.text.return_value = "Test Author"
    add_tab.dates_input.text.return_value = "2023-01-01"
    add_tab.tags_input.text.return_value = ""
    add_tab.label_input.text.return_value = "test_title"
    add_tab.url_input.text.return_value = ""
    add_tab.is_temp_file = False

    dataset_path = temp_dir / "test_dataset"
    dataset_path.mkdir()

    # First add should succeed silently
    add_tab.add_evidence()
    mock_msgbox.information.assert_not_called()

    # Second add same content → duplicate detected
    add_tab.add_evidence()
    mock_msgbox.information.assert_called_once()


@patch("evid.gui.tabs.add_evidence.requests.get")
@patch("evid.gui.tabs.add_evidence.QMessageBox")
def test_quick_add_from_url_success(mock_msgbox, mock_get, add_tab):
    mock_response = MagicMock()
    mock_response.content = b"dummy pdf content"
    mock_response.headers = {"Content-Type": "application/pdf"}
    mock_response.raise_for_status.return_value = None
    mock_get.return_value = mock_response

    add_tab.url_input.text.return_value = "http://example.com/test.pdf"

    add_tab.quick_add_from_url()

    assert add_tab.is_temp_file
    assert add_tab.temp_dir is not None
    add_tab.file_input.setText.assert_called()
    mock_msgbox.critical.assert_not_called()

    if add_tab.temp_dir:
        add_tab.temp_dir.cleanup()


@patch("evid.gui.tabs.add_evidence.requests.get")
@patch("evid.gui.tabs.add_evidence.QMessageBox")
def test_quick_add_from_url_failure(mock_msgbox, mock_get, add_tab):
    import requests

    mock_get.side_effect = requests.RequestException("Network error")
    add_tab.url_input.text.return_value = "http://example.com/test.pdf"

    add_tab.quick_add_from_url()

    mock_msgbox.critical.assert_called_once()


@patch("evid.gui.tabs.add_evidence.QMessageBox")
def test_add_evidence_temp_file_cleanup(mock_msgbox, add_tab, temp_dir):
    content = b"dummy pdf content"
    pdf_path = temp_dir / "test.pdf"
    pdf_path.write_bytes(content)

    mock_temp_dir = MagicMock()
    add_tab.file_input.text.return_value = str(pdf_path)
    add_tab.title_input.text.return_value = "Test Title"
    add_tab.authors_input.text.return_value = "Test Author"
    add_tab.dates_input.text.return_value = "2023-01-01"
    add_tab.tags_input.text.return_value = ""
    add_tab.label_input.text.return_value = "test_title"
    add_tab.url_input.text.return_value = ""
    add_tab.is_temp_file = True
    add_tab.temp_dir = mock_temp_dir

    dataset_path = temp_dir / "test_dataset"
    dataset_path.mkdir()

    add_tab.add_evidence()

    mock_temp_dir.cleanup.assert_called_once()
    assert not add_tab.is_temp_file


@patch("evid.gui.tabs.add_evidence.QMessageBox")
def test_browse_file_sets_not_temp(mock_msgbox, add_tab, temp_dir):
    pdf_path = temp_dir / "test.pdf"
    pdf_path.write_bytes(b"dummy pdf content")

    with patch(
        "PySide6.QtWidgets.QFileDialog.getOpenFileName",
        return_value=(str(pdf_path), ""),
    ):
        add_tab.browse_file()

    assert not add_tab.is_temp_file
    add_tab.file_input.setText.assert_called_with(str(pdf_path))
