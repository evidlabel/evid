"""`gather` builds every export from label/labels.json and pass/ (evid 0.7)."""

import json
import re

import pytest
import yaml

from evid.core.gather import gather_dataset
from tests.labelkit import label_doc

INFO = {
    "uuid": "1a2b3c4d5e6f",
    "title": "Test Judgment",
    "authors": "Ann Berg, Carl Dahl, Eva Fisk",
    "dates": "13-06-1978",
    "url": "https://example.com/judgment",
}


def _make_dataset(tmp_path, labels=True, quotes=True):
    doc = tmp_path / "sets" / "demo" / "docs" / "1a2b3c4d5e6f"
    doc.mkdir(parents=True)
    (doc / "info.yml").write_text(yaml.safe_dump(INFO), encoding="utf-8")
    label_doc(
        doc,
        labels=[
            {
                "key": "intro",
                "text": "a manually labelled snippet",
                "note": "Why it matters.",
                "page": 1,
            }
        ]
        if labels
        else (),
        quotes=[
            {"text": "The appeal was therefore dismissed in its entirety.", "page": 2}
        ]
        if quotes
        else (),
    )
    return tmp_path, doc


def test_gather_yaml_labels_and_machine_quotes(tmp_path):
    root, doc = _make_dataset(tmp_path)
    out = tmp_path / "refs.yml"
    gather_dataset(root, "demo", out)
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    text = (doc / "label" / "text.txt").read_text(encoding="utf-8")

    assert set(data) == {"1a2b:main", "1a2b:intro", "1a2b:q1"}
    main = data["1a2b:main"]
    assert main["title"] == "Test Judgment" and str(main["date"]) == "1978-06-13"
    assert main["author"] == "Ann Berg and Carl Dahl and Eva Fisk"
    for key in ("1a2b:intro", "1a2b:q1"):
        item = data[key]
        a, b = map(
            int, re.fullmatch(r"chars (\d+)-(\d+)", item["serial-number"]).groups()
        )
        assert (
            text[a:b] == item["title"]
        )  # verbatim: the exact slice of the canonical text
        assert item["parent"]["title"] == "Test Judgment"
    assert (
        data["1a2b:intro"]["page-range"] == "1" and data["1a2b:q1"]["page-range"] == "2"
    )
    assert (
        data["1a2b:intro"]["note"] == "Why it matters."
        and "note" not in data["1a2b:q1"]
    )


def test_gather_machine_quote_note(tmp_path):
    root, doc = _make_dataset(tmp_path, labels=False)
    from evid.core.quote_pass import note_quote

    note_quote(doc, "q1", "Check the date.")
    out = tmp_path / "refs.yml"
    gather_dataset(root, "demo", out)
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["1a2b:q1"]["note"] == "Check the date."


def test_gather_machine_only_and_labels_only(tmp_path):
    root, _ = _make_dataset(tmp_path, labels=False)
    out = tmp_path / "m.yml"
    gather_dataset(root, "demo", out)
    assert set(yaml.safe_load(out.read_text())) == {"1a2b:main", "1a2b:q1"}


def test_gather_bib_md_json(tmp_path):
    root, _ = _make_dataset(tmp_path)
    bib = tmp_path / "refs.bib"
    gather_dataset(root, "demo", bib)
    t = bib.read_text(encoding="utf-8")
    assert "1a2b:q1" in t and "1a2b:intro" in t and "dismissed in its entirety" in t
    md = tmp_path / "refs.md"
    gather_dataset(root, "demo", md, include_keys=True)
    t = md.read_text(encoding="utf-8")
    assert (
        "a manually labelled snippet" in t
        and "### intro" in t
        and "*Note:* Why it matters." in t
    )
    js = tmp_path / "refs.json"
    gather_dataset(root, "demo", js)
    snip = json.loads(js.read_text())["1a2b3c4d5e6f"]["snippets"]
    assert (
        snip["1a2b:intro"]["kind"] == "label" and snip["1a2b:q1"]["kind"] == "machine"
    )


def test_gather_warns_about_unmigrated_documents(tmp_path, caplog):
    root, _ = _make_dataset(tmp_path)
    old = tmp_path / "sets" / "demo" / "docs" / "9f9f0000"
    old.mkdir()
    (old / "info.yml").write_text(yaml.safe_dump({"uuid": "9f9f0000", "title": "Old"}))
    (old / "label.typ").write_text('#lab("k", "x", "")')
    gather_dataset(root, "demo", tmp_path / "r.yml")
    assert "migrate-labels" in caplog.text


def test_gather_nothing_to_gather_exits(tmp_path):
    root, _ = _make_dataset(tmp_path, labels=False, quotes=False)
    with pytest.raises(SystemExit):
        gather_dataset(root, "demo", tmp_path / "x.yml")


def test_gather_prefixes_stay_distinct(tmp_path):
    """Two docs sharing the first uuid chars get distinct prefixes: labquote groups by prefix."""
    for uuid in ("1a2b0001", "1a2b0002"):
        doc = tmp_path / "sets" / "demo" / "docs" / uuid
        doc.mkdir(parents=True)
        (doc / "info.yml").write_text(
            yaml.safe_dump({"uuid": uuid, "title": f"Doc {uuid}"}), encoding="utf-8"
        )
        label_doc(doc, labels=[{"key": "a", "text": f"text {uuid}", "page": 1}])
    out = tmp_path / "refs.yml"
    gather_dataset(tmp_path, "demo", out)
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    prefixes = {k.split(":", 1)[0] for k in data}
    assert len(prefixes) == 2, prefixes  # not merged under one "1a2b"
    assert sum(len(p) > 4 for p in prefixes) == 1  # the second was widened


def test_merge_hayagriva_dedupes_by_key(tmp_path):
    from evid.core.gather import merge_hayagriva

    a = tmp_path / "a.yml"
    a.write_text(
        "0001:main:\n  type: article\n  title: Alpha\n0001:q1:\n  title: one\n",
        encoding="utf-8",
    )
    b = tmp_path / "b.yml"
    b.write_text(
        "0001:main:\n  title: Alpha DUP\n0002:q1:\n  title: two\n", encoding="utf-8"
    )
    out = tmp_path / "merged.yml"
    merged = merge_hayagriva([a, b], out)
    assert list(merged) == ["0001:main", "0001:q1", "0002:q1"]  # first-seen order
    assert merged["0001:main"]["title"] == "Alpha"  # first file wins
    assert yaml.safe_load(out.read_text(encoding="utf-8")) == merged
