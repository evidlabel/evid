"""TagService — cross-set tag registry stored in tags.yml."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import yaml

from evid.models import Tag, TagItem

logger = logging.getLogger(__name__)


class TagService:
    def __init__(self, data_dir: Path) -> None:
        self.tags_path = data_dir / "tags.yml"

    # ── read ──────────────────────────────────────────────────────────────────

    def list_tags(self, owner_set: str | None = None) -> list[Tag]:
        tags = self._load_all()
        if owner_set:
            return [t for t in tags if t.owner_set == owner_set]
        return tags

    def get_tag(self, name: str) -> Tag:
        for tag in self._load_all():
            if tag.name == name:
                return tag
        msg = f"Tag '{name}' not found"
        raise KeyError(msg)

    # ── write ─────────────────────────────────────────────────────────────────

    def create_tag(self, name: str, owner_set: str) -> Tag:
        tags = self._load_all()
        if any(t.name == name for t in tags):
            msg = f"Tag '{name}' already exists"
            raise ValueError(msg)
        tag = Tag(name=name, owner_set=owner_set, created=datetime.now(tz=UTC))
        tags.append(tag)
        self._save_all(tags)
        return tag

    def add_items(self, tag_name: str, items: list[TagItem]) -> None:
        tags = self._load_all()
        tag = next((t for t in tags if t.name == tag_name), None)
        if tag is None:
            msg = f"Tag '{tag_name}' not found"
            raise KeyError(msg)
        existing_keys = {(i.set_slug, i.doc_uuid) for i in tag.items}
        for item in items:
            if (item.set_slug, item.doc_uuid) not in existing_keys:
                tag.items.append(item)
                existing_keys.add((item.set_slug, item.doc_uuid))
        self._save_all(tags)

    def remove_item(self, tag_name: str, set_slug: str, doc_uuid: str) -> None:
        tags = self._load_all()
        tag = next((t for t in tags if t.name == tag_name), None)
        if tag is None:
            return
        tag.items = [
            i
            for i in tag.items
            if not (i.set_slug == set_slug and i.doc_uuid == doc_uuid)
        ]
        self._save_all(tags)

    def delete_tag(self, tag_name: str) -> None:
        tags = [t for t in self._load_all() if t.name != tag_name]
        self._save_all(tags)

    # ── tag naming helper ─────────────────────────────────────────────────────

    @staticmethod
    def qualify(name: str, active_set_slug: str) -> str:
        """If *name* has no dot, prefix with *active_set_slug*."""
        return name if "." in name else f"{active_set_slug}.{name}"

    # ── internal ──────────────────────────────────────────────────────────────

    def _load_all(self) -> list[Tag]:
        if not self.tags_path.exists():
            return []
        with self.tags_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or []

        tags = []
        for entry in raw:
            created = entry.get("created")
            if isinstance(created, str):
                created = datetime.fromisoformat(created)
            items = [
                TagItem(
                    set_slug=i["set"],
                    doc_uuid=i["doc_uuid"],
                    chunks=i.get("chunks"),
                )
                for i in entry.get("items", [])
            ]
            tags.append(
                Tag(
                    name=entry["name"],
                    owner_set=entry["owner_set"],
                    created=created or datetime.now(tz=UTC),
                    items=items,
                )
            )
        return tags

    def _save_all(self, tags: list[Tag]) -> None:
        self.tags_path.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {
                "name": t.name,
                "owner_set": t.owner_set,
                "created": t.created.isoformat(),
                "items": [
                    {
                        "set": i.set_slug,
                        "doc_uuid": i.doc_uuid,
                        "chunks": i.chunks,
                    }
                    for i in t.items
                ],
            }
            for t in tags
        ]
        with self.tags_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
