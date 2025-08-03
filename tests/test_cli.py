import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys
import logging

from evid.cli.dataset import get_datasets, select_dataset, create_dataset
from evid.cli.evidence import add_evidence
from evid.core.bibtex import generate_bibtex
import yaml
import fitz
import json

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

def test_create_dataset(temp_dir):
    dataset_name = "new_dataset"
    create_dataset(temp_dir, dataset_name)
    assert (temp_dir / dataset_name).exists()

@patch("evid.core.label.generate_bib_from_typ", return_value=(True, ""))
@patch("subprocess.run")
def test_add_evidence_local_pdf_with_label(mock_run, mock_bib, temp_dir, tmp_path):
    pdf_path = tmp_path / "test.pdf"
    # Create a valid PDF using fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((100, 100), "Test content")
    doc.save(str(pdf_path))
    doc.close()

    add_evidence(temp_dir, "dataset1", str(pdf_path), label=True)

    dataset_path = temp_dir / "dataset1"
    uuid_dirs = [d for d in dataset_path.iterdir() if d.is_dir()]
    assert len(uuid_dirs) == 1
    uuid_dir = uuid_dirs[0]
    assert (uuid_dir / "test.pdf").exists()
    assert (uuid_dir / "info.yml").exists()
    assert (uuid_dir / "label.typ").exists()  # Check label.typ created

    with (uuid_dir / "info.yml").open("r") as f:
        info = yaml.safe_load(f)
        assert info["original_name"] == "test.pdf"
        assert info["title"] == "test"
        assert info["label"] == "test"

    with (uuid_dir / "label.typ").open("r") as f:
        content = f.read()
        assert "Test content" in content  # Check generated content

    mock_run.assert_called_once_with(
        ["code", str(uuid_dir / "label.typ")], check=True
    )

def test_add_evidence_custom_directory(tmp_path, tmp_path_factory):
    custom_dir = tmp_path_factory.mktemp("custom_evid_db")
    pdf_path = tmp_path / "test.pdf"
    # Create a valid PDF using fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((100, 100), "Test content")
    doc.save(str(pdf_path))
    doc.close()

    add_evidence(custom_dir, "dataset1", str(pdf_path))

    dataset_path = custom_dir / "dataset1"
    assert dataset_path.exists()
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

@pytest.fixture
def setup_bibtex_typs(tmp_path):
    dataset_path = tmp_path / "test_dataset"
    entry1 = dataset_path / "uuid1"
    entry2 = dataset_path / "uuid2"
    entry3 = dataset_path / "uuid3"
    entry1.mkdir(parents=True)
    entry2.mkdir(parents=True)
    entry3.mkdir(parents=True)

    typ_data = """#import "@local/labtyp:0.1.0": lablist, lab, mset

#mset(values: (title: "Test Title", date: "2023-01-01"))

= Test Title

Test content

= List of Labels
#lablist()
"""
    typ_path1 = entry1 / "label.typ"
    typ_path2 = entry2 / "label.typ"
    with typ_path1.open("w", encoding="utf-8") as f:
        f.write(typ_data)
    with typ_path2.open("w", encoding="utf-8") as f:
        f.write(typ_data)

    typ_path3 = entry3 / "label.typ"
    typ_path3.write_text("", encoding="utf-8")

    info_data = {
        "original_name": "doc.pdf",
        "uuid": "uuid1",
        "time_added": "2023-01-01",
        "dates": "2023-01-01",
        "title": "Doc1",
        "authors": "Author1",
        "tags": "",
        "label": "doc1",
        "url": "http://example.com"
    }
    with (entry1 / "info.yml").open("w", encoding="utf-8") as f:
        yaml.dump(info_data, f)
    info_data["uuid"] = "uuid2"
    info_data["title"] = "Doc2"
    info_data["authors"] = "Author2"
    info_data["label"] = "doc2"
    with (entry2 / "info.yml").open("w", encoding="utf-8") as f:
        yaml.dump(info_data, f)
    info_data["uuid"] = "uuid3"
    info_data["title"] = "Doc3"
    info_data["authors"] = "Author3"
    info_data["label"] = "doc3"
    with (entry3 / "info.yml").open("w", encoding="utf-8") as f:
        yaml.dump(info_data, f)

    return [typ_path1, typ_path2, typ_path3]

@patch("subprocess.run")
def test_generate_bibtex_multiple_typ_sequential(mock_run, setup_bibtex_typs, capsys):
    def side_effect(*args, **kwargs):
        if "stdout" in kwargs:
            stdout_file = kwargs["stdout"]
            typ_file = Path(args[0][2])
            if typ_file.stat().st_size > 0:
                json_content = json.dumps([{"value": {"key": "test_label", "text": "Test quote", "date": "2023-01-01", "opage": 1, "title": "Test Title", "note": "Test note"}}])
                stdout_file.write(json_content)
            else:
                stdout_file.write('[]')
            stdout_file.close()
        return MagicMock(returncode=0, stderr=b"")

    mock_run.side_effect = side_effect

    typ_paths = setup_bibtex_typs
    generate_bibtex(typ_paths, parallel=False)

    for typ_path in typ_paths[:2]:
        bib_file = typ_path.parent / "label.bib"
        assert bib_file.exists()
        with bib_file.open("r", encoding="utf-8") as f:
            content = f.read()
            assert "@article" in content

    captured = capsys.readouterr()
    assert "Successfully generated 2 BibTeX files." in captured.out
    assert "Encountered 1 issues:" in captured.out
    assert "Skipped empty Typst file" in captured.out

def test_generate_bibtex_nonexistent_typ(tmp_path, capsys):
    typ_paths = [tmp_path / "nonexistent1.typ", tmp_path / "nonexistent2.typ"]
    generate_bibtex(typ_paths)
    captured = capsys.readouterr()
    assert "Successfully generated 0 BibTeX files." in captured.out
    assert "Encountered 2 issues:" in captured.out
    assert "Typst file" in captured.out
    assert "does not exist" in captured.out
    for typ_path in typ_paths:
        assert f"Typst file '{typ_path}' does not exist." in captured.out


