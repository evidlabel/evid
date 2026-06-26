"""Tests for --since/--until addition-date filtering in `gather`."""

import datetime
import json

import pytest
import yaml
from evid.core.gather import (
    _names_in_range,
    _parse_date_spec,
    gather_dataset,
)

TODAY = _parse_date_spec("today")
YESTERDAY = TODAY - datetime.timedelta(days=1)
OLD = TODAY - datetime.timedelta(days=10)


def _bib(prefix: str, snippet: str) -> str:
    return (
        f"@article{{ {prefix}:main ,\n"
        f"  title = {{Doc {prefix}}},\n"
        f"}}\n"
        f"@article{{{prefix}:s1,\n"
        f"  title = {{{snippet}}},\n"
        f"  pages = {{1}}\n"
        f"}}\n"
    )


def _add_doc(docs, uuid, title, time_added, snippet):
    doc = docs / uuid
    doc.mkdir(parents=True)
    info = {"uuid": uuid, "title": title, "time_added": time_added.isoformat()}
    (doc / "info.yml").write_text(yaml.safe_dump(info), encoding="utf-8")
    (doc / "label.bib").write_text(_bib(uuid[:4], snippet), encoding="utf-8")


def _make_dataset(tmp_path):
    docs = tmp_path / "sets" / "demo" / "docs"
    _add_doc(docs, "aaaa1111", "Today doc", TODAY, "today snippet")
    _add_doc(docs, "bbbb2222", "Yesterday doc", YESTERDAY, "yesterday snippet")
    _add_doc(docs, "cccc3333", "Old doc", OLD, "old snippet")
    return tmp_path, docs


def test_parse_date_spec_keywords():
    assert _parse_date_spec("today") == TODAY
    assert _parse_date_spec("yesterday") == YESTERDAY
    assert _parse_date_spec("3d") == TODAY - datetime.timedelta(days=3)
    assert _parse_date_spec("3") == TODAY - datetime.timedelta(days=3)
    assert _parse_date_spec("2026-06-01") == datetime.date(2026, 6, 1)


def test_parse_date_spec_invalid():
    with pytest.raises(SystemExit):
        _parse_date_spec("not-a-date")


def test_names_in_range_since_yesterday(tmp_path):
    _, docs = _make_dataset(tmp_path)
    names = _names_in_range(docs, YESTERDAY, TODAY)
    assert names == {"aaaa1111", "bbbb2222"}


def test_names_in_range_literal_window(tmp_path):
    _, docs = _make_dataset(tmp_path)
    names = _names_in_range(docs, OLD, OLD)
    assert names == {"cccc3333"}


def test_gather_md_since_yesterday(tmp_path):
    root, _ = _make_dataset(tmp_path)
    out = tmp_path / "recent.md"
    gather_dataset(root, "demo", out, regen=False, since="yesterday")
    text = out.read_text(encoding="utf-8")
    assert "Today doc" in text
    assert "Yesterday doc" in text
    assert "Old doc" not in text


def test_gather_json_since_yesterday(tmp_path):
    root, _ = _make_dataset(tmp_path)
    out = tmp_path / "recent.json"
    gather_dataset(root, "demo", out, regen=False, since="yesterday")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data) == {"aaaa1111", "bbbb2222"}


def test_gather_no_filter_includes_all(tmp_path):
    root, _ = _make_dataset(tmp_path)
    out = tmp_path / "all.json"
    gather_dataset(root, "demo", out, regen=False)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data) == {"aaaa1111", "bbbb2222", "cccc3333"}


def test_gather_empty_range_exits(tmp_path):
    root, _ = _make_dataset(tmp_path)
    out = tmp_path / "none.json"
    future = (TODAY + datetime.timedelta(days=5)).isoformat()
    with pytest.raises(SystemExit):
        gather_dataset(root, "demo", out, regen=False, since=future)
