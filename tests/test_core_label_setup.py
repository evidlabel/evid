from evid.core.label_setup import (
    clean_text_for_typst,
    textpdf_to_typst,
    text_to_typst,
    json_to_bib,
    load_uuid_prefix,
    load_url,
)
import fitz
import yaml
import json
from unittest.mock import patch


def test_clean_text_for_typst():
    text = "Line with @mention\nSentence ending.\nAnother line."
    cleaned = clean_text_for_typst(text)
    assert "// Line with @mention" in cleaned
    assert "\n\n" in cleaned


def test_textpdf_to_typst(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((100, 100), "Test text")
    doc.save(pdf_path)
    typst_content = textpdf_to_typst(pdf_path)
    assert "= NAME" in typst_content
    assert "Test text" in typst_content


def test_text_to_typst(tmp_path):
    txt_path = tmp_path / "test.txt"
    txt_path.write_text("Test text")
    typst_content = text_to_typst(txt_path)
    assert "= NAME" in typst_content
    assert "Test text" in typst_content


def test_json_to_bib(tmp_path):
    json_path = tmp_path / "label.json"
    bib_path = tmp_path / "label.bib"
    data = [
        {
            "value": {
                "key": "key1",
                "text": "quote",
                "title": "title",
                "date": "2023-01-01",
                "opage": 1,
                "note": "note",
            }
        }
    ]
    json_path.write_text(json.dumps(data))
    with patch("evid.core.label_setup.load_uuid_prefix", return_value="uuid"):
        with patch("evid.core.label_setup.load_url", return_value="http://example.com"):
            json_to_bib(json_path, bib_path, True)
    assert bib_path.exists()
    content = bib_path.read_text()
    assert "uuid:key1" in content
    assert "nonote = {note}" in content


def test_load_uuid_prefix(tmp_path):
    info_path = tmp_path / "info.yml"
    info_data = {
        "original_name": "test.pdf",
        "uuid": "uuid123",
        "time_added": "2023-01-01",
        "dates": "2023-01-01",
        "title": "Test",
        "authors": "Author",
        "tags": "",
        "label": "test",
        "url": "",
    }
    info_path.write_text(yaml.dump(info_data))
    assert load_uuid_prefix(info_path) == "uuid"


def test_load_url(tmp_path):
    info_path = tmp_path / "info.yml"
    info_data = {
        "original_name": "test.pdf",
        "uuid": "uuid123",
        "time_added": "2023-01-01",
        "dates": "2023-01-01",
        "title": "Test",
        "authors": "Author",
        "tags": "",
        "label": "test",
        "url": "http://example.com",
    }
    info_path.write_text(yaml.dump(info_data))
    assert load_url(info_path) == "http://example.com"
