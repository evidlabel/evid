"""Tests for HTML date extraction (avoids the rendered-PDF 'today' trap)."""

import pymupdf
import pytest

from evid.core.pdf_metadata import extract_html_date, extract_pdf_metadata


@pytest.mark.parametrize(
    "html",
    [
        '<meta property="article:published_time" content="2025-04-02T10:00:00Z">',
        '<meta name="date" content="2025-04-02">',
        '<meta itemprop="datePublished" content="2025-04-02">',
        '<script type="application/ld+json">{"datePublished":"2025-04-02T08:00:00"}</script>',
        '<time datetime="2025-04-02">2. april 2025</time>',
    ],
)
def test_extract_html_date_finds_iso(html):
    assert extract_html_date(html) == "2025-04-02"


def test_extract_html_date_absent_returns_empty():
    assert extract_html_date("<html><body>no date here</body></html>") == ""


def test_extract_pdf_metadata_reads_pymupdf_fields(tmp_path):
    """Title/author/date come from PyMuPDF's metadata dict."""
    doc = pymupdf.open()
    doc.new_page()
    doc.set_metadata(
        {
            "title": "The Judgment",
            "author": "High Court",
            "creationDate": "D:20240102030405Z",
        }
    )
    pdf = tmp_path / "j.pdf"
    doc.save(str(pdf))
    doc.close()

    title, authors, date = extract_pdf_metadata(pdf, pdf.name)
    assert title == "The Judgment"
    assert authors == "High Court"
    assert date == "2024-01-02"


def test_extract_pdf_metadata_falls_back_to_filename(tmp_path):
    doc = pymupdf.open()
    doc.new_page()
    pdf = tmp_path / "unnamed.pdf"
    doc.save(str(pdf))
    doc.close()

    title, authors, date = extract_pdf_metadata(pdf, pdf.name)
    assert title == "unnamed"
    assert authors == ""
    assert date == ""
