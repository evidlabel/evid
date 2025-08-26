import pytest
from evid.core.database import Database
import yaml
from pathlib import Path

@pytest.fixture
def temp_db(tmp_path):
    dataset = tmp_path / "test_ds"
    dataset.mkdir()
    uuid_dir = dataset / "uuid1"
    uuid_dir.mkdir()
    info_path = uuid_dir / "info.yml"
    info_data = {
        "original_name": "test.pdf",
        "uuid": "uuid1",
        "time_added": "2023-01-01",
        "dates": "2023-01-01",
        "title": "Test",
        "authors": "Author",
        "tags": "",
        "label": "test",
        "url": ""
    }
    info_path.write_text(yaml.dump(info_data))
    return tmp_path, ["test_ds"]

def test_database_init(temp_db):
    tmp_path, datasets = temp_db
    db = Database(tmp_path, datasets)
    assert "test_ds" in db.db
    assert "Test uuid1" in db.db["test_ds"]

def test_get_filenames(temp_db):
    tmp_path, datasets = temp_db
    db = Database(tmp_path, datasets)
    assert db.get_filenames() == ["test.pdf"]
