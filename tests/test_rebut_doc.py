import pytest
from unittest.mock import patch
from evid.core.rebut_doc import base_rebuttal, write_rebuttal, rebut_doc
from evid import CONFIG


@pytest.fixture
def temp_dir(tmp_path):
    return tmp_path


def test_base_rebuttal(temp_dir):
    bib_file = temp_dir / "label.bib"
    bib_content = """@article{test_uuid:test_label,
        nonote = {Test note},
        title = {Test quote},
        journal = {Section 1},
        date = {2023-01-01},
        pages = {1},
        url = {},
    }"""
    bib_file.write_text(bib_content)
    result = base_rebuttal(bib_file)
    assert "// Test note" in result
    assert "#bcite(<test_uuid:test_label>)" in result


def test_write_rebuttal(temp_dir):
    output_file = temp_dir / "rebut.typ"
    body = "Test body"
    write_rebuttal(body, output_file)
    assert output_file.exists()
    assert output_file.read_text() == body


def test_write_rebuttal_existing_file(temp_dir):
    output_file = temp_dir / "rebut.typ"
    output_file.write_text("Existing content")
    body = "New body"
    write_rebuttal(body, output_file)
    assert output_file.read_text() == "Existing content"


@patch("evid.core.bibtex.generate_bib_from_typ", return_value=(True, ""))
@patch("evid.core.rebut_doc.subprocess.run")
def test_rebut_doc_success(mock_run, mock_gen, temp_dir):
    workdir = temp_dir / "workdir"
    workdir.mkdir()
    typ_file = workdir / "label.typ"
    typ_file.write_text("content")
    bib_file = workdir / "label.bib"
    bib_file.write_text("""@article{test_id,
        nonote = {Test note},
        title = {quote},
        journal = {journal},
        date = {2023-01-01},
        pages = {1},
    }""")
    rebut_file = workdir / "rebut.typ"
    rebut_doc(workdir)
    assert rebut_file.exists()
    mock_run.assert_called_with([CONFIG["editor"], str(rebut_file)], check=True)
    mock_gen.assert_called_with(typ_file)


def test_rebut_doc_no_label(temp_dir):
    workdir = temp_dir / "workdir"
    workdir.mkdir()
    with pytest.raises(RuntimeError):
        rebut_doc(workdir)


def test_rebut_doc_empty_label(temp_dir):
    workdir = temp_dir / "workdir"
    workdir.mkdir()
    typ_file = workdir / "label.typ"
    typ_file.write_text("")
    with pytest.raises(RuntimeError):
        rebut_doc(workdir)
