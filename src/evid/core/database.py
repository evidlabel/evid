import yaml
from pathlib import Path
from typing import Dict, List
from evid import DEFAULT_DIR

class Database:
    def __init__(self, db_path: Path = DEFAULT_DIR, datasets: List[str] = None):
        self.db: Dict[str, Dict] = {}
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
                        key = f"{entry.get('title', '')} {entry['uuid']}"
                        self.db[dataset][key] = entry
                except Exception:
                    continue

    def get_filenames(self) -> List[str]:
        return [entry["original_name"] for dataset in self.db.values() for entry in dataset.values() if "original_name" in entry]
