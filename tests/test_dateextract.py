import pytest
from pathlib import Path
import fitz
from evid.core.dateextract import extract_dates_from_pdf
import arrow
from io import BytesIO

@pytest.fixture
def temp_pdf(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Date: 12/01/2023\nAnother date: 15. januar 2024")
    doc.save(pdf_path)
    yield pdf_path
    doc.close()

@pytest.fixture
def temp_pdf_stream():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Date: 12/01/2023")
    stream = BytesIO()
    doc.save(stream, garbage=4, deflate=True)
    stream.seek(0)
    yield stream
    doc.close()

def test_extract_dates_from_pdf_file(temp_pdf):
    dates = extract_dates_from_pdf(temp_pdf)
    assert len(dates) >= 2
    found_dates = [
        d.format("DD-MM-YYYY") if isinstance(d, arrow.Arrow) else d for d in dates
    ]
    assert "12-01-2023" in found_dates
    assert "15-01-2024" in found_dates

def test_extract_dates_from_pdf_stream(temp_pdf_stream):
    dates = extract_dates_from_pdf(temp_pdf_stream)
    assert len(dates) >= 1
    found_dates = [
        d.format("DD-MM-YYYY") if isinstance(d, arrow.Arrow) else d for d in dates
    ]
    assert "12-01-2023" in found_dates

def test_extract_dates_invalid_type():
    with pytest.raises(ValueError, match="pdf_source must be a Path or BytesIO object"):
        extract_dates_from_pdf("invalid_type")
