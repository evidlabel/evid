"""Full-text search over document *bodies* (not just info.yml metadata).

Searches each document's generated ``label.typ`` (the Typst file produced at
ingest, which carries the full body text inline under ``== Page N`` markers).
This is fast — no PDF re-extraction — and a fast external grepper (``rg`` or
``ugrep``) is used to narrow the candidate files before Python computes the
precise hit. When no grepper is on PATH, a pure-Python scan is used instead.

Two modes:

* **literal** (default) — case-insensitive substring match; one hit per document.
* **regex** — every ``re`` match across documents, each with a context snippet.

Both report the page number of the match (read from the ``== Page N`` markers).
Because the source is ``label.typ``, snippets may include Typst markup
(``#lab(...)``, ``== Page N``, escaping) and any labels the user has added.
Documents without a ``label.typ`` are skipped; the count is logged.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Marker lines emitted per page by ``textpdf_to_typst`` (typst_generation.py).
_PAGE_RX = re.compile(r"^== Page (\d+)\s*$", re.MULTILINE)

# Greppers we know how to drive, in preference order.
_GREPPERS = ("rg", "ugrep", "ug")


@dataclass
class TextHit:
    uuid: str
    label: str
    page: int
    snippet: str
    char_start: int
    score: float | None  # always None now (kept for table/preview compatibility)


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


def _page_for_typ_offset(text: str, offset: int) -> int:
    """Map a char offset in a ``label.typ`` to its 1-based page number.

    Uses the ``== Page N`` marker lines; returns the page of the last marker at
    or before *offset*, defaulting to 1 when no marker precedes it.
    """
    page = 1
    for m in _PAGE_RX.finditer(text):
        if m.start() <= offset:
            page = int(m.group(1))
        else:
            break
    return page


def _grepper() -> str | None:
    """Return the first available grepper binary, or None."""
    for name in _GREPPERS:
        if shutil.which(name):
            return name
    return None


def _iter_typ_files(set_path: Path):
    """Yield ``(doc_dir, label_typ_path)`` for every doc with a label.typ."""
    docs_dir = set_path / "docs"
    if not docs_dir.exists():
        return
    skipped = 0
    for doc_dir in sorted(d for d in docs_dir.iterdir() if d.is_dir()):
        typ = doc_dir / "label.typ"
        if typ.exists():
            yield doc_dir, typ
        else:
            skipped += 1
    if skipped:
        logger.info(
            "Full-text search skipped %d document(s) with no label.typ", skipped
        )


def _candidate_dirs(set_path: Path, query: str) -> list[Path] | None:
    """Use a grepper to find doc dirs whose label.typ contains *query* (literal).

    Returns the matching doc dirs (parents of matching label.typ files), or None
    when no grepper is available so the caller can fall back to a Python scan.
    """
    binary = _grepper()
    if binary is None:
        return None
    docs_dir = set_path / "docs"
    if not docs_dir.exists():
        return []
    # ``-l`` files-with-matches, ``-i`` ignore case, ``-F`` literal, ``-e`` pattern.
    cmd = [binary, "-l", "-i", "-F", "-e", query]
    if binary == "rg":
        # --no-ignore: don't let a .gitignore in the db tree hide label.typ files.
        cmd += ["--no-ignore", "-g", "label.typ", str(docs_dir)]
    else:  # ugrep / ug
        cmd += ["-r", "--include=label.typ", str(docs_dir)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError:
        logger.exception("Grepper %s failed to launch; using Python fallback", binary)
        return None
    # rg/ugrep exit 1 when there are no matches — that's not an error.
    if proc.returncode not in (0, 1):
        logger.warning(
            "Grepper %s exited %d: %s", binary, proc.returncode, proc.stderr.strip()
        )
        return None
    dirs = []
    for line in proc.stdout.splitlines():
        p = Path(line.strip())
        if p.name == "label.typ" and p.parent.is_dir():
            dirs.append(p.parent)
    return sorted(dirs)


def _literal_search(
    set_path: Path, query: str, *, n: int, context: int
) -> list[TextHit]:
    needle = query.casefold()
    candidates = _candidate_dirs(set_path, query)
    if candidates is None:
        # No grepper: scan every label.typ in Python.
        candidates = [doc_dir for doc_dir, _ in _iter_typ_files(set_path)]

    hits: list[TextHit] = []
    for doc_dir in candidates:
        typ = doc_dir / "label.typ"
        try:
            text = typ.read_text(encoding="utf-8")
        except OSError:
            logger.debug("Could not read %s", typ, exc_info=True)
            continue
        idx = text.casefold().find(needle)
        if idx < 0:
            continue
        hits.append(
            TextHit(
                uuid=doc_dir.name,
                label=_doc_label(doc_dir),
                page=_page_for_typ_offset(text, idx),
                snippet=_context(text, idx, idx + len(query), context),
                char_start=idx,
                score=None,
            )
        )
        if len(hits) >= n:
            break
    return hits


def _regex_search(
    set_path: Path, pattern: str, *, n: int, context: int
) -> list[TextHit]:
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        msg = f"Invalid regex '{pattern}': {exc}"
        raise ValueError(msg) from exc

    # Python's `re` is authoritative; scan every label.typ to avoid grepper
    # regex-dialect false negatives (reading files is cheap — no PDF work).
    hits: list[TextHit] = []
    for doc_dir, typ in _iter_typ_files(set_path):
        try:
            text = typ.read_text(encoding="utf-8")
        except OSError:
            logger.debug("Could not read %s", typ, exc_info=True)
            continue
        label = _doc_label(doc_dir)
        for m in rx.finditer(text):
            hits.append(
                TextHit(
                    uuid=doc_dir.name,
                    label=label,
                    page=_page_for_typ_offset(text, m.start()),
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
    context: int = 160,
) -> list[TextHit]:
    """Search document bodies (their ``label.typ``) in *set_path*.

    ``regex=True`` returns up to *n* regex matches (document then offset order);
    otherwise a case-insensitive substring match, one hit per document, up to *n*.
    """
    if regex:
        return _regex_search(set_path, query, n=n, context=context)
    return _literal_search(set_path, query, n=n, context=context)
