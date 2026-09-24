"""json_to_bib without pandas: typst query JSON → label.bib."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
import yaml

from evid.core.bibtex_utils import json_to_bib


def _doc(tmp_path, *, uuid: str = "abcd1234ef", **info):
    workdir = tmp_path / uuid
    workdir.mkdir()
    payload = {
        "uuid": uuid,
        "title": "The Judgment",
        "authors": "High Court",
        "url": "https://example.com/j",
        "dates": "1978",
        **info,
    }
    (workdir / "info.yml").write_text(yaml.safe_dump(payload), encoding="utf-8")
    return workdir


def _write_json(workdir, values: list[dict]):
    path = workdir / "label.json"
    path.write_text(
        json.dumps([{"value": v} for v in values]),
        encoding="utf-8",
    )
    return path


def test_bibtex_utils_does_not_import_pandas_or_numpy():
    code = (
        "import sys\n"
        "import evid.core.bibtex_utils  # noqa: F401\n"
        "assert 'pandas' not in sys.modules\n"
        "assert 'numpy' not in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_json_to_bib_empty_raises(tmp_path):
    workdir = _doc(tmp_path)
    json_file = workdir / "label.json"
    json_file.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        json_to_bib(json_file, workdir / "label.bib", exclude_note=True)


def test_generate_bib_from_typ_empty_labels_is_ok(tmp_path, monkeypatch):
    """Unlabelled docs query to [] — that is not a BibTeX failure."""
    from evid.core.bibtex import generate_bib_from_typ

    typ = tmp_path / "label.typ"
    typ.write_text("// no labs\n", encoding="utf-8")

    def _run(*_args, **kwargs):
        kwargs["stdout"].write("[]")
        return subprocess.CompletedProcess(
            args=["typst", "query"], returncode=0, stderr=b""
        )

    monkeypatch.setattr("evid.core.bibtex.subprocess.run", _run)
    ok, msg = generate_bib_from_typ(typ)
    assert ok is True
    assert msg == ""


def test_generate_bib_from_typ_skips_query_without_labs(tmp_path, monkeypatch):
    """A fresh label.typ (no #lab calls) must not spawn typst at all."""
    from evid.core.bibtex import generate_bib_from_typ

    typ = tmp_path / "label.typ"
    typ.write_text(
        '#import "@preview/labtyp:0.1.0": lablist\n= Title\n\nbody\n#lablist()\n',
        encoding="utf-8",
    )
    called: list[int] = []
    monkeypatch.setattr(
        "evid.core.bibtex.subprocess.run", lambda *_a, **_k: called.append(1)
    )

    ok, msg = generate_bib_from_typ(typ)
    assert ok is True
    assert msg == ""
    assert called == []
    assert (tmp_path / "label.json").read_text(encoding="utf-8") == "[]"
    assert not (tmp_path / "label.bib").exists()


def test_generate_bib_from_typ_queries_when_labs_present(tmp_path, monkeypatch):
    """A labelled typ still runs typst query."""
    from evid.core.bibtex import generate_bib_from_typ

    typ = tmp_path / "label.typ"
    typ.write_text('#lab("lab1", "a quote", "")\n', encoding="utf-8")
    called: list[int] = []

    def _run(*_args, **kwargs):
        called.append(1)
        kwargs["stdout"].write("[]")
        return subprocess.CompletedProcess(
            args=["typst", "query"], returncode=0, stderr=b""
        )

    monkeypatch.setattr("evid.core.bibtex.subprocess.run", _run)
    ok, msg = generate_bib_from_typ(typ)
    assert ok is True
    assert msg == ""
    assert called == [1]


def test_json_to_bib_missing_key_raises(tmp_path):
    workdir = _doc(tmp_path)
    json_file = _write_json(workdir, [{"text": "no key here", "opage": 1}])
    with pytest.raises(ValueError, match="key"):
        json_to_bib(json_file, workdir / "label.bib", exclude_note=True)


def test_json_to_bib_writes_main_and_snippet(tmp_path):
    workdir = _doc(tmp_path)
    json_file = _write_json(
        workdir,
        [
            {
                "key": "intro",
                "text": "The appeal was dismissed.",
                "note": "held",
                "title": "The Judgment",
                "opage": 3,
                "date": "2024-03-15",
            }
        ],
    )
    out = workdir / "label.bib"
    json_to_bib(json_file, out, exclude_note=True)
    bib = out.read_text(encoding="utf-8")
    assert "@article{ abcd:main" in bib
    assert "title = {The Judgment}" in bib
    assert "author = {High Court}" in bib
    assert "date = {1978}" in bib
    assert "url = {https://example.com/j}" in bib
    assert "@article{ abcd:intro" in bib
    assert "title = {The appeal was dismissed.}" in bib
    assert "journal = {The Judgment}" in bib
    assert "nonote = {held}" in bib
    assert "note =" not in bib.replace("nonote", "")
    assert "date = {2024-03-15}" in bib
    assert "pages = {3}" in bib


def test_json_to_bib_exclude_note_false_keeps_note_key(tmp_path):
    workdir = _doc(tmp_path)
    json_file = _write_json(
        workdir, [{"key": "k", "text": "quote", "note": "n", "opage": 1}]
    )
    out = workdir / "label.bib"
    json_to_bib(json_file, out, exclude_note=False)
    bib = out.read_text(encoding="utf-8")
    assert "note = {n}" in bib
    assert "nonote" not in bib


def test_json_to_bib_skips_unparseable_snippet_date(tmp_path):
    workdir = _doc(tmp_path)
    json_file = _write_json(
        workdir,
        [{"key": "k", "text": "quote", "opage": 1, "date": "DATE"}],
    )
    out = workdir / "label.bib"
    json_to_bib(json_file, out, exclude_note=True)
    snippet = out.read_text(encoding="utf-8").split("@article{ abcd:k", 1)[1]
    assert "date =" not in snippet


def test_json_to_bib_year_only_snippet_date(tmp_path):
    workdir = _doc(tmp_path)
    json_file = _write_json(
        workdir,
        [{"key": "k", "text": "quote", "opage": 1, "date": "1978"}],
    )
    out = workdir / "label.bib"
    json_to_bib(json_file, out, exclude_note=True)
    snippet = out.read_text(encoding="utf-8").split("@article{ abcd:k", 1)[1]
    assert "date = {1978-01-01}" in snippet


def test_json_to_bib_omits_missing_opage(tmp_path):
    workdir = _doc(tmp_path)
    json_file = _write_json(workdir, [{"key": "k", "text": "quote"}])
    out = workdir / "label.bib"
    json_to_bib(json_file, out, exclude_note=True)
    snippet = out.read_text(encoding="utf-8").split("@article{ abcd:k", 1)[1]
    assert "pages =" not in snippet
