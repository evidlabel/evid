"""`evid doc note` / `evid doc notes`."""

from __future__ import annotations

import json

import pytest
import yaml

import evid.cli.callbacks as cb
from evid.services.set_manager import SetManager


@pytest.fixture
def setdir(tmp_path, monkeypatch):
    sm = SetManager(tmp_path)
    s = sm.create_set("Case")
    d = s.path / "docs" / "u1"
    d.mkdir(parents=True)
    (d / "info.yml").write_text(
        yaml.safe_dump({"uuid": "u1", "title": "Judgment", "time_added": "2024-01-01"})
    )
    (d / "original.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(cb, "DIRECTORY", tmp_path)
    return d


def test_note_set_show_clear(setdir, capsys):
    cb.note_callback(
        dataset="case", uuid="u1", path="original.pdf", text="Signed copy."
    )
    cb.note_callback(
        dataset="case", uuid="u1", text="Key exhibit."
    )  # no -p: the document
    capsys.readouterr()
    cb.note_callback(dataset="case", uuid="u1", path="original.pdf")
    assert capsys.readouterr().out == "Signed copy.\n"
    cb.note_callback(dataset="case", uuid="u1")
    assert (
        capsys.readouterr().out == ".:\n  Key exhibit.\noriginal.pdf:\n  Signed copy.\n"
    )
    cb.note_callback(dataset="case", uuid="u1", path="original.pdf", clear=True)
    with pytest.raises(SystemExit) as e:
        cb.note_callback(dataset="case", uuid="u1", path="original.pdf")
    assert e.value.code == 1
    with pytest.raises(SystemExit, match="outside"):
        cb.note_callback(dataset="case", uuid="u1", path="../x", text="y")


def test_notes_listing_json_and_doc_list(setdir, capsys):
    cb.note_callback(dataset="case", uuid="u1", text="Key exhibit.")
    capsys.readouterr()
    cb.notes_callback(dataset="case", format="json")
    rows = json.loads(capsys.readouterr().out)
    assert rows == [
        {
            "uuid": "u1",
            "title": "Judgment",
            "path": ".",
            "note": "Key exhibit.",
            "missing": False,
        }
    ]
    cb.notes_callback(dataset="case", format="md")
    assert "- document: Key exhibit." in capsys.readouterr().out
    cb.list_docs_callback(dataset="case", format="json")
    assert json.loads(capsys.readouterr().out)[0]["note"] == "Key exhibit."


def test_evid_db_env_selects_the_data_dir(tmp_path, monkeypatch):
    """Inside the GUI's Agent pane EVID_DB points `evid` at the GUI's data dir."""
    import sys

    import evid.cli.main as m

    monkeypatch.setenv("EVID_DB", str(tmp_path / "db"))
    monkeypatch.setattr(sys, "argv", ["evid", "set", "list"])
    monkeypatch.setattr(type(m.app), "run", lambda _self: None)
    m.main()
    assert tmp_path / "db" == cb.DIRECTORY and cb.DIRECTORY_EXPLICIT is True


def test_evid_set_env_is_the_default_dataset(setdir, monkeypatch, capsys):
    """In a set's Agent pane EVID_SET makes -s optional."""
    monkeypatch.setenv("EVID_SET", "case")
    cb.note_callback(uuid="u1", text="From the agent pane.")
    capsys.readouterr()
    cb.note_callback(uuid="u1")
    assert "From the agent pane." in capsys.readouterr().out
