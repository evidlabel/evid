"""Database handling for evid."""

from pathlib import Path

import yaml

from evid import DEFAULT_DIR
from evid.core.models import InfoModel  # Added for validation


class Database:
    def __init__(self, db_path: Path = DEFAULT_DIR, datasets: list[str] = None):
        self.db: dict[str, dict] = {}
        if datasets is None:
            datasets = [
                d.name
                for d in db_path.iterdir()
                if d.is_dir() and not d.name.startswith(".")
            ]
        for dataset in datasets:
            self.db[dataset] = {}
            for info_file in db_path.glob(f"{dataset}/**/info.yml"):
                try:
                    with info_file.open() as f:
                        entry = yaml.safe_load(f)
                        validated_entry = InfoModel(**entry)
                        entry = validated_entry.model_dump()
                        # Store the real doc directory so resolve_uuid doesn't
                        # have to guess the path layout (old: dataset/uuid/,
                        # new: dataset/docs/uuid/).
                        entry["_workdir"] = str(info_file.parent)
                        key = f"{entry.get('title', '')} {entry['uuid']}"
                        self.db[dataset][key] = entry
                except ValueError:
                    continue
                except Exception:
                    continue

    def get_filenames(self) -> list[str]:
        return [
            entry["original_name"]
            for dataset in self.db.values()
            for entry in dataset.values()
            if "original_name" in entry
        ]
