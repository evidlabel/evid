import pytest
from unittest.mock import patch, call
import logging
from evid.core.rebut_doc import rebut_doc, base_rebuttal, write_rebuttal
import yaml
import json
import os
from unittest.mock import ANY


@pytest.fixture
def temp_workdir(tmp_path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    typ_content = """#import "@local/labtyp:0.1.0": lablist, lab, mset

#mset(values: (title: "Test Title", date: "2023-01-01"))

= Test Title

Test content

= List of Labels
#lablist()
"""
    typ_file = workdir / "label.typ"
    typ_file.write_text(typ_content, encoding="utf-8")
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
    bib_file = tmp_path / "label.bib"
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

    def side_effect(*args, **kwargs):
        if args[0][0] == "code":
            return mock.MagicMock(returncode=0)
        elif args[0][0] == "typst":
            if "stdout" in kwargs:
                stdout_file = kwargs["stdout"]
                json_content = json.dumps([{"value": {"key": "test_label", "text": "Test quote", "date": "2023-01-01", "opage": 1, "title": "Test Title", "note": "Test note"}}])
                stdout_file.write(json_content)
                stdout_file.close()
            return mock.MagicMock(returncode=0, stderr=b"")
        return mock.MagicMock(returncode=0)

    mock_run.side_effect = side_effect

    rebut_doc(temp_workdir)
    bib_file = temp_workdir / "label.bib"
    rebut_file = temp_workdir / "rebut.typ"
    assert bib_file.exists(), f"Bib file {bib_file} not created"
    with bib_file.open("r", encoding="utf-8") as f:
        bib_content = f.read()
        assert "@article" in bib_content, f"Expected entry not found in {bib_content}"
    assert rebut_file.exists(), f"Rebut file {rebut_file} not created"
    rebut_content = rebut_file.read_text(encoding="utf-8")
    assert (
        "+ Regarding: #cite" in rebut_content
    ), f"Expected citation not found in {rebut_content}"
    assert "Written a new" in caplog.text
    json_file = temp_workdir / "label.json"
    typ_file = temp_workdir / "label.typ"
    mock_run.assert_has_calls([
        call(
            [
                "typst",
                "query",
                str(typ_file),
                "<lab>",
                "--package-path",
                os.path.expanduser("~/.cache/typst"),
            ],
            stdout=ANY,
            stderr=subprocess.PIPE,
            check=False,
        ),
        call(["code", str(rebut_file)], check=True)
    ])


def test_rebut_doc_no_label(temp_workdir, caplog):
    (temp_workdir / "label.typ").unlink()
    with pytest.raises(RuntimeError) as exc_info:
        rebut_doc(temp_workdir)
    assert "Typst file" in str(exc_info.value)
    assert "does not exist" in str(exc_info.value)
    assert "Failed to generate rebuttal" in caplog.text


def test_rebut_doc_empty_label(temp_workdir, caplog):
    (temp_workdir / "label.typ").write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError) as exc_info:
        rebut_doc(temp_workdir)
    assert "Skipped empty Typst file" in str(exc_info.value)
    assert "Failed to generate rebuttal" in caplog.text




