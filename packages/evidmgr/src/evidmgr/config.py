"""evidmgr configuration — reads/writes ~/.local/share/evidmgr/evidmgr.yml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class EvidmgrConfig(BaseModel):
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".local" / "share" / "evidmgr")
    editor: str = "code"
    default_language: str = "da"

    @classmethod
    def load(cls, path: Path | None = None) -> "EvidmgrConfig":
        config_path = path or (Path.home() / ".local" / "share" / "evidmgr" / "evidmgr.yml")
        if config_path.exists():
            with config_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return cls(**data)
        return cls()

    def save(self, path: Path | None = None) -> None:
        config_path = path or (self.data_dir / "evidmgr.yml")
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
