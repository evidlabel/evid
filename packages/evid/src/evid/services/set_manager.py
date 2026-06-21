"""SetManager — CRUD for evidence sets stored under data_dir/sets/."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import yaml
from slugify import slugify

from evid.models import EvidenceSet, SetType

logger = logging.getLogger(__name__)


class SetManager:
    def __init__(self, data_dir: Path) -> None:
        self.sets_dir = data_dir / "sets"
        self.sets_dir.mkdir(parents=True, exist_ok=True)

    # ── read ─────────────────────────────────────────────────────────────────

    def list_sets(self) -> list[EvidenceSet]:
        sets = []
        for set_dir in sorted(self.sets_dir.iterdir()):
            yml = set_dir / "set.yml"
            if set_dir.is_dir() and yml.exists():
                try:
                    sets.append(self._load_set_yml(set_dir))
                except Exception:
                    logger.exception("Failed to load set at %s", set_dir)
        return sets

    def load_set(self, slug: str) -> EvidenceSet:
        set_dir = self.sets_dir / slug
        if not set_dir.exists():
            msg = f"Set '{slug}' not found"
            raise FileNotFoundError(msg)
        return self._load_set_yml(set_dir)

    # ── write ─────────────────────────────────────────────────────────────────

    def create_set(
        self,
        name: str,
        set_type: SetType | str = SetType.NORMAL,
        description: str = "",
    ) -> EvidenceSet:
        slug = slugify(name)
        set_dir = self.sets_dir / slug
        if set_dir.exists():
            msg = f"Set '{slug}' already exists"
            raise FileExistsError(msg)
        set_dir.mkdir(parents=True)
        (set_dir / "docs").mkdir()
        (set_dir / "vecdb").mkdir()

        created = datetime.now(tz=UTC)
        data = {
            "name": name,
            "slug": slug,
            "type": str(SetType(set_type).value),
            "created": created.isoformat(),
            "description": description,
        }
        with (set_dir / "set.yml").open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True)

        logger.info("Created set '%s' (%s) at %s", name, set_type, set_dir)
        return EvidenceSet(
            name=name,
            slug=slug,
            path=set_dir,
            set_type=SetType(set_type),
            created=created,
            description=description,
        )

    def delete_set(self, slug: str) -> None:
        import shutil

        set_dir = self.sets_dir / slug
        if not set_dir.exists():
            msg = f"Set '{slug}' not found"
            raise FileNotFoundError(msg)
        shutil.rmtree(set_dir)
        logger.info("Deleted set '%s'", slug)

    def update_set_meta(self, slug: str, **kwargs: object) -> EvidenceSet:
        """Update name, description, or set_type in set.yml."""
        set_dir = self.sets_dir / slug
        yml_path = set_dir / "set.yml"
        with yml_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        allowed = {"name", "description", "set_type"}
        for k, v in kwargs.items():
            if k in allowed:
                # set_type is stored under "type" key to match create_set / _load_set_yml
                data["type" if k == "set_type" else k] = v
        with yml_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True)
        return self._load_set_yml(set_dir)

    # ── documents ─────────────────────────────────────────────────────────────

    def list_documents(self, slug: str) -> list[Path]:
        """Return doc UUID paths for a set (unsorted)."""
        docs_dir = self.sets_dir / slug / "docs"
        if not docs_dir.exists():
            return []
        return [d for d in docs_dir.iterdir() if d.is_dir()]

    # ── internal ──────────────────────────────────────────────────────────────

    def _load_set_yml(self, set_dir: Path) -> EvidenceSet:
        with (set_dir / "set.yml").open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        created = data.get("created")
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        return EvidenceSet(
            name=data["name"],
            slug=data["slug"],
            path=set_dir,
            set_type=SetType(data.get("type", "normal")),
            created=created,
            description=data.get("description", ""),
        )
