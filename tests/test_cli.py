import pytest
from unittest.mock import patch
from pathlib import Path
from evid.cli import get_datasets, select_dataset, add_evidence
import yaml

@pytest.fixture
def temp_dir(tmp_path):
    dataset1 = tmp_path / "dataset1"
    dataset2 = tmp_path / "dataset2"
    dataset1.mkdir()
    dataset2.mkdir()
    return tmp_path

def test_get_datasets(temp_dir):
    datasets = get_datasets(temp_dir)
    assert sorted(datasets) == ["dataset1", "dataset2"]

@patch("builtins.input", side_effect=["1"])
def test_select_dataset_existing(mock_input, temp_dir):
    dataset = select_dataset(temp_dir)
    assert dataset in ["dataset1", "dataset2"]

@patch("builtins.input", side_effect=["3", "new_dataset"])
def test_select_dataset_create_new(mock_input, temp_dir):
    dataset = select_dataset(temp_dir)
    assert dataset == "new_dataset"
    assert (temp_dir / "new_dataset").exists()

def test_add_evidence_local_pdf(temp_dir, tmp_path):
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")  # Minimal PDF
    add_evidence(temp_dir, "dataset1", str(pdf_path), is_url=False)

    dataset_path = temp_dir / "dataset1"
    uuid_dirs = [d for d in dataset_path.iterdir() if d.is_dir()]
    assert len(uuid_dirs) == 1
    uuid_dir = uuid_dirs[0]
    assert (uuid_dir / "test.pdf").exists()
    assert (uuid_dir / "info.yml").exists()

    with (uuid_dir / "info.yml").open("r") as f:
        info = yaml.safe_load(f)
        assert info["original_name"] == "test.pdf"
        assert info["title"] == "test"
        assert info["label"] == "test"
