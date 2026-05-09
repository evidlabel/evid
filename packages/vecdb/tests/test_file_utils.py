"""Tests for file utilities."""

import os
import shutil

import pytest
from vecdb.utils.file_utils import get_label_files, snippetize_document


@pytest.fixture
def temp_dir():
    temp_path = "tests/temp_files"
    os.makedirs(temp_path, exist_ok=True)
    yield temp_path
    shutil.rmtree(temp_path)


def test_get_label_files(temp_dir):
    """Test getting label.typ files."""
    with open(os.path.join(temp_dir, "label.typ"), "w") as f:
        f.write("Test")
    files = get_label_files(temp_dir)
    assert len(files) == 1
    assert "label.typ" in files[0]


def test_snippetize_document(temp_dir):
    """Test splitting a document into paragraphs."""
    file_path = os.path.join(temp_dir, "label.typ")
    with open(file_path, "w") as f:
        f.write("Para1\n\nPara2")
    snippets = snippetize_document(file_path)
    assert len(snippets) == 2
    assert "Para1" in snippets[0]
