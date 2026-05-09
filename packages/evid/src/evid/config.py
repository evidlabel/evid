"""evid configuration — reads/writes ~/.local/share/evid/evid.yml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class EvidConfig(BaseModel):
    data_dir: Path = Field(
        default_factory=lambda: Path.home() / ".local" / "share" / "evid"
    )
    editor: str = "code"
    default_language: str = "da"

    @classmethod
    def load(cls, path: Path | None = None) -> EvidConfig:
        new_path = Path.home() / ".local" / "share" / "evid" / "evid.yml"
        legacy_path = Path.home() / ".local" / "share" / "evidmgr" / "evidmgr.yml"
        config_path = path or (new_path if new_path.exists() else legacy_path)
        if config_path.exists():
            with config_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            # Migrate legacy data_dir to new default if not explicitly set
            if "data_dir" not in data:
                legacy_data = Path.home() / ".local" / "share" / "evidmgr"
                if legacy_data.exists():
                    data["data_dir"] = str(legacy_data)
            return cls(**data)
        # No config yet — fall back to legacy data dir if it exists
        legacy_data = Path.home() / ".local" / "share" / "evidmgr"
        if legacy_data.exists():
            return cls(data_dir=legacy_data)
        return cls()

    def save(self, path: Path | None = None) -> None:
        config_path = path or (self.data_dir / "evid.yml")
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                {
                    "data_dir": str(self.data_dir),
                    "editor": self.editor,
                    "default_language": self.default_language,
                },
                f,
                allow_unicode=True,
            )
