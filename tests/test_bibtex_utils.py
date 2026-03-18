"""Tests for bibtex_utils module."""

import json

import pytest
import yaml

from evid.core.bibtex_utils import (
    bib_escape,
    json_to_bib,
    load_authors,
    load_dates,
    load_title,
    load_url,
    load_uuid_prefix,
    remove_backslash_substrings,
    remove_curly_brace_content,
    replace_multiple_spaces,
    replace_underscores,
)

INFO = {
    "original_name": "doc.pdf",
    "uuid": "abcd1234",
    "time_added": "2023-01-01",
    "dates": "2023-01-01",
    "title": "Test Title",
    "authors": "Alice Bob",
    "tags": "",
    "label": "test_label",
    "url": "http://example.com",
}


@pytest.fixture
def info_dir(tmp_path):
    (tmp_path / "info.yml").write_text(yaml.dump(INFO))
    return tmp_path


def test_replace_multiple_spaces():
    assert replace_multiple_spaces("a  b   c") == "a b c"


def test_replace_multiple_spaces_typeerror():
    assert replace_multiple_spaces(None) == ""


def test_replace_underscores():
    assert replace_underscores("a_b_c") == "a b c"


def test_replace_underscores_typeerror():
    assert replace_underscores(None) == ""


def test_remove_curly_brace_content():
    assert remove_curly_brace_content("a{foo}b") == "ab"


def test_remove_curly_brace_content_typeerror():
    assert remove_curly_brace_content(None) == ""


def test_remove_backslash_substrings():
    assert remove_backslash_substrings(r"a\cmd b") == "a b"


def test_remove_backslash_substrings_typeerror():
    assert remove_backslash_substrings(None) == ""


def test_bib_escape():
    assert bib_escape('say "hi"') == 'say \\"hi\\"'
    assert bib_escape("a\\b") == "a\\\\b"


def test_load_uuid_prefix(info_dir):
    f = info_dir / "label.json"
    f.touch()
    assert load_uuid_prefix(f) == "abcd"


def test_load_uuid_prefix_no_file(tmp_path):
    assert load_uuid_prefix(tmp_path / "label.json") == ""


def test_load_url(info_dir):
    f = info_dir / "label.json"
    f.touch()
    assert load_url(f) == "http://example.com"


def test_load_url_no_file(tmp_path):
    assert load_url(tmp_path / "label.json") == ""


def test_load_authors(info_dir):
    f = info_dir / "label.json"
    f.touch()
    assert load_authors(f) == "Alice Bob"


def test_load_authors_no_file(tmp_path):
    assert load_authors(tmp_path / "label.json") == ""


def test_load_title(info_dir):
    f = info_dir / "label.json"
    f.touch()
    assert load_title(f) == "Test Title"


def test_load_title_no_file(tmp_path):
    assert load_title(tmp_path / "label.json") == ""


def test_load_dates(info_dir):
    f = info_dir / "label.json"
    f.touch()
    result = load_dates(f)
    assert "2023" in result


def test_load_dates_no_file(tmp_path):
    assert load_dates(tmp_path / "label.json") == ""


def test_json_to_bib_basic(info_dir):
    json_file = info_dir / "label.json"
    bib_file = info_dir / "label.bib"
    data = [
        {
            "value": {
                "key": "lab1",
                "text": "Some quote text",
                "title": "Section Title",
                "date": "2023-01-01",
                "note": "my note",
            }
        }
    ]
    json_file.write_text(json.dumps(data))
    json_to_bib(json_file, bib_file, exclude_note=False)
    content = bib_file.read_text()
    assert "@article" in content
    assert "Some quote text" in content
    assert "my note" in content


def test_json_to_bib_exclude_note(info_dir):
    json_file = info_dir / "label.json"
    bib_file = info_dir / "label.bib"
    data = [
        {
            "value": {
                "key": "lab1",
                "text": "Quote",
                "title": "Title",
                "date": "2023-01-01",
                "note": "secret",
            }
        }
    ]
    json_file.write_text(json.dumps(data))
    json_to_bib(json_file, bib_file, exclude_note=True)
    content = bib_file.read_text()
    assert "nonote" in content
    assert "secret" in content


def test_json_to_bib_with_pages(info_dir):
    json_file = info_dir / "label.json"
    bib_file = info_dir / "label.bib"
    data = [{"value": {"key": "lab1", "text": "Quote", "title": "T", "opage": 5}}]
    json_file.write_text(json.dumps(data))
    json_to_bib(json_file, bib_file, exclude_note=True)
    content = bib_file.read_text()
    assert "pages" in content


def test_json_to_bib_empty_raises(tmp_path):
    json_file = tmp_path / "label.json"
    bib_file = tmp_path / "label.bib"
    json_file.write_text("[]")
    with pytest.raises(ValueError):
        json_to_bib(json_file, bib_file, exclude_note=True)
