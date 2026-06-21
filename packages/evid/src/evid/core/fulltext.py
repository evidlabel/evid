"""Full-text search over document *bodies* (not just info.yml metadata).

Two modes over each document's extracted plain text (PDF/txt → cached
``text.txt``, via :func:`evid.core.quote_extract.extract_document_text`):

* **fuzzy** (default) — `rapidfuzz` partial-ratio match; ranks documents by how
  closely the query appears, snapped to a clean sentence. Tolerant of typos and
  paraphrase.
* **regex** — every `re` match across documents, each with a context snippet.

Both report the page number of the match. Documents with no PDF/txt source are
skipped (nothing to extract); the count is logged.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from evid.core.quote_extract import (
    _page_for_offset,
    extract_document_text,
)
from evid.core.quote_match import fuzzy_locate

logger = logging.getLogger(__name__)


@dataclass
class TextHit:
    uuid: str
    label: str
    page: int
    snippet: str
    char_start: int
    score: float | None  # fuzzy partial ratio in [0, 1]; None for regex


def _doc_label(doc_dir: Path) -> str:
    info_p = doc_dir / "info.yml"
    if info_p.exists():
        try:
            raw = yaml.safe_load(info_p.read_text(encoding="utf-8")) or {}
            return raw.get("title") or raw.get("label") or doc_dir.name
        except Exception:
            logger.debug("Bad info.yml in %s", doc_dir.name, exc_info=True)
    return doc_dir.name


def _context(text: str, start: int, end: int, ctx: int) -> str:
    a = max(0, start - ctx)
    b = min(len(text), end + ctx)
    lead = "…" if a > 0 else ""
    trail = "…" if b < len(text) else ""
    return (lead + text[a:b] + trail).replace("\n", " ").strip()


def _iter_doc_texts(set_path: Path, refresh: bool):
    docs_dir = set_path / "docs"
    if not docs_dir.exists():
        return
    skipped = 0
    for doc_dir in sorted(d for d in docs_dir.iterdir() if d.is_dir()):
        try:
            text, page_index = extract_document_text(doc_dir, refresh=refresh)
        except Exception:
            skipped += 1
            logger.debug("No extractable text for %s", doc_dir.name, exc_info=True)
            continue
        yield doc_dir, text, page_index
    if skipped:
        logger.info("Full-text search skipped %d document(s) with no source", skipped)


def _fuzzy_search(
    set_path: Path, query: str, *, n: int, min_ratio: float, refresh: bool
) -> list[TextHit]:
    hits: list[TextHit] = []
    for doc_dir, text, page_index in _iter_doc_texts(set_path, refresh):
        if not text:
            continue
        res = fuzzy_locate(query, text, min_ratio=min_ratio)
        if not res.match_found:
            continue
        hits.append(
            TextHit(
                uuid=doc_dir.name,
                label=_doc_label(doc_dir),
                page=_page_for_offset(res.match_start, page_index),
                snippet=res.exact_quote,
                char_start=res.match_start,
                score=res.score,
            )
        )
    hits.sort(key=lambda h: h.score or 0.0, reverse=True)
    return hits[:n]


def _regex_search(
    set_path: Path, pattern: str, *, n: int, context: int, refresh: bool
) -> list[TextHit]:
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        msg = f"Invalid regex '{pattern}': {exc}"
        raise ValueError(msg) from exc

    hits: list[TextHit] = []
    for doc_dir, text, page_index in _iter_doc_texts(set_path, refresh):
        label = _doc_label(doc_dir)
        for m in rx.finditer(text):
            hits.append(
                TextHit(
                    uuid=doc_dir.name,
                    label=label,
                    page=_page_for_offset(m.start(), page_index),
                    snippet=_context(text, m.start(), m.end(), context),
                    char_start=m.start(),
                    score=None,
                )
            )
            if len(hits) >= n:
                return hits
    return hits


def search_fulltext(
    set_path: Path,
    query: str,
    *,
    regex: bool = False,
    n: int = 10,
    min_ratio: float = 0.7,
    context: int = 160,
    refresh: bool = False,
) -> list[TextHit]:
    """Search document bodies in *set_path*.

    ``regex=True`` returns up to *n* regex matches (document then offset order);
    otherwise a fuzzy partial-ratio match per document, the top *n* by score.
    """
    if regex:
        return _regex_search(set_path, query, n=n, context=context, refresh=refresh)
    return _fuzzy_search(set_path, query, n=n, min_ratio=min_ratio, refresh=refresh)
