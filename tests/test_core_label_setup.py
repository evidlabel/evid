"""Tests for core label setup."""


import pytest

from evid.core.typst_generation import text_to_typst, textpdf_to_typst


def test_textpdf_to_typst(tmp_path):
    try:
        import fitz
    except (ImportError, RuntimeError):
        pytest.skip("fitz not available")
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Test content")
    doc.save(pdf_path)
    doc.close()

    info_path = tmp_path / "info.yml"
    info_path.write_text("label: test\ndates: 2023-01-01\n")

    output_path = tmp_path / "output.typ"
    result = textpdf_to_typst(pdf_path, output_path)
    assert "Test content" in result
    assert output_path.exists()


def test_textpdf_to_typst_no_info(tmp_path):
    try:
        import fitz
    except (ImportError, RuntimeError):
        pytest.skip("fitz not available")
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(pdf_path)
    doc.close()

    result = textpdf_to_typst(pdf_path)
    assert "NAME" in result
    assert "DATE" in result


def test_textpdf_to_typst_autolabel(tmp_path):
    try:
        import fitz
    except (ImportError, RuntimeError):
        pytest.skip("fitz not available")
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "First paragraph.\n\nSecond paragraph.")
    doc.save(pdf_path)
    doc.close()

    (tmp_path / "info.yml").write_text("label: test\ndates: 2023-01-01\n")

    result = textpdf_to_typst(pdf_path, autolabel=True)
    assert '#lab("lab' in result


def test_textpdf_to_typst_info_validation_error(tmp_path):
    try:
        import fitz
    except (ImportError, RuntimeError):
        pytest.skip("fitz not available")
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(pdf_path)
    doc.close()

    # info.yml with invalid/missing required fields
    (tmp_path / "info.yml").write_text("label: test\n")

    result = textpdf_to_typst(pdf_path)
    # Falls back to defaults on validation error
    assert result is not None


def test_text_to_typst(tmp_path):
    txt_path = tmp_path / "test.txt"
    txt_path.write_text("Test text content\n\nAnother paragraph.")

    info_path = tmp_path / "info.yml"
    info_path.write_text("label: test\ndates: 2023-01-01\n")

    output_path = tmp_path / "output.typ"
    result = text_to_typst(txt_path, output_path)
    assert "Test text content" in result
    assert output_path.exists()


def test_text_to_typst_no_info(tmp_path):
    txt_path = tmp_path / "test.txt"
    txt_path.write_text("Hello world.")

    result = text_to_typst(txt_path)
    assert "NAME" in result
    assert "DATE" in result


def test_text_to_typst_autolabel(tmp_path):
    txt_path = tmp_path / "test.txt"
    txt_path.write_text("Para one.\n\nPara two.")

    (tmp_path / "info.yml").write_text("label: test\ndates: 2023-01-01\n")

    result = text_to_typst(txt_path, autolabel=True)
    assert '#lab("lab' in result


def test_text_to_typst_info_validation_error(tmp_path):
    txt_path = tmp_path / "test.txt"
    txt_path.write_text("Hello.")

    # Missing required fields
    (tmp_path / "info.yml").write_text("label: test\n")

    result = text_to_typst(txt_path)
    assert result is not None


def test_text_to_typst_no_outputfile(tmp_path):
    txt_path = tmp_path / "test.txt"
    txt_path.write_text("Hello.")

    result = text_to_typst(txt_path)
    assert "Hello" in result
