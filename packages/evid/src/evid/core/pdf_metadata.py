"""Extract PDF metadata functions."""

import logging
import re
from io import BytesIO
from pathlib import Path

import pypdf

from evid.utils.text import normalize_text

# Logging is configured centrally in evid.logging_config (called from main()).
logger = logging.getLogger(__name__)

# Common ways a publish date is exposed in HTML, most specific first.
_HTML_DATE_PATTERNS = (
    r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
    r'<meta[^>]+name=["\'](?:date|dc\.date|dcterms\.date|pubdate)["\'][^>]+content=["\']([^"\']+)["\']',
    r'<meta[^>]+itemprop=["\']datePublished["\'][^>]+content=["\']([^"\']+)["\']',
    r'"datePublished"\s*:\s*"([^"]+)"',
    r'<time[^>]+datetime=["\']([^"\']+)["\']',
)


def extract_html_date(html: str) -> str:
    """Best-effort published date (YYYY-MM-DD) from an HTML page, else ''.

    Avoids the trap where a URL is rendered to a fresh PDF whose creation date is
    *today*: prefer the page's own metadata. Returns the first ``YYYY-MM-DD`` found
    in standard meta tags / JSON-LD / ``<time>``; empty string if none.
    """
    for pat in _HTML_DATE_PATTERNS:
        m = re.search(pat, html, re.IGNORECASE)
        if not m:
            continue
        iso = re.search(r"\d{4}-\d{2}-\d{2}", m.group(1))
        if iso:
            return iso.group(0)
    return ""


def extract_pdf_metadata(
    pdf_source: Path | BytesIO, file_name: str
) -> tuple[str, str, str]:
    """Extract title, authors, and date from PDF as plain strings, preserving Danish characters."""

    try:
        if isinstance(pdf_source, Path):
            with open(pdf_source, "rb") as f:
                reader = pypdf.PdfReader(f)
                meta = reader.metadata
        else:
            pdf_source.seek(0)
            reader = pypdf.PdfReader(pdf_source)
            meta = reader.metadata

        title = normalize_text(meta.get("/Title", Path(file_name).stem))
        authors = normalize_text(meta.get("/Author", ""))
        date = normalize_text(meta.get("/CreationDate") or meta.get("/ModDate", ""))
        if date and date.startswith("D:"):
            date = f"{date[2:6]}-{date[6:8]}-{date[8:10]}"  # YYYY-MM-DD
        else:
            date = ""
    except Exception:
        title = normalize_text(Path(file_name).stem)
        authors = ""
        date = ""
        logger.warning(f"Failed to extract metadata from {file_name}, using defaults.")
    return title, authors, date
