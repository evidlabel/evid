"""Per-document metadata sidecar (indexed, notes)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

META_LEGACY = "evidmgr_meta.yml"
META_CURRENT = "evid_meta.yml"

_DEFAULT: dict[str, Any] = {
    "notes": "",
    "indexed": False,
}


def meta_path(doc_dir: Path, *, for_write: bool = False) -> Path:
    """Return path to the metadata file for *doc_dir*.

    Reads prefer ``evid_meta.yml`` then legacy ``evidmgr_meta.yml``.
    Writes always target ``evid_meta.yml``.
    """
    current = doc_dir / META_CURRENT
    legacy = doc_dir / META_LEGACY
    if for_write:
        return current
    if current.exists():
        return current
    if legacy.exists():
        return legacy
    return current


def read_meta(doc_dir: Path) -> dict[str, Any]:
    path = meta_path(doc_dir)
    if not path.exists():
        return dict(_DEFAULT)
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return {**_DEFAULT, **data}
    except Exception:
        logger.exception("Failed to read %s", path)
        return dict(_DEFAULT)


def write_meta(doc_dir: Path, meta: dict[str, Any]) -> Path:
    """Write metadata to ``evid_meta.yml`` (migrates off legacy filename)."""
    path = meta_path(doc_dir, for_write=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(meta, f, allow_unicode=True)
    legacy = doc_dir / META_LEGACY
    if legacy.exists() and legacy != path:
        try:
            legacy.unlink()
        except OSError:
            logger.warning("Could not remove legacy meta file %s", legacy)
    return path
