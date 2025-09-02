from evid.core.pdf_metadata import extract_pdf_metadata
from io import BytesIO

MINIMAL_PDF = b"%PDF-1.0\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 3 3]>>endobj xref 0 4\n0000000000 65535 f\n0000000010 00000 n\n0000000053 00000 n\n0000000102 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref 149 %%EOF"


def test_extract_pdf_metadata_bytes():
    pdf_file = BytesIO(MINIMAL_PDF)
    title, authors, date = extract_pdf_metadata(pdf_file, "test.pdf")
    assert title == "test"
    assert authors == ""
    assert date == ""


def test_extract_pdf_metadata_file(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(MINIMAL_PDF)
    title, authors, date = extract_pdf_metadata(pdf_path, "test.pdf")
    assert title == "test"
    assert authors == ""
    assert date == ""
