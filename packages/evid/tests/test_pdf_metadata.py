"""Tests for HTML date extraction (avoids the rendered-PDF 'today' trap)."""

import pytest
from evid.core.pdf_metadata import extract_html_date


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
