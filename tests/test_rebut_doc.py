import pytest
from unittest.mock import patch, call
import logging
from evid.core.rebut_doc import rebut_doc, base_rebuttal, write_rebuttal
import yaml


@pytest.fixture
def temp_workdir(tmp_path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    csv_content = (
        "label ; quote ; note ; section title ; section no ; page ; date ; opage\n"
        "test_label ; Test quote ; Test note ; Section 1 ; 1 ; 1 ; 2023-01-01 ; 0"
    )
    csv_file = workdir / "label.csv"
    csv_file.write_text(csv_content, encoding="utf-8")
    info_data = {
        "original_name": "test.pdf",
        "uuid": "test_uuid",
        "time_added": "2023-01-01",
        "dates": "2023-01-01",
        "title": "Test",
        "authors": "Author",
        "tags": "",
        "label": "test",
        "url": "http://example.com",
    }
    with (workdir / "info.yml").open("w", encoding="utf-8") as f:
        yaml.dump(info_data, f)
    yield workdir


@pytest.mark.parametrize(
    "bib_content",
    [
        """@article{test_uuid:test_label,
        nonote = {Test note},
        title = {Test quote},
        journal = {Section 1},
        date = {2023-01-01},
        pages = {1},
        url = {},
    }"""
    ],
)
def test_base_rebuttal(tmp_path, bib_content):
    bib_file = tmp_path / "label1.bib"
    bib_file.write_text(bib_content, encoding="utf-8")
    rebut_body = base_rebuttal(bib_file)
    assert "+ Regarding: #cite(<test_uuid:test_label>, form: \"full\")" in rebut_body
    assert "// Test note" in rebut_body
    assert f"#bibliography(\"{bib_file.name}\"" in rebut_body


def test_write_rebuttal(tmp_path):
    output_file = tmp_path / "rebut.typ"
    body = "Sample rebuttal content"
    write_rebuttal(body, output_file)
    assert output_file.exists()
    assert output_file.read_text(encoding="utf-8") == body


def test_write_rebuttal_existing_file(tmp_path):
    output_file = tmp_path / "rebut.typ"
    output_file.write_text("Existing content", encoding="utf-8")
    body = "New content"
    write_rebuttal(body, output_file)
    assert output_file.read_text(encoding="utf-8") == "Existing content"


@patch("subprocess.run")
def test_rebut_doc_success(mock_run, temp_workdir, caplog):
    caplog.set_level(logging.INFO)
    rebut_doc(temp_workdir)
    bib_file = temp_workdir / "label1.bib"
    rebut_file = temp_workdir / "rebut.typ"
    assert bib_file.exists(), f"Bib file {bib_file} not created"
    with bib_file.open("r", encoding="utf-8") as f:
        bib_content = f.read()
        assert "test_label" in bib_content, f"Expected label not found in {bib_content}"
        assert "Test quote" in bib_content, f"Expected quote not found in {bib_content}"
    assert rebut_file.exists(), f"Rebut file {rebut_file} not created"
    rebut_content = rebut_file.read_text(encoding="utf-8")
    assert (
        "+ Regarding: #cite" in rebut_content
    ), f"Expected citation not found in {rebut_content}"
    assert "Written a new" in caplog.text
    pdf_file = rebut_file.with_suffix(".pdf")
    mock_run.assert_has_calls([
        call(["typst", "compile", str(rebut_file), str(pdf_file)], check=True),
        call(["xdg-open", str(pdf_file)], check=True)
    ])


def test_rebut_doc_no_label(temp_workdir, caplog):
    (temp_workdir / "label.csv").unlink()
    with pytest.raises(FileNotFoundError) as exc_info:
        rebut_doc(temp_workdir)
    assert f"CSV file {temp_workdir / 'label.csv'} not found" in str(exc_info.value)
    assert "Failed to generate rebuttal" in caplog.text


def test_rebut_doc_empty_label(temp_workdir, caplog):
    (temp_workdir / "label.csv").write_text("", encoding="utf-8")
    with pytest.raises(ValueError) as exc_info:
        rebut_doc(temp_workdir)
    assert f"CSV file {temp_workdir / 'label.csv'} is empty" in str(exc_info.value)
    assert "Failed to generate rebuttal" in caplog.text

