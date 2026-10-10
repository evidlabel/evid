"""Replacing a document in place (did re-handoff): labels follow, the lost ones are stale."""

import json
import subprocess
import sys

import pymupdf
import pytest
import yaml

from evid.core import labels
from evid.services import doc_replace


def _pdf(path, lines, title=""):
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line)
        y += 16
    if title:
        doc.set_metadata({"title": title})
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def doc(tmp_path):
    d = tmp_path / "sets" / "case-anon" / "docs" / "abc123"
    d.mkdir(parents=True)
    _pdf(
        d / "original.pdf",
        ["[PERSON 1] moved out of the flat.", "[ORGANIZATION 1] kept the deposit."],
    )
    (d / "info.yml").write_text(
        yaml.safe_dump(
            {"uuid": "abc123", "title": "[DOCUMENT 1]", "original_name": "original.pdf"}
        )
    )
    span, _, _ = labels.span_of(d, "[PERSON 1] moved out of the flat.")
    labels.add_label(d, span, "moved")
    span, _, _ = labels.span_of(d, "[ORGANIZATION 1] kept the deposit.")
    labels.add_label(d, span, "kept")
    return d


def test_replace_with_renames_keeps_every_label(doc, tmp_path):
    new = _pdf(
        tmp_path / "v2.pdf",
        [
            "A new first line.",
            "[PERSON 4] moved out of the flat.",
            "[ORGANIZATION 1] kept the deposit.",
        ],
        title="[DOCUMENT 2]",
    )
    r = doc_replace.replace(doc, new, {"[PERSON 1]": "[PERSON 4]"})
    assert r["stale"] == 0 and r["mapped"] == 1
    data = labels.read(doc)
    moved = next(x for x in data["labels"] if x["key"] == "moved")
    text, _ = labels.read_text(doc)
    assert (
        moved["text"]
        == "[PERSON 4] moved out of the flat."
        == text[moved["start"] : moved["end"]]
    )
    assert "lost" not in moved
    assert yaml.safe_load((doc / "info.yml").read_text())["title"] == "[DOCUMENT 2]"


def test_swapped_numbers_do_not_chain(doc, tmp_path):
    new = _pdf(
        tmp_path / "v2.pdf",
        ["[PERSON 2] moved out of the flat.", "[ORGANIZATION 1] kept the deposit."],
    )
    with labels._locked(doc) as data:  # a second person label to swap with
        pass
    r = doc_replace.replace(
        doc, new, {"[PERSON 1]": "[PERSON 2]", "[PERSON 2]": "[PERSON 1]"}
    )
    moved = next(x for x in labels.read(doc)["labels"] if x["key"] == "moved")
    assert moved["text"].startswith("[PERSON 2]") and r["stale"] == 0


def test_lost_labels_are_stale_then_repaired(doc, tmp_path):
    new = _pdf(
        tmp_path / "v2.pdf",
        ["The tenant left the apartment.", "[ORGANIZATION 1] kept the deposit."],
    )
    r = doc_replace.replace(doc, new, {})
    assert r["stale"] == 1
    rows = doc_replace.stale(doc.parent.parent)
    assert rows[0]["uuid"] == "abc123" and rows[0]["records"][0]["key"] == "moved"

    # a model that paraphrases is refused: the quote must be the document's own bytes
    refused = doc_replace.repair(
        doc, ask=lambda _prompt: '{"choice": 1, "text": "The tenant moved out."}'
    )
    assert refused == {"uuid": "abc123", "repaired": 0, "stale": 1}

    def ask(prompt):
        assert (
            "[PERSON 1] moved out of the flat." in prompt
            and "The tenant left the apartment." in prompt
        )
        n = next(
            line.split("]")[0].lstrip("[")
            for line in prompt.splitlines()
            if "The tenant left" in line
        )
        return json.dumps({"choice": int(n), "text": "The tenant left the apartment."})

    ok = doc_replace.repair(doc, ask=ask)
    assert ok["repaired"] == 1 and ok["stale"] == 0
    moved = next(x for x in labels.read(doc)["labels"] if x["key"] == "moved")
    text, _ = labels.read_text(doc)
    assert (
        moved["text"]
        == "The tenant left the apartment."
        == text[moved["start"] : moved["end"]]
    )
    assert moved["repaired"] and "lost" not in moved
    assert doc_replace.stale(doc.parent.parent) == []


def test_cli_replace_and_stale(doc, tmp_path):
    data_dir = tmp_path
    (data_dir / "sets" / "case-anon" / "set.yml").write_text(
        yaml.safe_dump({"name": "case-anon", "type": "anon"})
    )
    new = _pdf(
        tmp_path / "v2.pdf",
        ["Nothing alike here.", "[ORGANIZATION 1] kept the deposit."],
    )
    mp = tmp_path / "map.json"
    mp.write_text("{}")
    run = [sys.executable, "-m", "evid.cli.main", "--db", str(data_dir)]
    r = subprocess.run(
        [
            *run,
            "doc",
            "replace",
            "-s",
            "case-anon",
            "-u",
            "abc123",
            "--source",
            str(new),
            "--map",
            str(mp),
            "-f",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["stale"] == 1
    r = subprocess.run(
        [*run, "label", "stale", "-s", "case-anon", "-f", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(r.stdout)[0]["records"][0]["key"] == "moved"
