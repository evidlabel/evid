"""Tests for gdid GUI application."""

from unittest.mock import patch

import pytest


@pytest.fixture
def main_window(qtbot):
    from gdid.main import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    return window


def test_window_title(main_window):
    assert "DID" in main_window.windowTitle()


def test_default_language(main_window):
    assert main_window.language == "da"


def test_initial_state(main_window):
    assert main_window.files == []
    assert main_window.extracted_texts == {}
    assert main_window.anonymized_texts == {}
    assert main_window.yaml_configs == {}
    assert main_window.anonymizer is None


def test_change_language(main_window):
    main_window.lang_combo.setCurrentText("en")
    assert main_window.language == "en"
    main_window.lang_combo.setCurrentText("da")
    assert main_window.language == "da"


def test_extract_texts_warns_without_files(main_window, qtbot):
    with patch("gdid.main.QMessageBox.warning") as mock_warn:
        main_window.extract_texts()
        mock_warn.assert_called_once()


def test_detect_entities_warns_without_extracted(main_window, qtbot):
    with patch("gdid.main.QMessageBox.warning") as mock_warn:
        main_window.detect_entities()
        mock_warn.assert_called_once()


def test_pseudonymize_warns_without_detected(main_window, qtbot):
    with patch("gdid.main.QMessageBox.warning") as mock_warn:
        main_window.pseudonymize()
        mock_warn.assert_called_once()


def test_save_warns_without_pseudonymized(main_window, qtbot):
    with patch("gdid.main.QMessageBox.warning") as mock_warn:
        main_window.save_files()
        mock_warn.assert_called_once()


def test_update_file_list_empty(main_window):
    main_window.update_file_list()
    assert main_window.file_list.count() == 0


def test_file_list_reflects_processing_state(main_window, tmp_path):
    fake_file = tmp_path / "test.pdf"
    fake_file.touch()
    main_window.files = [fake_file]
    main_window.update_file_list()
    assert main_window.file_list.count() == 1

    # Mark as extracted
    main_window.extracted_texts[fake_file] = "some text"
    main_window.update_file_list()
    assert main_window.file_list.count() == 1
