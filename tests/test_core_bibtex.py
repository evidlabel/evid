import pytest
from pathlib import Path
from evid.core.bibtex import generate_bib_from_typ, generate_bibtex
import subprocess
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
    # Simulate typst query output
    mock_data = [{"value": {"key": "key1", "text": "quote", "title": "title", "date": "2023-01-01", "opage": 1, "note": "note"}}]
    json_file.write_text(json.dumps(mock_data))
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = b""
        with patch("evid.core.label_setup.json_to_bib") as mock_json_to_bib:
            success, msg = generate_bib_from_typ(typ_file)
            assert success
            assert msg == ""
            mock_json_to_bib.assert_called_with(json_file, bib_file, exclude_note=True)

def test_generate_bibtex(temp_typ_file):
    typ_file, _, _ = temp_typ_file
    with patch("evid.core.bibtex.generate_bib_from_typ", return_value=(True, "")):
        generate_bibtex([typ_file])
