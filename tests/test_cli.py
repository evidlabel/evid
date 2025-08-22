import pytest
from unittest.mock import patch, MagicMock
from evid.cli.dataset import get_datasets, select_dataset, create_dataset
from evid.cli.evidence import add_evidence
from evid.core.bibtex import generate_bibtex
from evid import CONFIG
import json

MINIMAL_PDF = b"%PDF-1.0\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 3 3]>>endobj xref 0 4\n0000000000 65535 f\n0000000010 00000 n\n0000000053 00000 n\n0000000102 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref 149 %%EOF"


@pytest.fixture
def temp_dir(tmp_path):
    return tmp_path


def test_get_datasets(temp_dir):
    (temp_dir / "dataset1").mkdir()
    (temp_dir / "dataset2").mkdir()
    (temp_dir / ".hidden").mkdir()
    assert sorted(get_datasets(temp_dir)) == ["dataset1", "dataset2"]


@patch("builtins.input", side_effect=["1"])
def test_select_dataset_existing(mock_input, temp_dir):
    (temp_dir / "dataset2").mkdir()  # Create in order to match output
    (temp_dir / "dataset1").mkdir()
    assert select_dataset(temp_dir, "Select dataset") == "dataset2"


@patch("builtins.input", side_effect=["3", "new_dataset"])
def test_select_dataset_create_new(mock_input, temp_dir):
    (temp_dir / "dataset2").mkdir()
    (temp_dir / "dataset1").mkdir()
    assert select_dataset(temp_dir, "Select dataset") == "new_dataset"
    assert (temp_dir / "new_dataset").exists()


def test_create_dataset(temp_dir):
    create_dataset(temp_dir, "new_dataset")
    assert (temp_dir / "new_dataset").exists()


@patch("evid.core.label.generate_bib_from_typ", return_value=(True, ""))
@patch("evid.core.label.subprocess.run")
@patch("evid.core.label.textpdf_to_typst")
def test_add_evidence_local_pdf_with_label(mock_textpdf, mock_run, mock_gen, temp_dir):
    pdf_path = temp_dir / "test.pdf"
    pdf_path.write_bytes(MINIMAL_PDF)
    dataset = "dataset1"
    (temp_dir / dataset).mkdir()

    def textpdf_side_effect(pdfname, outputfile):
        if outputfile:
            outputfile.write_text("dummy typst content")
        return "dummy typst content"

    mock_textpdf.side_effect = textpdf_side_effect
    add_evidence(temp_dir, dataset, str(pdf_path), label=True)
    unique_dirs = list((temp_dir / dataset).iterdir())
    assert len(unique_dirs) == 1
    label_file = unique_dirs[0] / "label.typ"
    assert label_file.exists()
    mock_run.assert_called_with([CONFIG["editor"], str(label_file)], check=True)
    mock_gen.assert_called_with(label_file)


def test_add_evidence_custom_directory(temp_dir):
    pdf_path = temp_dir / "test.pdf"
    pdf_path.write_bytes(MINIMAL_PDF)
    dataset = "dataset1"
    (temp_dir / dataset).mkdir()
    add_evidence(temp_dir, dataset, str(pdf_path))
    unique_dirs = list((temp_dir / dataset).iterdir())
    assert len(unique_dirs) == 1
    assert (unique_dirs[0] / "test.pdf").exists()
    assert (unique_dirs[0] / "info.yml").exists()


@patch("evid.core.bibtex.subprocess.run")
def test_generate_bibtex_multiple_typ_sequential(mock_run, temp_dir):
    dataset_dir = temp_dir / "test_dataset"
    dataset_dir.mkdir()
    typ_files = []
    for i in range(1, 4):
        uuid_dir = dataset_dir / f"uuid{i}"
        uuid_dir.mkdir()
        typ_file = uuid_dir / "label.typ"
        typ_files.append(typ_file)
        if i == 3:
            typ_file.write_text("")  # empty
        else:
            typ_file.write_text("content")

    def side_effect(*args, **kwargs):
        if args[0][0] == "typst":
            json_file_obj = kwargs["stdout"]
            json_file_obj.write(
                json.dumps(
                    [
                        {
                            "value": {
                                "key": "test_label",
                                "text": "Test quote",
                                "title": "Section 1",
                                "date": "2023-01-01",
                                "opage": 1,
                                "note": "Test note",
                            }
                        }
                    ]
                )
            )
            json_file_obj.flush()
            mock_result = MagicMock(returncode=0, stderr=b"")
            mock_result.args = args[0]
            return mock_result
        return MagicMock(returncode=0)

    mock_run.side_effect = side_effect
    generate_bibtex(typ_files)
    for i in range(1, 3):
        bib_file = dataset_dir / f"uuid{i}" / "label.bib"
        assert bib_file.exists()
    empty_bib = dataset_dir / "uuid3" / "label.bib"
    assert not empty_bib.exists()


def test_generate_bibtex_nonexistent_typ(temp_dir):
    typ_files = [temp_dir / "nonexistent1.typ", temp_dir / "nonexistent2.typ"]
    with patch("sys.stdout", new_callable=MagicMock()):
        generate_bibtex(typ_files)
    # Assertions on logged errors can be added if needed
