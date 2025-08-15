import pytest
import fitz
from evid.core.label_setup import textpdf_to_typst, clean_text_for_typst
import yaml


@pytest.fixture
def temp_pdf_with_info(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    info_path = tmp_path / "info.yml"

    # Create a simple PDF
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Sample text with #special chars")
    doc.save(pdf_path)

    # Create info.yml
    info_data = {
        "original_name": "test.pdf",
        "uuid": "test-uuid",
        "time_added": "2023-01-01",
        "dates": "2023-01-01",
        "title": "Test Title",
        "authors": "Test Author",
        "tags": "",
        "label": "test_label",
        "url": "",
    }
    with info_path.open("w") as f:
        yaml.dump(info_data, f)

    yield pdf_path, info_path
    doc.close()


def test_clean_text_for_typst():
    text = "Text with #special chars\n\n\nExtra newlines"
    cleaned = clean_text_for_typst(text)
    assert cleaned == "Text with #special chars\n\nExtra newlines"


def test_textpdf_to_typst(temp_pdf_with_info):
    pdf_path, _ = temp_pdf_with_info
    typst = textpdf_to_typst(pdf_path)

    assert 'date: "2023-01-01")' in typst
    assert "= test label" in typst
    assert "== Page 1" in typst
    assert "Sample text with #special chars" in typst
    assert "#lablist()" in typst


def test_textpdf_to_typst_no_info(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "No info file")
    doc.save(pdf_path)

    typst = textpdf_to_typst(pdf_path)
    assert 'date: "DATE")' in typst
    assert "= NAME" in typst
    assert "No info file" in typst

    doc.close()
