"""Live mode: the GUI notices changes made outside it (evid.web.live)."""

from __future__ import annotations

import os
import time

import yaml

from evid.services.set_manager import SetManager
from evid.web.jobs import Events
from evid.web.live import DiskWatch


def _doc(set_path, uuid, title="T"):
    d = set_path / "docs" / uuid
    d.mkdir(parents=True)
    (d / "info.yml").write_text(
        yaml.safe_dump({"uuid": uuid, "title": title, "label": title})
    )
    return d


def _bump(p, text=None):
    """Write (or touch) with a clearly newer mtime, so tests do not depend on clock resolution."""
    if text is not None:
        p.write_text(text)
    t = time.time() + 2
    os.utime(p, (t, t))


def _events(ev, kind):
    return [e for e in ev.since(0)[1] if e["kind"] == kind]


def test_outside_and_own_changes(tmp_path):
    sm = SetManager(tmp_path)
    es = sm.create_set("Case")
    a, b = _doc(es.path, "a" * 32), _doc(es.path, "b" * 32)
    ev = Events()
    w = DiskWatch(tmp_path, ev)
    w.poll()
    assert _events(ev, "disk") == []  # nothing changed yet

    _bump(
        a / "info.yml", yaml.safe_dump({"title": "Cleaned up by the agent"})
    )  # an agent
    w.touch("case", "b" * 32)
    _bump(b / "info.yml", yaml.safe_dump({"title": "Saved in the GUI"}))  # the GUI
    w.poll()
    (disk,) = _events(ev, "disk")
    by = {c["uuid"][0]: (c["by"], c["files"]) for c in disk["changed"]}
    assert by["a"] == ("outside", ["info.yml"])
    assert by["b"][0] == "you"


def test_added_removed_and_sets(tmp_path):
    sm = SetManager(tmp_path)
    es = sm.create_set("Case")
    _doc(es.path, "a" * 32)
    ev = Events()
    w = DiskWatch(tmp_path, ev)
    _doc(es.path, "c" * 32)
    import shutil

    shutil.rmtree(es.path / "docs" / ("a" * 32))
    sm.create_set("Other")
    (tmp_path / "tags.yml").write_text("[]")
    w.poll()
    (disk,) = _events(ev, "disk")
    assert [x["uuid"][0] for x in disk["added"]] == ["c"] and [
        x["uuid"][0] for x in disk["removed"]
    ] == ["a"]
    assert _events(ev, "sets_changed") and _events(ev, "tags_changed")


def test_label_typ_edited_outside_is_extracted_again(tmp_path):
    sm = SetManager(tmp_path)
    es = sm.create_set("Case")
    d = _doc(es.path, "a" * 32)
    (d / "label.typ").write_text("no labels\n")
    (d / "label.json").write_text("[]")
    ev = Events()
    w = DiskWatch(tmp_path, ev)
    _bump(d / "label.typ", "still no labels, edited by an agent\n")
    w.poll()
    assert _events(ev, "labels_updated")  # label.json rebuilt
    assert (d / "label.json").stat().st_mtime_ns >= 0
    ev2 = Events()
    w.events = ev2
    w.poll()
    assert _events(ev2, "disk") == []  # our own rebuild is not reported as a change


def test_indexing_is_not_an_outside_change(tmp_path, monkeypatch):
    from evid.web.jobs import IndexQueue

    sm = SetManager(tmp_path)
    es = sm.create_set("Case")
    d = _doc(es.path, "a" * 32)
    ev = Events()
    w = DiskWatch(tmp_path, ev)

    class Rec:
        def index_existing(self, doc_dir, _es):
            _bump(doc_dir / "evid_meta.yml", "indexed: true\n")
            return True

    q = IndexQueue(ev, on_write=w.touch)
    monkeypatch.setattr(q, "_make_ingester", lambda: (Rec(), False))
    q.enqueue(d, es)
    q.stop()
    w.poll()
    (disk,) = _events(ev, "disk")
    assert disk["changed"][0]["by"] == "you"
