"""Shared document loading and meta search for CLI and GUI."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import yaml

from evid.core.models import InfoModel
from evid.models import Document

logger = logging.getLogger(__name__)


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
            info = InfoModel(**raw)
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

        tags = [t.strip() for t in info.tags.split(",") if t.strip()]
        results.append(
            Document(
                uuid=info.uuid or doc_dir.name,
                path=doc_dir,
                label=info.title or info.label,
                tags=tags,
                added=datetime.now(tz=UTC),
                source_url=info.url,
            )
        )
    return results
