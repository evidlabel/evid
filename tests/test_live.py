"""Live mode: the GUI notices changes made outside it (evid.web.live)."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest
import yaml

from evid.services.set_manager import SetManager
from evid.web.jobs import Events
from evid.web.live import DiskWatch, _is_watch_dir


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


def test_labels_and_passes_edited_outside(tmp_path):
    sm = SetManager(tmp_path)
    es = sm.create_set("Case")
    d = _doc(es.path, "a" * 32)
    (d / "label").mkdir()
    (d / "label" / "labels.json").write_text("{}\n")
    (d / "pass").mkdir()
    ev = Events()
    w = DiskWatch(tmp_path, ev)
    _bump(d / "label" / "labels.json", '{"labels":[{"key":"k"}]}\n')
    w.poll()
    (disk,) = _events(ev, "disk")
    changed = disk["changed"][0]
    assert changed["by"] == "outside" and "label/labels.json" in changed["files"]
    assert _events(ev, "labels_updated") == []  # nothing is extracted from a .typ
    ev2 = Events()
    w.events = ev2
    w.touch("case", "a" * 32)
    _bump(d / "pass" / "p1.json", "{}\n")
    w.poll()
    (disk,) = _events(ev2, "disk")
    assert disk["changed"][0]["by"] == "you" and "pass" in disk["changed"][0]["files"]


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


def test_watch_dirs_are_the_set_tree_only():
    root = Path("/data")
    assert _is_watch_dir(root, root / "sets")
    assert _is_watch_dir(root, root / "sets" / "litc")
    assert _is_watch_dir(root, root / "sets" / "litc" / "docs")
    assert _is_watch_dir(root, root / "sets" / "litc" / "docs" / "u")
    assert _is_watch_dir(root, root / "sets" / "litc" / "docs" / "u" / "label")
    assert _is_watch_dir(root, root / "sets" / "litc" / "docs" / "u" / "pass")
    assert _is_watch_dir(root, root / "plain" / "plain_set_case" / "docs" / "u")
    assert not _is_watch_dir(root, root / "sets" / "litc" / "vecdb")
    assert not _is_watch_dir(root, root / "sets" / "litc" / "vecdb" / "chroma")
    assert not _is_watch_dir(root, root / "other")
    assert not _is_watch_dir(root, root)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="inotify")
def test_watch_thread_sees_a_change_without_polling(tmp_path):
    """The thread must notice a write while its poll interval is still pending."""
    sm = SetManager(tmp_path)
    es = sm.create_set("Case")
    d = _doc(es.path, "a" * 32)
    ev = Events()
    w = DiskWatch(tmp_path, ev, interval=30)
    w.start()
    try:
        assert w._ready.wait(2)
        _bump(d / "info.yml", yaml.safe_dump({"title": "Edited outside"}))
        deadline = time.time() + 2
        while time.time() < deadline and not _events(ev, "disk"):
            time.sleep(0.02)
        (disk,) = _events(ev, "disk")
        assert disk["changed"][0]["by"] == "outside"
        assert disk["changed"][0]["files"] == ["info.yml"]

        (d / "label").mkdir()
        (d / "label" / "labels.json").write_text('{"labels": []}\n')
        deadline = time.time() + 2
        seen = []
        while time.time() < deadline:
            seen = [
                c
                for e in _events(ev, "disk")
                for c in e["changed"]
                if "label/labels.json" in c["files"]
            ]
            if seen:
                break
            time.sleep(0.02)
        assert seen and seen[0]["by"] == "outside"
    finally:
        w.stop()
        w._thread.join(2)
        assert not w._thread.is_alive()


def test_an_agents_reply_is_an_event(tmp_path):
    from evid.core import feedback

    sm = SetManager(tmp_path)
    es = sm.create_set("Case")
    _doc(es.path, "a" * 32)
    ev = Events()
    w = DiskWatch(tmp_path, ev)
    feedback.add(
        es.path, "a" * 32, "Check the date"
    )  # the GUI would touch first; this is "outside"
    w.poll()
    (e,) = _events(ev, "feedback")
    assert e["slug"] == "case" and e["by"] == "outside"
