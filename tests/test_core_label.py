"""Test label creation."""

import subprocess
from unittest.mock import patch

import pytest

from evid.core.label import create_label


@pytest.fixture
def temp_pdf(tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.touch()
    return pdf


@pytest.fixture
def temp_txt(tmp_path):
    txt = tmp_path / "test.txt"
    txt.write_text("Hello world")
    return txt


def test_create_label_pdf(temp_pdf):
    with (
        patch("subprocess.run") as mock_run,
        patch("evid.core.label.textpdf_to_typst") as mock_typst,
        patch("evid.core.bibtex.generate_bib_from_typ", return_value=(True, "")),
    ):
        create_label(temp_pdf, "test_ds", "uuid1")
        mock_typst.assert_called()
        mock_run.assert_called()


def test_create_label_txt(temp_txt):
    with (
        patch("subprocess.run"),
        patch("evid.core.label.text_to_typst") as mock_typst,
        patch("evid.core.label.generate_bib_from_typ", return_value=(True, "")),
    ):
        create_label(temp_txt, "test_ds", "uuid1")
        mock_typst.assert_called()


def test_create_label_unsupported_type(tmp_path):
    unsupported = tmp_path / "test.docx"
    unsupported.touch()
    with patch("evid.core.label.textpdf_to_typst") as mock_typst:
        create_label(unsupported, "test_ds", "uuid1")
        mock_typst.assert_not_called()


def test_create_label_file_already_exists(temp_pdf):
    label_file = temp_pdf.parent / "label.typ"
    label_file.write_text("existing content")
    with (
        patch("subprocess.run"),
        patch("evid.core.label.textpdf_to_typst") as mock_typst,
        patch("evid.core.label.generate_bib_from_typ", return_value=(True, "")),
    ):
        create_label(temp_pdf, "test_ds", "uuid1")
        mock_typst.assert_not_called()


def test_create_label_editor_not_found(temp_pdf):
    with (
        patch("evid.core.label.textpdf_to_typst"),
        patch("subprocess.run", side_effect=FileNotFoundError),
    ):
        # Should not raise — logs error and returns early
        create_label(temp_pdf, "test_ds", "uuid1")


def test_create_label_subprocess_error(temp_pdf):
    with (
        patch("evid.core.label.textpdf_to_typst"),
        patch(
            "subprocess.run",
            side_effect=subprocess.SubprocessError("editor crashed"),
        ),
    ):
        create_label(temp_pdf, "test_ds", "uuid1")


def test_create_label_bibtex_failure(temp_pdf):
    with (
        patch("subprocess.run"),
        patch("evid.core.label.textpdf_to_typst"),
        patch(
            "evid.core.label.generate_bib_from_typ", return_value=(False, "typst error")
        ),
    ):
        create_label(temp_pdf, "test_ds", "uuid1")


def test_create_label_general_exception(temp_pdf):
    with patch(
        "evid.core.label.textpdf_to_typst", side_effect=RuntimeError("unexpected")
    ):
        create_label(temp_pdf, "test_ds", "uuid1")
