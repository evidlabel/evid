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

    with (entry1 / "info.yml").open("w") as f:
        yaml.dump({"title": "Doc1", "uuid": "uuid1", "original_name": "doc1.pdf"}, f)
    with (entry2 / "info.yml").open("w") as f:
        yaml.dump({"title": "Doc2", "uuid": "uuid2", "original_name": "doc2.pdf"}, f)

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
