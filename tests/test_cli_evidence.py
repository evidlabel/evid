import pytest
from unittest.mock import patch
from evid.cli.evidence import (
    add_evidence,
    get_evidence_list,
    select_evidence,
    label_evidence,
)
import yaml

MINIMAL_PDF = b"%PDF-1.0\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 3 3]>>endobj xref 0 4\n0000000000 65535 f\n0000000010 00000 n\n0000000053 00000 n\n0000000102 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref 149 %%EOF"


@pytest.fixture
def temp_dir(tmp_path):
    return tmp_path


def test_add_evidence_local_pdf(temp_dir):
    pdf_path = temp_dir / "test.pdf"
    pdf_path.write_bytes(MINIMAL_PDF)
    dataset = "test_ds"
    (temp_dir / dataset).mkdir()
    with patch("sys.stdout"):
        add_evidence(temp_dir, dataset, str(pdf_path))
    unique_dirs = list((temp_dir / dataset).iterdir())
    assert len(unique_dirs) == 1
    assert (unique_dirs[0] / "test.pdf").exists()
    assert (unique_dirs[0] / "info.yml").exists()


def test_get_evidence_list(temp_dir):
    dataset = "test_ds"
    (temp_dir / dataset).mkdir()
    uuid_dir = temp_dir / dataset / "uuid1"
    uuid_dir.mkdir()
    info_path = uuid_dir / "info.yml"
    info_data = {
        "original_name": "test.pdf",
        "uuid": "uuid1",
        "time_added": "2023-01-01",
        "dates": "2023-01-01",
        "title": "Test Doc",
        "authors": "Author",
        "tags": "",
        "label": "test_doc",
        "url": "",
    }
    info_path.write_text(yaml.dump(info_data))
    evidences = get_evidence_list(temp_dir, dataset)
    assert len(evidences) == 1
    assert evidences[0]["title"] == "Test Doc"


def test_select_evidence(temp_dir):
    dataset = "test_ds"
    (temp_dir / dataset).mkdir()
    uuid_dir = temp_dir / dataset / "uuid1"
    uuid_dir.mkdir()
    info_path = uuid_dir / "info.yml"
    info_data = {
        "original_name": "test.pdf",
        "uuid": "uuid1",
        "time_added": "2023-01-01",
        "dates": "2023-01-01",
        "title": "Test Doc",
        "authors": "Author",
        "tags": "",
        "label": "test_doc",
        "url": "",
    }
    info_path.write_text(yaml.dump(info_data))
    with patch("builtins.input", return_value="1"):
        uuid = select_evidence(temp_dir, dataset)
        assert uuid == "uuid1"


def test_label_evidence(temp_dir):
    dataset = "test_ds"
    uuid = "uuid1"
    workdir = temp_dir / dataset / uuid
    workdir.mkdir(parents=True)
    pdf_path = workdir / "test.pdf"
    pdf_path.touch()
    with patch("evid.cli.evidence.create_label") as mock_create:
        label_evidence(temp_dir, dataset, uuid)
        mock_create.assert_called_with(pdf_path, dataset, uuid)
