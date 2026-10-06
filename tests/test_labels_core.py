"""Plain-text labels: spans, labels.json, scoped git commits (evid 0.7)."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from evid.core import labels
from evid.core.gitops import commit_labels
from evid.core.spans import locate, make_span, page_for_offset, reanchor

TEXT = "Page one says hello.\nThe board finds that the municipality did not\ninvestigate the case.\nPage two: the end.\n"
PAGES = [[0, 1], [TEXT.index("Page two"), 2]]


@pytest.fixture
def doc(tmp_path):
    d = tmp_path / "docs" / "u1"
    d.mkdir(parents=True)
    labels._write_text(d, TEXT, PAGES)
    return d


def test_make_span_trims_and_pages():
    i = TEXT.index("Page two")
    s = make_span(TEXT, i - 1, i + 8, PAGES)
    assert (
        s["text"] == "Page two"
        and s["page"] == 2
        and s["prefix"].endswith("case.\n")
        and s["suffix"].startswith(":")
    )
    assert page_for_offset(0, PAGES) == 1
    with pytest.raises(ValueError, match="outside"):
        make_span(TEXT, 5, 999, PAGES)


def test_locate_exact_spaces_fuzzy():
    assert locate("hello", TEXT)[3] == "exact"
    s, e, _, how = locate(
        "municipality did not investigate", TEXT
    )  # line break in the text
    assert how == "spaces" and TEXT[s:e] == "municipality did not\ninvestigate"
    s, e, score, how = locate("the municipalty did not investigate the case", TEXT)
    assert how == "fuzzy" and score >= 0.92 and "municipality" in TEXT[s:e]
    assert locate("nothing like this at all", TEXT) is None


def test_reanchor_after_reextraction():
    span = make_span(
        TEXT, TEXT.index("investigate"), TEXT.index("investigate") + 11, PAGES
    ) | {"key": "k"}
    new_text = "A new first line.\n" + TEXT
    moved, how = reanchor(span, new_text, [[0, 1]])
    assert (
        how == "moved"
        and moved["key"] == "k"
        and new_text[moved["start"] : moved["end"]] == "investigate"
    )
    assert reanchor(span, TEXT, PAGES)[1] == "same"
    assert reanchor(span, "completely different", [[0, 1]]) == (None, "lost")


def test_labels_notes_annotations(doc):
    span, score, how = labels.span_of(
        doc, "the municipality did not investigate the case"
    )
    assert how == "spaces" and score == 1.0
    rec = labels.add_label(doc, span, "deadline", note="Key finding.")
    assert rec["notes"][0]["text"] == "Key finding." and rec["by"] == "you"
    labels.add_note(doc, "deadline", "Checked against the letter.", by="agent")
    with pytest.raises(ValueError, match="already"):
        labels.add_label(doc, span, "deadline")
    with pytest.raises(ValueError, match="bad label key"):
        labels.add_label(doc, span, "has space")
    ann = labels.add_annotation(doc, labels.span_at(doc, 0, 10), "Odd header", by="you")
    labels.annotate(doc, ann["id"], "it is the letterhead")
    data = labels.read(doc)
    assert [n["by"] for n in data["labels"][0]["notes"]] == ["you", "agent"]
    assert [n["text"] for n in data["annotations"][0]["notes"]] == [
        "Odd header",
        "it is the letterhead",
    ]
    ((key, value),) = labels.label_entries(doc)
    assert (
        key == "deadline"
        and value["note"] == "Key finding.\nChecked against the letter."
        and value["opage"] == 1
    )
    labels.rename_label(doc, "deadline", "board-finding")
    labels.remove_annotation(doc, ann["id"])
    labels.remove_label(doc, "board-finding")
    assert labels.read(doc)["labels"] == [] and labels.read(doc)["annotations"] == []
    with pytest.raises(KeyError):
        labels.add_note(doc, "nope", "x")


def test_unmapped_glyph_cannot_be_labelled(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    labels._write_text(d, "kvali�cerede personale", [[0, 1]])
    with pytest.raises(ValueError, match="not text"):
        labels.span_at(d, 0, 12)


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_saving_commits_only_label_and_pass(doc, tmp_path):
    root = tmp_path
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@x",
    }
    import os

    def run(*a):
        return subprocess.run(
            ["git", *a],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, **env},
        )

    run("init", "-q")
    (root / "other.txt").write_text("staged by you")
    run("add", "other.txt")
    span, _, _ = labels.span_of(doc, "hello")
    labels.add_label(doc, span, "greeting")
    os.environ.update(env)
    try:
        h = commit_labels(doc, "label: test (+greeting)")
    finally:
        for k in env:
            os.environ.pop(k, None)
    assert h
    files = run("show", "--name-only", "--format=", "HEAD").stdout.split()
    assert (
        all(f.startswith("docs/u1/label/") for f in files)
        and "docs/u1/label/labels.json" in files
    )
    assert not any(f.endswith((".lock", ".tmp")) for f in files)
    assert (
        "other.txt" in run("diff", "--cached", "--name-only").stdout
    )  # still staged, not committed
    assert commit_labels(doc, "again") is None  # nothing new
