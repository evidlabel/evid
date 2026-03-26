"""Tests for label setup."""

import pytest
from pathlib import Path


def test_extract_pdf_metadata(tmp_path):
    """Test extracting metadata from PDF."""
    try:
        import fitz
    except (ImportError, RuntimeError):
        pytest.skip("fitz not available")
    from evid.core.pdf_metadata import extract_pdf_metadata

    # Create a dummy PDF with metadata
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    doc.set_metadata({"title": "Test Title", "author": "Test Author", "creationDate": "D:20230101000000"})
    page = doc.new_page()
    page.insert_text((50, 50), "Content")
    doc.save(pdf_path)
    doc.close()

    title, authors, date = extract_pdf_metadata(pdf_path, "test.pdf")
    assert title == "Test Title"
    assert authors == "Test Author"
    assert date == "2023-01-01"
