import pytest
from evid.core.bibtex import generate_bib_from_typ, generate_bibtex
import json
from unittest.mock import patch, MagicMock


@pytest.fixture
def temp_typ_file(tmp_path):
    typ_file = tmp_path / "label.typ"
    typ_file.write_text("content")
    json_file = tmp_path / "label.json"
    bib_file = tmp_path / "label.bib"
    return typ_file, json_file, bib_file


def test_generate_bib_from_typ(temp_typ_file):
    typ_file, json_file, bib_file = temp_typ_file
    mock_data = json.dumps(
        [
            {
                "value": {
                    "key": "key1",
                    "text": "quote",
                    "title": "title",
                    "date": "2023-01-01",
                    "opage": 1,
                    "note": "note",
                }
            }
        ]
    )

    def mock_run(args, stdout, stderr, check):
        stdout.write(mock_data)
        stdout.flush()
        result = MagicMock()
        result.returncode = 0
        result.stderr = b""
        result.args = args
        return result

    with patch("subprocess.run", side_effect=mock_run):
        with patch("evid.core.bibtex.json_to_bib") as mock_json_to_bib:
            success, msg = generate_bib_from_typ(typ_file)
            assert success
            assert msg == ""
            mock_json_to_bib.assert_called_with(json_file, bib_file, exclude_note=True)


def test_generate_bibtex(temp_typ_file):
    typ_file, _, _ = temp_typ_file
    with patch("evid.core.bibtex.generate_bib_from_typ", return_value=(True, "")):
        generate_bibtex([typ_file])
