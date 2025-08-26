import pytest
from unittest.mock import patch
from evid.cli.dataset import get_datasets, list_datasets, select_dataset, create_dataset, track_dataset
from pathlib import Path
import sys

@pytest.fixture
def temp_dir(tmp_path):
    return tmp_path

def test_get_datasets(temp_dir):
    (temp_dir / "ds1").mkdir()
    (temp_dir / "ds2").mkdir()
    assert sorted(get_datasets(temp_dir)) == ["ds1", "ds2"]

def test_list_datasets(temp_dir, capsys):
    (temp_dir / "ds1").mkdir()
    (temp_dir / "ds2").mkdir()
    list_datasets(temp_dir)
    captured = capsys.readouterr()
    assert "Available datasets" in captured.out
    assert "ds1" in captured.out
    assert "ds2" in captured.out

def test_select_dataset_no_datasets_allow_create(temp_dir):
    with patch("builtins.input", return_value="new_ds"):
        ds = select_dataset(temp_dir)
        assert ds == "new_ds"
        assert (temp_dir / "new_ds").exists()

def test_select_dataset_existing(temp_dir):
    (temp_dir / "ds1").mkdir()
    (temp_dir / "ds2").mkdir()
    with patch("builtins.input", return_value="1"):
        ds = select_dataset(temp_dir)
        assert ds == "ds1"

def test_create_dataset(temp_dir):
    create_dataset(temp_dir, "new_ds")
    assert (temp_dir / "new_ds").exists()

def test_track_dataset(temp_dir):
    (temp_dir / "ds1").mkdir()
    with patch("evid.cli.dataset.Repo") as mock_repo:
        track_dataset(temp_dir, "ds1")
        mock_repo.init.assert_called_with(temp_dir / "ds1")
