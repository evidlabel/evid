"""Tests for web_to_pdf."""

from unittest.mock import MagicMock, patch

import pytest

from evid.core.typst_generation import web_to_pdf

HTML = """<html><head><title>Test Page</title></head>
<body><p>Hello world.</p><p>Second paragraph.</p></body></html>"""


@pytest.fixture
def mock_response():
    r = MagicMock()
    r.text = HTML
    r.raise_for_status.return_value = None
    return r


def test_web_to_pdf_creates_pdf(tmp_path, mock_response):
    with patch("requests.get", return_value=mock_response):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            pdf_path, title = web_to_pdf("http://example.com/article", tmp_path)

    assert pdf_path == tmp_path / "article.pdf"
    assert title == "Test Page"
    # Typst file should have been written
    assert (tmp_path / "article.typ").exists()
    typ_content = (tmp_path / "article.typ").read_text()
    assert "datetime.today" in typ_content
    assert "Hello world" in typ_content


def test_web_to_pdf_escapes_hash(tmp_path, mock_response):
    mock_response.text = (
        "<html><head><title>T</title></head><body>#hashtag</body></html>"
    )
    with patch("requests.get", return_value=mock_response):
        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
            web_to_pdf("http://example.com/page", tmp_path)

    typ_content = (tmp_path / "page.typ").read_text()
    assert "\\#hashtag" in typ_content


def test_web_to_pdf_typst_failure(tmp_path, mock_response):
    with patch("requests.get", return_value=mock_response), patch(
        "subprocess.run",
        return_value=MagicMock(returncode=1, stderr=b"compile error"),
    ), pytest.raises(RuntimeError, match="typst compile failed"):
        web_to_pdf("http://example.com/page", tmp_path)


def test_web_to_pdf_fallback_title(tmp_path):
    r = MagicMock()
    r.text = "<html><body>content</body></html>"
    r.raise_for_status.return_value = None
    with patch("requests.get", return_value=r):
        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
            _, title = web_to_pdf("http://example.com/somepage", tmp_path)
    assert title == "somepage"
