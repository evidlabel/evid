"""Tests for core label setup."""

import pytest
from pathlib import Path
from evid.core.typst_generation import textpdf_to_typst, text_to_typst


def test_textpdf_to_typst(tmp_path):
    """Test generating Typst from PDF."""
    try:
        import fitz
    except (ImportError, RuntimeError):
        pytest.skip("fitz not available")
    # Create a dummy PDF
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Test content")
    doc.save(pdf_path)
    doc.close()

    # Create info.yml
    info_path = tmp_path / "info.yml"
    info_path.write_text("label: test\ndates: 2023-01-01\n")

    output_path = tmp_path / "output.typ"
    result = textpdf_to_typst(pdf_path, output_path)
    assert "Test content" in result
    assert output_path.exists()


def test_text_to_typst(tmp_path):
    """Test generating Typst from text."""
    txt_path = tmp_path / "test.txt"
    txt_path.write_text("Test text content\n\nAnother paragraph.")

    # Create info.yml
    info_path = tmp_path / "info.yml"
    info_path.write_text("label: test\ndates: 2023-01-01\n")

    output_path = tmp_path / "output.typ"
    result = text_to_typst(txt_path, output_path)
    assert "Test text content" in result
    assert output_path.exists()
