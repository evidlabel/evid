import pytest
from pathlib import Path
from evid.core.bibtex import generate_bib_from_typ, generate_bibtex
from unittest.mock import patch, mock_open, MagicMock
import json

@pytest.fixture
def temp_typ_file(tmp_path):
    typ_file = tmp_path / "label.typ"
    typ_file.write_text("content")
    json_file = tmp_path / "label.json"
    bib_file = tmp_path / "label.bib"
    return typ_file, json_file, bib_file

def test_generate_bib_from_typ(temp_typ_file):
    typ_file, json_file, bib_file = temp_typ_file
    mock_data = [{"value": {"key": "key1", "text": "quote", "title": "title", "date": "2023-01-01", "opage": 1, "note": "note"}}]
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch("builtins.open", mock_open()) as mock_file:
            mock_file.side_effect = [mock_open(read_data="").return_value, mock_open().return_value]
            with patch("json.load", return_value=mock_data):
                with patch("evid.core.label_setup.json_to_bib"):
                    success, msg = generate_bib_from_typ(typ_file)
                    assert success
                    assert msg == ""

def test_generate_bibtex(temp_typ_file):
    typ_file, _, _ = temp_typ_file
    with patch("evid.core.bibtex.generate_bib_from_typ", return_value=(True, "")):
        generate_bibtex([typ_file])
