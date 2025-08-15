import pytest
import yaml
from evid.core.database import Database


@pytest.fixture
def temp_dataset(tmp_path):
    dataset_path = tmp_path / "dataset"
    entry1 = dataset_path / "uuid1"
    entry2 = dataset_path / "uuid2"
    entry1.mkdir(parents=True)
    entry2.mkdir(parents=True)

    info_data = {
        "original_name": "doc1.pdf",
        "uuid": "uuid1",
        "time_added": "2023-01-01",
        "dates": "2023-01-01",
        "title": "Doc1",
        "authors": "Author1",
        "tags": "",
        "label": "doc1",
        "url": ""
    }
    with (entry1 / "info.yml").open("w") as f:
        yaml.dump(info_data, f)
    info_data["uuid"] = "uuid2"
    info_data["original_name"] = "doc2.pdf"
    info_data["title"] = "Doc2"
    info_data["authors"] = "Author2"
    info_data["label"] = "doc2"
    with (entry2 / "info.yml").open("w") as f:
        yaml.dump(info_data, f)

    yield tmp_path, ["dataset"]


def test_database_init_and_filenames(temp_dataset):
    db_path, datasets = temp_dataset
    db = Database(db_path, datasets)

    assert "dataset" in db.db
    assert len(db.db["dataset"]) == 2
    assert "Doc1 uuid1" in db.db["dataset"]
    assert "Doc2 uuid2" in db.db["dataset"]

    filenames = db.get_filenames()
    assert sorted(filenames) == ["doc1.pdf", "doc2.pdf"]


def test_database_with_invalid_entry(tmp_path):
    dataset_path = tmp_path / "dataset"
    entry = dataset_path / "uuid"
    entry.mkdir(parents=True)

    with (entry / "info.yml").open("w") as f:
        f.write("invalid: yaml: here")  # Valid YAML but not a complete entry

    db = Database(tmp_path, ["dataset"])
    assert "dataset" in db.db
    assert len(db.db["dataset"]) == 0  # Invalid entry skipped

