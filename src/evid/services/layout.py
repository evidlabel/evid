"""Where an evidence set lives on disk.

A new set is created at one of:

    {data_dir}/anon/anon_set_{slug}/
    {data_dir}/plain/plain_set_{slug}/

``anon`` is :class:`~evid.models.SetType.ANON`. ``plain`` is
:class:`~evid.models.SetType.NORMAL` (the type value stays ``normal``).
The slug in ``set.yml`` and on the CLI is unchanged; only the directory
name carries the ``anon_set_`` / ``plain_set_`` prefix.

A set written before this layout still lives at ``{data_dir}/sets/{slug}/``
and is read and updated there.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from evid.models import SetType

logger = logging.getLogger(__name__)

# (bucket directory, directory-name prefix) for each type.
_LAYOUT: dict[SetType, tuple[str, str]] = {
    SetType.ANON: ("anon", "anon_set_"),
    SetType.NORMAL: ("plain", "plain_set_"),
}
_LEGACY = "sets"


def new_set_dir(data_dir: Path, set_type: SetType | str, slug: str) -> Path:
    """Directory a new set of this type would occupy."""
    bucket, prefix = _LAYOUT[SetType(set_type)]
    return Path(data_dir) / bucket / f"{prefix}{slug}"


def read_slug(set_dir: Path) -> str | None:
    """Slug recorded in ``set.yml``, else the one implied by the directory name."""
    yml = set_dir / "set.yml"
    if not yml.is_file():
        return None
    try:
        data = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.exception("Failed to read %s", yml)
        return None
    if not isinstance(data, dict):
        return None
    slug = data.get("slug")
    if slug:
        return str(slug)
    name = set_dir.name
    parent = set_dir.parent.name
    for bucket, prefix in _LAYOUT.values():
        if parent == bucket and name.startswith(prefix):
            rest = name.removeprefix(prefix)
            return rest or name
    return name


def iter_set_dirs(data_dir: Path):
    """Set directories that have ``set.yml``, one per slug.

    ``anon`` and ``plain`` come first, then the legacy ``sets`` tree.
    A slug that appears twice keeps the earlier directory.
    """
    seen: set[str] = set()
    data_dir = Path(data_dir)
    buckets = [bucket for bucket, _prefix in _LAYOUT.values()]
    buckets.append(_LEGACY)
    for bucket in buckets:
        root = data_dir / bucket
        if not root.is_dir():
            continue
        for set_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            if not (set_dir / "set.yml").is_file():
                continue
            slug = read_slug(set_dir)
            if not slug:
                continue
            if slug in seen:
                logger.warning(
                    "duplicate set '%s' at %s; keeping the earlier one",
                    slug,
                    set_dir,
                )
                continue
            seen.add(slug)
            yield set_dir


def find_set_dir(data_dir: Path, slug: str) -> Path | None:
    """Set directory for *slug* that has ``set.yml``, or None."""
    for set_dir in iter_set_dirs(data_dir):
        if read_slug(set_dir) == slug:
            return set_dir
    return None


def existing_set_dir(data_dir: Path, slug: str) -> Path | None:
    """Directory for *slug*, including one that has documents but no ``set.yml`` yet.

    A directory with ``set.yml`` wins. Otherwise the first existing directory
    among the anon path, the plain path and ``sets/{slug}/``.
    """
    found = find_set_dir(data_dir, slug)
    if found is not None:
        return found
    data_dir = Path(data_dir)
    candidates = (
        new_set_dir(data_dir, SetType.ANON, slug),
        new_set_dir(data_dir, SetType.NORMAL, slug),
        data_dir / _LEGACY / slug,
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def place_new_set(data_dir: Path, set_type: SetType | str, slug: str) -> Path:
    """Directory ``create_set`` should write.

    A ``set.yml`` already stored under this slug is an error. A directory
    prepared in advance (the new path, or ``sets/{slug}/``) is reused so
    documents already there are not split into a second set.
    """
    data_dir = Path(data_dir)
    if find_set_dir(data_dir, slug) is not None:
        raise FileExistsError(f"Set '{slug}' already exists")
    dest = new_set_dir(data_dir, set_type, slug)
    legacy = data_dir / _LEGACY / slug
    for candidate in (dest, legacy):
        if (candidate / "set.yml").is_file():
            raise FileExistsError(f"Set '{slug}' already exists")
        if candidate.is_dir():
            return candidate
    return dest
