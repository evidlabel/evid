"""Tests for file utilities."""

import pytest
from vecdb.utils.file_utils import get_tex_files, snippetize_latex
import os
import shutil

@pytest.fixture
def temp_dir():
    temp_path = "tests/temp_files"
    os.makedirs(temp_path, exist_ok=True)
    yield temp_path
    shutil.rmtree(temp_path)

def test_get_tex_files(temp_dir):
    """Test getting .tex files."""
    with open(os.path.join(temp_dir, 'label.tex'), 'w') as f:
        f.write("Test")
    files = get_tex_files(temp_dir)
    assert len(files) == 1
    assert 'label.tex' in files[0]

def test_snippetize_latex(temp_dir):
    """Test snippetizing LaTeX content."""
    file_path = os.path.join(temp_dir, 'label.tex')
    with open(file_path, 'w') as f:
        f.write("\\begin{document}\nPara1\n\nPara2\n\\end{document}")
    snippets = snippetize_latex(file_path)
    assert len(snippets) == 2
    assert "Para1" in snippets[0]
