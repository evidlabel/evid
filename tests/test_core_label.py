import pytest
from unittest.mock import patch
from evid.core.label import create_label
from pathlib import Path

@pytest.fixture
def temp_pdf(tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.touch()
    return pdf

def test_create_label_pdf(temp_pdf):
    with patch("subprocess.run") as mock_run, patch("evid.core.label.textpdf_to_typst") as mock_typst, patch("evid.core.bibtex.generate_bib_from_typ", return_value=(True, "")):
        create_label(temp_pdf, "test_ds", "uuid1")
        mock_typst.assert_called()
        mock_run.assert_called()
