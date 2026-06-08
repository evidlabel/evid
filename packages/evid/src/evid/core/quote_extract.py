"""Machine quoting: turn approximate candidate quotes into verbatim Hayagriva.

The agent supplies *approximate* quotes as **JSON** (never YAML/Hayagriva, so the
input can never be loaded or cited as a bibliography). Each candidate is located
verbatim in the document's plain text with the deterministic fuzzy matcher
(:mod:`evid.core.quote_match`) and written to ``machine.hayagriva`` in the doc's
directory — the only Hayagriva-format, citable output.

``machine.hayagriva`` is labquote-native so it groups alongside the manual
``label.bib`` keys for the same document:

* keys are ``{uuid[:4]}:qN`` (colon-namespaced), verbatim quote in ``title:`` as a
  literal block, plus a ``{uuid[:4]}:main`` document entry written once.
* writes are append-only — existing entries, comments and watermarks are preserved.

Document metadata (title/author/date/url) comes from the doc's ``info.yml``; the
caller never passes it. ``evid set gather`` merges ``machine.hayagriva`` into its
exports.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path

from pydantic import BaseModel, Field

from evid.core.bibtex_utils import (
    load_authors,
    load_dates,
    load_title,
    load_url,
    load_uuid_prefix,
)
from evid.core.quote_match import fuzzy_locate
from evid.core.text_cleaning import _dehyphenate

logger = logging.getLogger(__name__)

TITLE_TRUNCATE = 240
MACHINE_FILE = "machine.hayagriva"
TEXT_CACHE = "text.txt"


# ── candidate input model (JSON, deliberately not Hayagriva) ─────────────────


class QuoteCandidate(BaseModel):
    """One approximate quote the agent wants made verbatim."""

    candidate: str
    note: str = ""
    min_ratio: float | None = None


class QuotesFile(BaseModel):
    """Schema of the ``quotes.json`` input."""

    quotes: list[QuoteCandidate] = Field(default_factory=list)


def load_quotes_json(path: Path) -> QuotesFile:
    """Load and validate a ``quotes.json`` candidate file.

    Strictly JSON: a YAML / Hayagriva file fails to parse here, which is the
    point — the non-citable boundary between paraphrased input and verbatim
    output is structural, not just by convention.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{path} is not valid JSON. The candidate file must be JSON "
            "(not YAML/Hayagriva) so it can never be cited as a bibliography."
        ) from exc
    return QuotesFile(**raw)


@dataclass
class QuoteResult:
    """Outcome of locating one candidate. ``key`` is None when no confident match."""

    candidate: str
    matched: bool
    score: float
    key: str | None = None
    page: int | None = None


def candidates_from_search(results, uuid: str, n: int) -> list[QuoteCandidate]:
    """Turn vector-search results for one document into quote candidates.

    Takes the top ``n`` chunks belonging to ``uuid`` (results are assumed already
    ranked) and wraps each chunk's text as a :class:`QuoteCandidate`. The fuzzy
    matcher later re-snaps each chunk to a clean sentence span, so the stored quote
    is a verbatim sentence, not the raw chunk. Duck-typed on ``r.doc.uuid`` and
    ``r.chunk_text`` so it is testable without a live index.
    """
    out: list[QuoteCandidate] = []
    for r in results:
        if getattr(r.doc, "uuid", None) != uuid:
            continue
        text = (r.chunk_text or "").strip()
        if text:
            out.append(QuoteCandidate(candidate=text))
        if len(out) >= n:
            break
    return out


# ── document plain text ──────────────────────────────────────────────────────


def _read_source(doc_dir: Path) -> tuple[str, list[tuple[int, int]]]:
    """Extract raw plain text from the doc's PDF (or .txt), with a page index.

    Returns ``(full_text, page_index)`` where ``page_index`` is a sorted list of
    ``(char_offset, page_no)`` marking where each page starts in ``full_text``.
    Unlike :func:`evid.core.typst_generation.textpdf_to_typst`, no Typst escaping
    is applied — the matcher needs the raw text.
    """
    pdfs = sorted(doc_dir.glob("*.pdf"))
    if pdfs:
        import fitz

        parts: list[str] = []
        page_index: list[tuple[int, int]] = []
        offset = 0
        with fitz.open(pdfs[0]) as pdf:
            for i, page in enumerate(pdf):
                page_index.append((offset, i + 1))
                # De-hyphenate per page so verbatim spans don't carry the PDF's
                # end-of-line soft hyphens (e.g. "mar-\nkant" → "markant"). Page
                # offsets stay consistent with the cached text.txt.
                text = _dehyphenate(page.get_text())
                parts.append(text)
                offset += len(text)
        return "".join(parts), page_index

    txts = sorted(doc_dir.glob("*.txt"))
    # text.txt is our own cache — never treat it as the source document.
    txts = [t for t in txts if t.name != TEXT_CACHE]
    if txts:
        return _dehyphenate(txts[0].read_text(encoding="utf-8")), [(0, 1)]

    raise FileNotFoundError(f"No PDF or TXT source found in {doc_dir}")


def extract_document_text(
    doc_dir: Path, refresh: bool = False
) -> tuple[str, list[tuple[int, int]]]:
    """Return the doc's flat plain text and page index, caching to ``text.txt``.

    Extraction is deterministic, so the cached ``text.txt`` is authoritative for
    character offsets (keeping ``serial-number`` spans stable across runs). The
    page index is always derived from the live source.
    """
    computed_text, page_index = _read_source(doc_dir)
    cache = doc_dir / TEXT_CACHE
    if cache.exists() and not refresh:
        full_text = cache.read_text(encoding="utf-8")
    else:
        full_text = computed_text
        cache.write_text(full_text, encoding="utf-8")
    return full_text, page_index


def _page_for_offset(offset: int, page_index: list[tuple[int, int]]) -> int:
    """Map a character offset to its 1-based page number."""
    page = page_index[0][1] if page_index else 1
    for start, no in page_index:
        if start <= offset:
            page = no
        else:
            break
    return page


# ── Hayagriva writing (labquote-native) ──────────────────────────────────────


def watermark(url: str | None = None) -> str:
    """Provenance comment stamped above every entry this tool appends."""
    from evid import __version__ as _evid_version

    wm = f"# generated-by: evid v{_evid_version} · {_date.today().isoformat()}"
    if url:
        wm += f" · {url}"
    return wm + "\n"


def find_next_q(bib_text: str, prefix: str, sep: str = ":q") -> int:
    """Next free ``q<N>`` number for ``prefix`` in an existing bib."""
    pat = re.compile(rf"^{re.escape(prefix)}{re.escape(sep)}(\d+):", re.MULTILINE)
    nums = [int(m.group(1)) for m in pat.finditer(bib_text)]
    return max(nums, default=0) + 1


def has_main(bib_text: str, prefix: str) -> bool:
    """True if a ``<prefix>:main:`` document entry already exists."""
    return re.search(rf"^{re.escape(prefix)}:main:", bib_text, re.MULTILINE) is not None


def _yaml_quoted_inline(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _yaml_literal_block(text: str, indent: int = 4) -> str:
    pad = " " * indent
    body = "\n".join(pad + line for line in text.split("\n"))
    return "|-\n" + body


def _truncate(s: str, n: int = TITLE_TRUNCATE) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def build_main_entry(
    prefix: str,
    source_type: str,
    url: str | None,
    author: str | None,
    date: str | None,
    doc_title: str | None,
) -> str:
    """The ``<prefix>:main`` document entry that quotes group under."""
    lines = [f"{prefix}:main:", f"  type: {source_type}"]
    if doc_title:
        lines.append(f"  title: {_yaml_quoted_inline(_truncate(doc_title))}")
    if author:
        lines.append(f"  author: {_yaml_quoted_inline(author)}")
    if date:
        lines.append(f"  date: {date}")
    if url:
        lines.append(f"  url: {url}")
    return watermark(url) + "\n".join(lines) + "\n"


def build_quote_entry(
    key: str,
    quote: str,
    char_start: int,
    char_end: int,
    page: int | None,
    source_type: str,
    url: str | None,
    author: str | None,
    date: str | None,
) -> str:
    """A verbatim quote entry — labquote reads the quote body from ``title:``."""
    lines = [
        "# verbatim, rapidfuzz-verified",
        f"{key}:",
        f"  type: {source_type}",
        f"  title: {_yaml_literal_block(quote, indent=4)}",
    ]
    if author:
        lines.append(f"  author: {_yaml_quoted_inline(author)}")
    if date:
        lines.append(f"  date: {date}")
    if url:
        lines.append(f"  url: {url}")
    if page is not None:
        # `page-range` is Hayagriva's standard locator field — Typst's native
        # bibliography and labquote both read it (labquote renders it as "p. N").
        lines.append(f'  page-range: "{page}"')
    lines.append(f'  serial-number: "chars {char_start}-{char_end}"')
    return watermark(url) + "\n".join(lines) + "\n"


# ── orchestration ────────────────────────────────────────────────────────────


def extract_quotes(
    doc_dir: Path,
    candidates: list[QuoteCandidate],
    min_ratio: float = 0.78,
    refresh: bool = False,
    source_type: str = "article",
) -> list[QuoteResult]:
    """Locate each candidate verbatim and append matches to ``machine.hayagriva``.

    Returns a :class:`QuoteResult` per candidate (in input order). Low-confidence
    candidates are skipped (``matched=False``, ``key=None``) and logged.
    """
    info_path = doc_dir / "info.yml"
    prefix = load_uuid_prefix(info_path)
    if not prefix:
        raise ValueError(f"Could not read uuid prefix from {info_path}")

    title = load_title(info_path) or None
    author = load_authors(info_path) or None
    url = load_url(info_path) or None
    date = load_dates(info_path) or None

    full_text, page_index = extract_document_text(doc_dir, refresh=refresh)

    bib_path = doc_dir / MACHINE_FILE
    bib_text = bib_path.read_text(encoding="utf-8") if bib_path.exists() else ""

    results: list[QuoteResult] = []
    appended = ""
    for cand in candidates:
        ratio = cand.min_ratio if cand.min_ratio is not None else min_ratio
        match = fuzzy_locate(cand.candidate, full_text, ratio)
        if not match.match_found:
            logger.warning(
                "Skipping low-confidence candidate (score %.2f < %.2f): %.60s",
                match.score,
                ratio,
                cand.candidate,
            )
            results.append(
                QuoteResult(candidate=cand.candidate, matched=False, score=match.score)
            )
            continue

        current = bib_text + appended
        if not has_main(current, prefix):
            appended += (
                build_main_entry(prefix, source_type, url, author, date, title) + "\n"
            )
            current = bib_text + appended

        n = find_next_q(current, prefix)
        key = f"{prefix}:q{n}"
        page = _page_for_offset(match.match_start, page_index)
        entry = build_quote_entry(
            key=key,
            quote=match.exact_quote,
            char_start=match.match_start,
            char_end=match.match_end,
            page=page,
            source_type=source_type,
            url=url,
            author=author,
            date=date,
        )
        if appended and not appended.endswith("\n\n"):
            appended += "\n"
        appended += entry
        results.append(
            QuoteResult(
                candidate=cand.candidate,
                matched=True,
                score=match.score,
                key=key,
                page=page,
            )
        )

    if appended:
        if bib_text and not bib_text.endswith("\n"):
            bib_text += "\n"
        if bib_text and not bib_text.endswith("\n\n"):
            bib_text += "\n"
        bib_path.write_text(bib_text + appended, encoding="utf-8")

    return results
