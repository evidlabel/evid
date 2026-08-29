"""Shared document loading and meta search for CLI and GUI."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import yaml

from evid.models import Document

logger = logging.getLogger(__name__)


def _parse_tags(tags_raw: object) -> list[str]:
    """Normalize tags from list or comma-separated string."""
    if isinstance(tags_raw, list):
        return [str(t).strip() for t in tags_raw if str(t).strip()]
    if tags_raw:
        return [t.strip() for t in str(tags_raw).split(",") if t.strip()]
    return []


def load_document(doc_dir: Path, doc_uuid: str | None = None) -> Document:
    """Load a Document from its UUID directory (info.yml + evid_meta.yml).

    Missing ``info.yml`` yields an empty info dict; the Document is still
    returned.  Label falls back to the document UUID when unset/empty.
    Tags accept either a list or a comma-separated string.
    """
    from evid.core.evid_meta import read_meta

    resolved_uuid = doc_uuid if doc_uuid is not None else doc_dir.name
    info_path = doc_dir / "info.yml"
    info: dict = {}
    if info_path.exists():
        try:
            with info_path.open("r", encoding="utf-8") as f:
                info = yaml.safe_load(f) or {}
        except Exception:
            logger.debug("Failed to read info.yml in %s", doc_dir.name, exc_info=True)
            info = {}

    meta = read_meta(doc_dir)
    tags = _parse_tags(info.get("tags", ""))

    # Prefer explicit label; empty/missing falls back to uuid (resilient).
    # Title is not used here — callers that need InfoModel-style label←title
    # (e.g. search_meta_documents) overlay that after load.
    return Document(
        uuid=resolved_uuid,
        path=doc_dir,
        label=info.get("label") or resolved_uuid,
        tags=tags,
        added=datetime.now(tz=UTC),
        indexed=meta.get("indexed", False),
        notes=meta.get("notes", ""),
        source_url=info.get("url") or "",
    )


def search_meta_documents(
    evidence_set_path: Path,
    pattern: str = "",
) -> list[Document]:
    """Return documents whose info.yml matches *pattern* (regex or substring)."""
    docs_dir = evidence_set_path / "docs"
    if not docs_dir.exists():
        return []

    results: list[Document] = []
    pattern = pattern.strip()

    for doc_dir in sorted(docs_dir.iterdir()):
        if not doc_dir.is_dir():
            continue
        info_path = doc_dir / "info.yml"
        if not info_path.exists():
            continue
        try:
            with info_path.open(encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            if not isinstance(raw, dict):
                continue
        except Exception:
            logger.debug("Skipping bad info.yml in %s", doc_dir.name, exc_info=True)
            continue

        haystack = " ".join(str(v) for v in raw.values() if v is not None)
        if pattern:
            try:
                if not re.search(pattern, haystack, re.IGNORECASE):
                    continue
            except re.error:
                if pattern.lower() not in haystack.lower():
                    continue

        # Shared loader for tags/meta; preserve prior label mapping (title|label).
        doc = load_document(doc_dir, raw.get("uuid") or doc_dir.name)
        display_label = raw.get("label") or raw.get("title")
        if display_label:
            doc.label = str(display_label)
        results.append(doc)
    return results
