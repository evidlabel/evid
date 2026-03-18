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


def test_add_evidence_success_local(add_tab, temp_dir):
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


def test_add_evidence_duplicate_content(add_tab, temp_dir):
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

    # Second add same content — duplicate detected, returns silently
    with patch("evid.gui.tabs.add_evidence.logger") as mock_log:
        add_tab.add_evidence()
        mock_log.info.assert_called()


@patch("evid.gui.tabs.add_evidence.requests.get")
def test_quick_add_from_url_success(mock_get, add_tab):
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

    if add_tab.temp_dir:
        add_tab.temp_dir.cleanup()


@patch("evid.gui.tabs.add_evidence.requests.get")
def test_quick_add_from_url_failure(mock_get, add_tab):
    import requests

    mock_get.side_effect = requests.RequestException("Network error")
    add_tab.url_input.text.return_value = "http://example.com/test.pdf"

    with patch("evid.gui.tabs.add_evidence.logger") as mock_log:
        add_tab.quick_add_from_url()
        mock_log.error.assert_called()


def test_add_evidence_temp_file_cleanup(add_tab, temp_dir):
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


def test_browse_file_sets_not_temp(add_tab, temp_dir):
    pdf_path = temp_dir / "test.pdf"
    pdf_path.write_bytes(b"dummy pdf content")

    with patch(
        "PySide6.QtWidgets.QFileDialog.getOpenFileName",
        return_value=(str(pdf_path), ""),
    ):
        add_tab.browse_file()

    assert not add_tab.is_temp_file
    add_tab.file_input.setText.assert_called_with(str(pdf_path))
