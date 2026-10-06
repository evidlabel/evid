"""`evid label` and `evid doc label` (evid 0.7 spans, no label.typ)."""

from __future__ import annotations

import json

import pytest
import yaml

import evid.cli.callbacks as cb
from evid.cli.label_cmd import (
    format_canonical,
    label_add_callback,
    label_annotate_callback,
    label_ls_callback,
    label_note_callback,
    label_rename_callback,
    label_rm_callback,
    label_text_callback,
    write_paragraph_labels,
)
from evid.core.labels import read


@pytest.fixture
def setdir(tmp_path, monkeypatch):
    from evid.services.set_manager import SetManager

    sm = SetManager(tmp_path)
    s = sm.create_set("Case")
    d = s.path / "docs" / "u1"
    d.mkdir(parents=True)
    (d / "info.yml").write_text(
        yaml.safe_dump({"uuid": "u1", "title": "Judgment", "time_added": "2024-01-01"})
    )
    (d / "source.txt").write_text(
        "Page one says hello.\nThe board finds that the municipality did not\n"
        "investigate the case.\n\nPage two: the end.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cb, "DIRECTORY", tmp_path)
    # label_cmd captured DIRECTORY at import, so point that binding too.
    import evid.cli.label_cmd as lc

    monkeypatch.setattr(lc, "DIRECTORY", tmp_path)
    return d


def test_add_note_rename_rm_and_list(setdir, capsys, monkeypatch):
    commits = []
    monkeypatch.setattr(
        "evid.cli.label_cmd.commit_labels", lambda _d, message: commits.append(message)
    )
    label_add_callback(
        dataset="case", uuid="u1", text="the municipality did not", note="the holding"
    )
    out = capsys.readouterr().out
    assert "the-municipality-did  page 1" in out
    label_note_callback(
        dataset="case", uuid="u1", key="the-municipality-did", text="second"
    )
    label_rename_callback(
        dataset="case", uuid="u1", key="the-municipality-did", new="holding"
    )
    capsys.readouterr()
    label_ls_callback(dataset="case", format="json")
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["key"] == "holding"
    assert rows[0]["notes"] == 2
    assert rows[0]["text"].startswith("the municipality did not")
    label_rm_callback(dataset="case", uuid="u1", key="holding")
    assert read(setdir)["labels"] == []
    assert commits[0].startswith("label: Judgment (+the-municipality-did)")
    assert any("holding" in m and "->" in m for m in commits)


def test_fuzzy_ratio_is_shown_and_a_miss_is_refused(setdir, capsys):
    label_add_callback(
        dataset="case",
        uuid="u1",
        text="the municipalty did not investigate the case",
        key="m",
    )
    out = capsys.readouterr().out
    assert "m  page 1  fuzzy " in out
    with pytest.raises(SystemExit, match="not in the document"):
        label_add_callback(dataset="case", uuid="u1", text="nothing like this at all")


def test_annotate_and_page_text(setdir, capsys):
    label_annotate_callback(
        dataset="case", uuid="u1", text="Page two: the end.", comment="closing line"
    )
    out = capsys.readouterr().out
    ann = read(setdir)["annotations"]
    assert len(ann) == 1 and ann[0]["id"] in out
    assert ann[0]["notes"][0]["text"] == "closing line"
    label_text_callback(dataset="case", uuid="u1", page=1)
    text = capsys.readouterr().out
    assert text.startswith("— page 1 —")
    assert "hello" in text
    with pytest.raises(SystemExit, match="No page 2"):
        label_text_callback(dataset="case", uuid="u1", page=2)


def test_paragraph_labels_on_add(setdir, capsys):
    n = write_paragraph_labels(setdir)
    assert n == 2
    assert [r["key"] for r in read(setdir)["labels"]] == ["lab1", "lab2"]
    assert "Labelled 2 paragraph(s)" in capsys.readouterr().out


def test_doc_label_headless_prints_the_commands(setdir, capsys, monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    def boom(*_a, **_k):
        raise AssertionError("the GUI must stay closed without a display")

    monkeypatch.setattr("evid.web.server.serve_gui", boom)
    cb.label_callback(dataset="case", uuid="u1")
    out = capsys.readouterr().out
    assert 'evid label add -s case -u u1 --text "verbatim passage"' in out


def test_doc_label_with_a_display_opens_that_document(setdir, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":1")
    opened = {}

    def fake(config, **kw):
        opened["dir"] = config.data_dir
        opened.update(kw)

    monkeypatch.setattr("evid.web.server.serve_gui", fake)
    cb.label_callback(dataset="case", uuid="u1")
    assert opened["open_at"] == {"set": "case", "doc": "u1", "pane": "label"}


def test_bibtex_command_is_gone_and_label_group_is_there():
    from evid.cli.main import app, doc_group

    assert "bibtex" not in [c.name for c in doc_group.commands]
    group = next(g for g in app.subgroups if g.name == "label")
    assert {c.name for c in group.commands} == {
        "ls",
        "add",
        "note",
        "rm",
        "rename",
        "annotate",
        "text",
    }


def test_format_canonical_marks_pages():
    text = "aaa\nbbb"
    out = format_canonical(text, [[0, 1], [4, 2]])
    assert "— page 1 —" in out and "aaa" in out
    assert "— page 2 —" in out and "bbb" in out
    assert "aaa" not in format_canonical(text, [[0, 1], [4, 2]], page=2)
