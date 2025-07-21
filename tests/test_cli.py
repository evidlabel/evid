import pytest
from unittest.mock import patch
from evid.cli.dataset import get_datasets, select_dataset, create_dataset
from evid.cli.evidence import add_evidence
from evid.core.bibtex import generate_bibtex
import yaml
import fitz  # Added for creating valid PDFs

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

@patch("subprocess.run")
def test_add_evidence_local_pdf_with_label(mock_run, temp_dir, tmp_path):
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
    assert (uuid_dir / "label.tex").exists()  # Check label.tex created

    with (uuid_dir / "info.yml").open("r") as f:
        info = yaml.safe_load(f)
        assert info["original_name"] == "test.pdf"
        assert info["title"] == "test"
        assert info["label"] == "test"

    with (uuid_dir / "label.tex").open("r") as f:
        content = f.read()
        assert "Test content" in content  # Check generated content

    mock_run.assert_called_once_with(
        ["code", str(uuid_dir / "label.tex")], check=True
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
def setup_bibtex_csvs(tmp_path):
    dataset_path = tmp_path / "test_dataset"
    entry1 = dataset_path / "uuid1"
    entry2 = dataset_path / "uuid2"
    entry3 = dataset_path / "uuid3"
    entry1.mkdir(parents=True)
    entry2.mkdir(parents=True)
    entry3.mkdir(parents=True)

    csv_data = "label ; quote ; note ; section title ; section no ; page ; date ; opage\n" \
               "test_label ; Test quote ; Test note ; Section 1 ; 1 ; 1 ; 2023-01-01 ; 0"
    csv_path1 = entry1 / "label.csv"
    csv_path2 = entry2 / "label.csv"
    with csv_path1.open("w", encoding="utf-8") as f:
        f.write(csv_data)
    with csv_path2.open("w", encoding="utf-8") as f:
        f.write(csv_data)

    csv_path3 = entry3 / "label.csv"
    csv_path3.write_text("", encoding="utf-8")

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

    return [csv_path1, csv_path2, csv_path3]

def test_generate_bibtex_multiple_csv_sequential(setup_bibtex_csvs, capsys):
    csv_paths = setup_bibtex_csvs
    generate_bibtex(csv_paths, parallel=False)

    for csv_path in csv_paths[:2]:
        bib_file = csv_path.parent / "label_table.bib"
        assert bib_file.exists()
        with bib_file.open("r", encoding="utf-8") as f:
            content = f.read()
            assert "@article" in content
            assert "nonote = {Test note}" in content
            assert "title = {Test quote}" in content
            assert "date = {2023-01-01}" in content

    captured = capsys.readouterr()
    assert "Successfully generated 2 BibTeX files." in captured.out
    assert "Skipped empty CSV file" in captured.out

def test_generate_bibtex_nonexistent_csv(tmp_path, capsys):
    csv_paths = [tmp_path / "nonexistent1.csv", tmp_path / "nonexistent2.csv"]
    generate_bibtex(csv_paths)
    captured = capsys.readouterr()
    assert "Successfully generated 0 BibTeX files." in captured.out
    assert "CSV file" in captured.out
    assert "does not exist" in captured.out
    for csv_path in csv_paths:
        assert f"CSV file '{csv_path}' does not exist." in captured.out
