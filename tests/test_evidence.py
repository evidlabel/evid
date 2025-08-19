import pytest
import hashlib
import uuid
from evid.cli.evidence import add_evidence


@pytest.fixture
def temp_directory(tmp_path):
    return tmp_path


@pytest.fixture
def sample_pdf_content():
    return b"%PDF-1.0\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 3 3]>>endobj xref 0 4\n0000000000 65535 f\n0000000010 00000 n\n0000000053 00000 n\n0000000102 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref 149 %EOF"


def test_add_duplicate_evidence(temp_directory, sample_pdf_content, capsys):
    dataset = "test_dataset"
    source_path = temp_directory / "sample.pdf"
    with open(source_path, "wb") as f:
        f.write(sample_pdf_content)

    # First add
    add_evidence(temp_directory, dataset, str(source_path))

    # Check that directory was created
    digest = hashlib.sha256(sample_pdf_content).digest()[:16]
    unique_id = uuid.UUID(bytes=digest).hex
    unique_dir = temp_directory / dataset / unique_id
    assert unique_dir.exists()
    assert (unique_dir / "sample.pdf").exists()
    assert (unique_dir / "info.yml").exists()

    # Second add (duplicate)
    add_evidence(temp_directory, dataset, str(source_path))
    captured = capsys.readouterr()
    assert f"This document is already added in {dataset} at {unique_id}" in captured.out

    # Verify no new directory created, still only one
    assert len(list((temp_directory / dataset).iterdir())) == 1
