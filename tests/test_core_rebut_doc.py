import pytest
from unittest.mock import patch
from evid.core.rebut_doc import base_rebuttal, write_rebuttal, rebut_doc


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
    rebut_body = base_rebuttal(bib_file)
    assert "// Test note" in rebut_body
    assert "#bcite(<test_uuid:test_label>)" in rebut_body


def test_write_rebuttal(temp_dir):
    rebut_file = temp_dir / "rebut.typ"
    body = "Test rebuttal content"
    write_rebuttal(body, rebut_file)
    assert rebut_file.exists()
    assert rebut_file.read_text() == body


def test_write_rebuttal_existing_file(temp_dir):
    rebut_file = temp_dir / "rebut.typ"
    rebut_file.write_text("Existing content")
    body = "New content"
    write_rebuttal(body, rebut_file)
    assert rebut_file.read_text() == "Existing content"


def test_rebut_doc(temp_dir):
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
    with patch("evid.core.rebut_doc.generate_bib_from_typ", return_value=(True, "")):
        with patch("subprocess.run"):
            rebut_doc(workdir)
    rebut_file = workdir / "rebut.typ"
    assert rebut_file.exists()


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
