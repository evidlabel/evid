"""Tests for web_to_pdf — title/URL injection into Typst markup."""

import shutil

import pytest
from evid.core.typst_generation import web_to_pdf

needs_typst = pytest.mark.skipif(
    shutil.which("typst") is None, reason="typst binary not on PATH"
)


@needs_typst
def test_web_to_pdf_title_with_hashtags(tmp_path):
    """Page titles containing '#word' (e.g. social hashtags) must compile.

    Regression: a LinkedIn share with title '#sof #barndomudenvold | Karina
    Rohr Sørensen' caused 'unknown variable: sof' because the title was
    interpolated into Typst markup, where '#sof' is a code escape.
    """
    html = (
        "<html><head>"
        "<title>#sof #barndomudenvold | Karina Rohr Sørensen</title>"
        "</head><body><p>body text</p></body></html>"
    )
    pdf_path, page_title = web_to_pdf("https://example.com/post", tmp_path, html=html)
    assert pdf_path.exists()
    assert "#sof" in page_title


@needs_typst
def test_web_to_pdf_url_with_fragment(tmp_path):
    """URLs containing '#fragment' must not be parsed as Typst code."""
    html = "<html><head><title>Doc</title></head><body>x</body></html>"
    url = "https://example.com/page#section?utm_source=share"
    pdf_path, _ = web_to_pdf(url, tmp_path, html=html)
    assert pdf_path.exists()


@needs_typst
def test_web_to_pdf_title_with_markup_specials(tmp_path):
    """Titles with *, _, $, [, @ etc. must not be parsed as Typst syntax."""
    html = (
        "<html><head><title>$x^2$ * _foo_ [bar] @baz</title></head>"
        "<body>body</body></html>"
    )
    pdf_path, _ = web_to_pdf("https://example.com/post", tmp_path, html=html)
    assert pdf_path.exists()


@needs_typst
@pytest.mark.parametrize(
    "body",
    [
        "Hello _open emphasis on this line",  # unclosed _ → unclosed delimiter
        "Hello `open raw on this line",  # unclosed ` → unclosed raw text
        "Hello <open_angle on this line",  # unclosed < → unclosed label
        "Footnote anchor [1 with no close",  # unbalanced [ → unclosed delimiter
        "Stray ] in body",  # bare ] should also be safe
    ],
    ids=["underscore", "backtick", "angle", "bracket_open", "bracket_close"],
)
def test_web_to_pdf_body_with_markup_specials(tmp_path, body):
    """Scraped body text containing bare Typst delimiters must still compile.

    Regression: web_to_pdf interpolated the body in markup mode, and
    clean_text_for_typst escaped only #, *, $ — leaving _, `, <, [ free to
    open delimiters that scraped text never closed, killing the URL-fetch
    flow in the GUI.
    """
    html = f"<html><head><title>T</title></head><body><p>{body}</p></body></html>"
    pdf_path, _ = web_to_pdf("https://example.com/x", tmp_path, html=html)
    assert pdf_path.exists()
