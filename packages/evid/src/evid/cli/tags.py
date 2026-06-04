"""Tag management helpers for evid datasets."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import bibtexparser as btp
import yaml

from evid.core.models import InfoModel

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

logger = logging.getLogger(__name__)


def iter_docs(
    directory: Path, dataset: str | None = None
) -> Generator[tuple[str, Path, InfoModel], None, None]:
    """Yield (slug, uuid_dir, InfoModel) for every doc with a valid info.yml.

    If *dataset* is given only that dataset's docs directory is scanned;
    otherwise every dataset under ``directory/sets/`` is scanned.
    """
    sets_dir = directory / "sets"
    if not sets_dir.exists():
        return

    if dataset:
        slugs = [dataset]
    else:
        slugs = [
            d.name
            for d in sorted(sets_dir.iterdir())
            if d.is_dir() and (d / "set.yml").exists()
        ]

    for slug in slugs:
        docs_dir = sets_dir / slug / "docs"
        if not docs_dir.is_dir():
            continue
        for uuid_dir in sorted(docs_dir.iterdir()):
            if not uuid_dir.is_dir():
                continue
            info_file = uuid_dir / "info.yml"
            if not info_file.exists():
                continue
            try:
                with info_file.open(encoding="utf-8") as fh:
                    raw = yaml.safe_load(fh)
                info = InfoModel(**raw)
            except Exception as exc:
                logger.warning("Skipping %s: %s", uuid_dir, exc)
                continue
            yield slug, uuid_dir, info


def _parse_tags(raw_tags: str) -> list[str]:
    """Split a comma-separated tag string into a sorted, deduplicated list."""
    return sorted({t.strip() for t in raw_tags.split(",") if t.strip()})


def _count_snippets(uuid_dir: Path) -> int:
    """Return the number of non-:main BibTeX entries in label.bib, or 0."""
    bib_file = uuid_dir / "label.bib"
    if not bib_file.exists():
        return 0
    try:
        db = btp.loads(bib_file.read_text(encoding="utf-8"))
        return sum(
            1
            for e in db.entries
            if (e["ID"].split(":", 1)[1] if ":" in e["ID"] else e["ID"]) != "main"
        )
    except Exception:
        return 0


def list_tags(directory: Path, dataset: str | None = None) -> dict[str, dict[str, int]]:
    """Return ``{tag: {"docs": N, "snippets": N}}`` across the given scope.

    Docs with no tags are silently skipped.  Results are unsorted — callers
    should sort as needed.
    """
    result: dict[str, dict[str, int]] = {}
    for _slug, uuid_dir, info in iter_docs(directory, dataset):
        tags = _parse_tags(info.tags)
        if not tags:
            continue
        snippets = _count_snippets(uuid_dir)
        for tag in tags:
            if tag not in result:
                result[tag] = {"docs": 0, "snippets": 0}
            result[tag]["docs"] += 1
            result[tag]["snippets"] += snippets
    return result


def show_tag(
    directory: Path, tag: str, dataset: str | None = None
) -> list[dict[str, str]]:
    """Return docs whose tag list contains *tag* (case-insensitive).

    Each entry is ``{"slug", "uuid", "label", "url", "path", "snippets"}``.
    """
    needle = tag.strip().lower()
    matches: list[dict[str, str]] = []
    for slug, uuid_dir, info in iter_docs(directory, dataset):
        tags = [t.lower() for t in _parse_tags(info.tags)]
        if needle in tags:
            matches.append(
                {
                    "slug": slug,
                    "uuid": info.uuid,
                    "label": info.label,
                    "url": info.url,
                    "path": str(uuid_dir),
                    "snippets": str(_count_snippets(uuid_dir)),
                }
            )
    return matches


def assign_tag(directory: Path, uuid: str, tag: str) -> tuple[bool, str]:
    """Add *tag* to the info.yml for the document matching *uuid*.

    Accepts full UUID or a unique prefix.  Returns ``(True, message)`` on
    success or ``(False, message)`` if the UUID was not found.
    """
    tag = tag.strip()
    if not tag:
        return False, "Tag must not be empty."

    needle = uuid.strip().lower()
    matched: Path | None = None

    for _slug, uuid_dir, info in iter_docs(directory):
        if info.uuid.lower().startswith(needle):
            if matched is not None:
                return False, f"UUID prefix '{uuid}' is ambiguous — be more specific."
            matched = uuid_dir

    if matched is None:
        return False, f"No document found matching UUID '{uuid}'."

    info_file = matched / "info.yml"
    with info_file.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    existing = _parse_tags(str(raw.get("tags", "")))
    if tag.lower() in [t.lower() for t in existing]:
        return True, f"Tag '{tag}' already present on {info_file.parent.name}."

    existing.append(tag)
    raw["tags"] = ", ".join(sorted(existing))

    with info_file.open("w", encoding="utf-8") as fh:
        yaml.dump(raw, fh, allow_unicode=True)

    return True, f"Tag '{tag}' added to {info_file.parent.name}."


def remove_tag(
    directory: Path, tag: str, dataset: str | None = None
) -> tuple[bool, str]:
    """Remove *tag* from every document that carries it.

    Scoped to *dataset* if given, otherwise all datasets.  Returns
    ``(True, message)`` with a count, or ``(False, message)`` if the tag
    was not found on any document.
    """
    tag = tag.strip()
    if not tag:
        return False, "Tag must not be empty."

    lower_tag = tag.lower()
    count = 0

    for _slug, uuid_dir, info in iter_docs(directory, dataset):
        existing = _parse_tags(str(info.tags or ""))
        updated = [t for t in existing if t.lower() != lower_tag]
        if len(updated) == len(existing):
            continue

        info_file = uuid_dir / "info.yml"
        with info_file.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        raw["tags"] = ", ".join(sorted(updated))
        with info_file.open("w", encoding="utf-8") as fh:
            yaml.dump(raw, fh, allow_unicode=True)
        count += 1

    if count == 0:
        return False, f"Tag '{tag}' not found on any document."
    return True, f"Tag '{tag}' removed from {count} document(s)."
