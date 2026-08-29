"""Unified document tagging — keeps TagService (tags.yml) and info.yml in sync."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from evid.models import TagItem
from evid.services.tag_service import TagService

logger = logging.getLogger(__name__)


def parse_tags_field(raw: str | None) -> list[str]:
    """Split a comma-separated tags field into a sorted, deduplicated list."""
    if not raw:
        return []
    return sorted({t.strip() for t in str(raw).split(",") if t.strip()})


def format_tags_field(tags: list[str]) -> str:
    return ", ".join(sorted(tags))


def resolve_doc_pdf(doc_dir: Path) -> Path | None:
    """Return the primary PDF for a document directory, if any exists."""
    info_path = doc_dir / "info.yml"
    if info_path.exists():
        try:
            with info_path.open(encoding="utf-8") as f:
                info = yaml.safe_load(f) or {}
            name = info.get("original_name") or info.get("original_filename")
            if name:
                candidate = doc_dir / name
                if candidate.is_file():
                    return candidate
        except Exception:
            logger.debug(
                "Could not read original_name from %s", info_path, exc_info=True
            )

    original = doc_dir / "original.pdf"
    if original.is_file():
        return original

    pdfs = sorted(doc_dir.glob("*.pdf"))
    return pdfs[0] if pdfs else None


def _read_info_tags(info_path: Path) -> list[str]:
    if not info_path.exists():
        return []
    with info_path.open(encoding="utf-8") as f:
        info = yaml.safe_load(f) or {}
    return parse_tags_field(info.get("tags", ""))


def _write_info_tags(info_path: Path, tags: list[str]) -> None:
    info: dict = {}
    if info_path.exists():
        with info_path.open(encoding="utf-8") as f:
            info = yaml.safe_load(f) or {}
    info["tags"] = format_tags_field(tags)
    with info_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(info, f, allow_unicode=True)


def assign_doc_tag(
    tag_service: TagService,
    set_slug: str,
    doc_uuid: str,
    info_path: Path,
    tag_name: str,
) -> bool:
    """Add *tag_name* to TagService and info.yml. Returns True if newly added."""
    tag_name = tag_name.strip()
    if not tag_name:
        return False

    try:
        tag_service.get_tag(tag_name)
    except KeyError:
        tag_service.create_tag(tag_name, set_slug)

    tag_service.add_items(tag_name, [TagItem(set_slug=set_slug, doc_uuid=doc_uuid)])

    existing = _read_info_tags(info_path)
    if tag_name in existing:
        return False
    existing.append(tag_name)
    try:
        _write_info_tags(info_path, existing)
    except Exception:
        logger.exception("Failed to update info.yml tags for %s", doc_uuid)
        raise
    return True


def remove_doc_tag(
    tag_service: TagService,
    set_slug: str,
    doc_uuid: str,
    info_path: Path,
    tag_name: str,
) -> bool:
    """Remove *tag_name* from TagService and info.yml. Returns True if removed."""
    tag_name = tag_name.strip()
    if not tag_name:
        return False

    try:
        tag_service.remove_item(tag_name, set_slug, doc_uuid)
    except Exception:
        logger.debug("Tag %s not in TagService for %s/%s", tag_name, set_slug, doc_uuid)

    existing = _read_info_tags(info_path)
    if tag_name not in existing:
        return False
    existing.remove(tag_name)
    try:
        _write_info_tags(info_path, existing)
    except Exception:
        logger.exception("Failed to remove tag from info.yml for %s", doc_uuid)
        raise
    return True
