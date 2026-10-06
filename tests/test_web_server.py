"""The GUI server (evid.web.server): a real server on a free port, called over HTTP."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from urllib.error import HTTPError as URLHTTPError
from urllib.request import Request, urlopen

import pymupdf
import pytest
import yaml

from evid.config import EvidConfig
from evid.web import server as web
from evid.web.jobs import Events, IndexQueue, LabelWatcher
from tests.labelkit import label_doc


def _make_pdf(path: Path, text: str) -> Path:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    a = web.EvidApp(EvidConfig(data_dir=tmp_path / "data", editor="true"))
    a.has_vec = False
    a.attach_log()
    yield a
    a.shutdown()


@pytest.fixture
def server(app, monkeypatch):
    monkeypatch.setattr(web.Handler, "app", app, raising=False)
    monkeypatch.setattr(web.Handler, "window", None)
    srv = web.Server(("127.0.0.1", 0), web.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    srv.server_close()


def call(base, method, path, body=None, headers=None):
    h = {"X-Evid": "1", **(headers or {})}
    data = json.dumps(body).encode() if body is not None else None
    if data is not None:
        h["Content-Type"] = "application/json"
    req = Request(base + path, data=data, method=method, headers=h)
    try:
        with urlopen(req, timeout=10) as r:
            raw, ctype, status = r.read(), r.headers["Content-Type"], r.status
    except URLHTTPError as e:
        raw, ctype, status = e.read(), e.headers["Content-Type"], e.code
    return status, (
        json.loads(raw) if ctype.startswith("application/json") else raw.decode()
    )


def wait_job(base, jid, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, r = call(base, "GET", "/api/events?since=0")
        for e in r["events"]:
            if e["kind"] == "job" and e["job_id"] == jid and e["state"] != "running":
                return e
        time.sleep(0.05)
    raise AssertionError(f"job {jid} did not finish")


def ingest(base, slug, pdf, **fields):
    _, r = call(base, "POST", "/api/ingest", {"slug": slug, "path": str(pdf), **fields})
    e = wait_job(base, r["job"])
    assert e["state"] == "done", e
    return e["result"]


@pytest.fixture
def doc(server, tmp_path):
    call(server, "POST", "/api/sets", {"name": "Case"})
    pdf = _make_pdf(tmp_path / "a.pdf", "Hello evidence world")
    r = ingest(server, "case", pdf, title="A title", tags=["case.x"])
    return r["uuid"]


def test_page_and_assets(server):
    status, page = call(server, "GET", "/")
    assert status == 200 and '"data_dir"' in page and "/*EVID_CONFIG*/" not in page
    assert call(server, "GET", "/assets/evid.svg")[0] == 200
    assert call(server, "GET", "/assets/nope.js")[0] == 404
    assert call(server, "GET", "/api/config")[1]["has_vec"] is False


def test_guards(server):
    req = Request(server + "/api/sets", data=b"{}", method="POST")
    with pytest.raises(URLHTTPError) as e:
        urlopen(req, timeout=5)
    assert e.value.code == 403
    assert call(server, "GET", "/api/sets", headers={"Host": "evil.example"})[0] == 403
    req = Request(
        server + "/api/sets", data=b"{bad", method="POST", headers={"X-Evid": "1"}
    )
    with pytest.raises(URLHTTPError) as e:
        urlopen(req, timeout=5)
    assert e.value.code == 400
    assert call(server, "POST", "/api/nope", {})[0] == 404
    assert call(server, "GET", "/api/sets/..%2Fx/docs")[0] == 400
    assert call(server, "GET", "/api/sets/missing/docs")[0] == 404


def test_sets_and_docs(server, doc):
    sets = call(server, "GET", "/api/sets")[1]
    assert [s["slug"] for s in sets] == ["case"]
    assert sets[0]["docs"] == 1
    rows = call(server, "GET", "/api/sets/case/docs")[1]
    assert len(rows) == 1 and rows[0]["uuid"] == doc
    assert rows[0]["has_pdf"] and rows[0]["tags"] == ["case.x"]
    assert "authors" in rows[0] and "dates" in rows[0]
    d = call(server, "GET", f"/api/sets/case/docs/{doc}")[1]
    assert d["title"] == "A title" and d["labels"] == []
    status, d = call(
        server,
        "PUT",
        f"/api/sets/case/docs/{doc}",
        {"title": "New", "notes": "n1", "tags": "case.x, case.y"},
    )
    assert status == 200 and d["title"] == "New" and d["notes"] == "n1"
    assert call(server, "GET", "/api/sets/case/docs")[1][0]["tags"] == [
        "case.x",
        "case.y",
    ]
    assert call(server, "GET", "/api/sets/case/docs/nope")[0] == 404


def test_duplicate_ingest(server, doc, tmp_path):
    pdf = _make_pdf(tmp_path / "b.pdf", "Hello evidence world")
    # same bytes as a.pdf? not necessarily — ingest the stored original instead
    stored = next(
        (
            Path(call(server, "GET", "/api/config")[1]["data_dir"])
            / "sets"
            / "case"
            / "docs"
            / doc
        ).glob("*.pdf")
    )
    r = ingest(server, "case", stored)
    assert r["existing"] is True and r["uuid"] == doc
    assert pdf.exists()


def test_tags(server, doc):
    status, r = call(
        server, "POST", "/api/sets/case/tag", {"uuids": [doc], "tag": "psych"}
    )
    assert status == 200 and r["tag"] == "case.psych" and r["changed"] == 1
    assert "case.psych" in call(server, "GET", "/api/tags")[1]
    assert (
        call(
            server,
            "POST",
            "/api/sets/case/tag",
            {"uuids": [doc], "tag": "case.psych", "remove": True},
        )[1]["changed"]
        == 1
    )
    assert call(server, "GET", "/api/sets/case/docs")[1][0]["tags"] == ["case.x"]
    assert (
        call(server, "POST", "/api/tags", {"slug": "case", "name": "empty"})[1]["tag"]
        == "case.empty"
    )
    assert (
        call(server, "POST", "/api/sets/case/tag", {"uuids": [doc], "tag": " "})[0]
        == 400
    )


def test_copy_and_delete(server, doc):
    call(server, "POST", "/api/sets", {"name": "Other"})
    status, r = call(
        server, "POST", "/api/sets/case/copy", {"uuids": [doc], "dest": "other"}
    )
    assert status == 200 and r["copied"] == 1
    assert (
        call(server, "POST", "/api/sets/case/copy", {"uuids": [doc], "dest": "other"})[
            1
        ]["copied"]
        == 0
    )
    assert (
        call(server, "POST", "/api/sets/case/copy", {"uuids": [doc], "dest": "case"})[0]
        == 400
    )
    other = call(server, "GET", "/api/sets/other/docs")[1]
    assert other[0]["uuid"] == doc and other[0]["indexed"] is False
    assert (
        call(server, "POST", "/api/sets/other/delete", {"uuids": [doc]})[1]["deleted"]
        == 1
    )
    assert call(server, "GET", "/api/sets/other/docs")[1] == []
    assert len(call(server, "GET", "/api/sets/case/docs")[1]) == 1


def test_label_reader(server, doc, app):
    d = app.data_dir / "sets" / "case" / "docs" / doc
    assert call(server, "GET", "/api/sets/case/docs")[1][0]["has_json"] is False
    assert call(server, "GET", f"/api/sets/case/docs/{doc}/typ")[0] == 404
    assert call(server, "POST", f"/api/sets/case/docs/{doc}/label", {})[0] == 404
    status, view = call(server, "GET", f"/api/sets/case/docs/{doc}/text")
    assert status == 200 and "Hello" in view["text"] and view["labels"] == []
    start = view["text"].index("Hello")
    end = start + len("Hello")
    (d / "pass").mkdir()
    (d / "pass" / "p1.json").write_text(
        json.dumps(
            {
                "id": "p1",
                "timestamp": "2026-01-01T00:00:00Z",
                "schema": 1,
                "model": "m",
                "evid_version": "0.6.1",
                "job": "find dates",
                "results": [
                    {
                        "candidate": "Hello",
                        "matched": True,
                        "score": 1,
                        "key": "q1",
                        "page": 1,
                    }
                ],
                "found": [
                    {
                        "key": "q1",
                        "start": start,
                        "end": end,
                        "page": 1,
                        "text": "Hello",
                    }
                ],
            }
        )
    )
    status, out = call(
        server,
        "POST",
        f"/api/sets/case/docs/{doc}/labels",
        {"start": start, "end": end, "note": "why"},
    )
    assert status == 200, out
    assert (
        out["labels"][0]["key"] == "hello"
        and out["labels"][0]["notes"][0]["text"] == "why"
    )
    assert (
        out["passes"][0]["job"] == "find dates"
        and out["passes"][0]["quotes"][0]["key"] == "q1"
    )
    assert (d / "label" / "labels.json").exists()
    assert call(server, "GET", "/api/sets/case/docs")[1][0]["has_json"] is True
    status, out = call(
        server,
        "POST",
        f"/api/sets/case/docs/{doc}/labels/hello/notes",
        {"text": "second"},
    )
    assert status == 200 and len(out["labels"][0]["notes"]) == 2
    status, out = call(
        server, "PUT", f"/api/sets/case/docs/{doc}/labels/hello", {"key": "greeting"}
    )
    assert status == 200 and out["labels"][0]["key"] == "greeting"
    status, out = call(
        server,
        "POST",
        f"/api/sets/case/docs/{doc}/annotations-on-text",
        {"start": start, "end": end, "text": "check"},
    )
    assert status == 200 and out["annotations"][0]["notes"][0]["text"] == "check"
    aid = out["annotations"][0]["id"]
    status, out = call(
        server,
        "PUT",
        f"/api/sets/case/docs/{doc}/annotations-on-text/{aid}",
        {"text": "more"},
    )
    assert status == 200 and len(out["annotations"][0]["notes"]) == 2
    assert (
        call(server, "DELETE", f"/api/sets/case/docs/{doc}/annotations-on-text/{aid}")[
            1
        ]["annotations"]
        == []
    )
    assert (
        call(server, "DELETE", f"/api/sets/case/docs/{doc}/labels/greeting")[1][
            "labels"
        ]
        == []
    )
    assert (
        call(
            server,
            "POST",
            f"/api/sets/case/docs/{doc}/labels",
            {"text": "not in this document zzz"},
        )[0]
        == 400
    )
    assert call(server, "DELETE", f"/api/sets/case/docs/{doc}/labels/missing")[0] == 404


def test_quotes_and_labels(server, doc, app):
    d = app.data_dir / "sets" / "case" / "docs" / doc
    label_doc(
        d, labels=[{"key": "k1", "text": "Quoted words", "page": 3, "note": "why"}]
    )
    det = call(server, "GET", f"/api/sets/case/docs/{doc}")[1]
    assert [lb["key"] for lb in det["labels"]] == ["k1"] and det["labels"][0][
        "page"
    ] == "3"
    y = call(
        server, "POST", f"/api/sets/case/docs/{doc}/labels-yaml", {"keys": ["k1"]}
    )[1]["text"]
    assert yaml.safe_load(y)["labels"]["k1"]["text"] == "Quoted words"
    q = call(server, "POST", "/api/sets/case/quotes", {"uuids": [doc]})[1]["text"]
    assert "Quoted words" in q
    assert (
        "Quoted words"
        in call(
            server,
            "POST",
            "/api/sets/case/quotes",
            {"uuids": [doc], "format": "markdown"},
        )[1]["text"]
    )


def test_search_meta_and_text(server, doc, app):
    assert [
        r["uuid"]
        for r in call(
            server, "POST", "/api/search/meta", {"slug": "case", "pattern": "A title"}
        )[1]
    ] == [doc]
    assert (
        call(server, "POST", "/api/search/meta", {"slug": "case", "pattern": "zzz"})[1]
        == []
    )
    from evid.core.labels import _write_text

    _write_text(
        app.data_dir / "sets" / "case" / "docs" / doc, "the needle is here\n", [[0, 1]]
    )
    hits = call(
        server, "POST", "/api/search/text", {"slug": "case", "query": "needle"}
    )[1]
    assert hits and hits[0]["uuid"] == doc and hits[0]["page"] == 1
    status, r = call(server, "POST", "/api/search/vec", {"slug": "case", "query": "x"})
    assert status == 400 and "vec" in r["error"]


def test_ingest_meta_files_and_import(server, tmp_path):
    pdf = _make_pdf(tmp_path / "m.pdf", "meta")
    r = call(server, "POST", "/api/ingest/meta", {"path": str(pdf)})[1]
    assert r["title"] and r["label"] == r["title"]
    assert (
        call(server, "POST", "/api/ingest/meta", {"path": str(tmp_path / "no.pdf")})[0]
        == 404
    )
    (tmp_path / "sub").mkdir()
    (tmp_path / "notes.txt").write_text("x")
    listing = call(server, "GET", f"/api/files?dir={tmp_path}&pdf=1")[1]
    names = [e["name"] for e in listing["entries"]]
    assert "sub" in names and "m.pdf" in names and "notes.txt" not in names
    assert (
        call(server, "POST", "/api/sets/import", {"path": str(tmp_path / "nope")})[0]
        == 400
    )


def test_fetch_rejects_non_url(server):
    assert call(server, "POST", "/api/fetch", {"url": "file:///etc/passwd"})[0] == 400


def test_ingest_error_is_an_event(server, tmp_path, monkeypatch):
    from evid.services import doc_ingester

    call(server, "POST", "/api/sets", {"name": "Case"})
    pdf = _make_pdf(tmp_path / "e.pdf", "boom")

    def boom(*_a, **_k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(doc_ingester.DocIngester, "ingest", boom)
    _, r = call(server, "POST", "/api/ingest", {"slug": "case", "path": str(pdf)})
    e = wait_job(server, r["job"])
    assert e["state"] == "error" and "disk on fire" in e["error"]


def test_quit_headless(server):
    assert call(server, "POST", "/api/quit", {})[1] == {"ok": True}


# ── background pieces ────────────────────────────────────────────────────────


def test_event_ids_are_never_overridden_by_data():
    ev = Events()
    ev.emit("a")
    ev.emit("job", id=99, job_id=1)
    assert [e["id"] for e in ev.since(0)[1]] == [1, 2]
    assert [e["kind"] for e in ev.since(1)[1]] == ["job"]


def test_label_watcher_rebuilds_on_save(tmp_path):
    ev = Events()
    typ = tmp_path / "label.typ"
    typ.write_text("no labels\n")
    w = LabelWatcher(ev)
    w._thread = object()  # don't start the polling thread; call poll() directly
    w.watch(typ, "case", "u1")
    w.poll()
    assert ev.since(0)[1] == []
    time.sleep(0.01)
    typ.write_text("still no labels\n")
    w.poll()
    kinds = [e["kind"] for e in ev.since(0)[1]]
    assert kinds == ["labels_updated"]
    assert (tmp_path / "label.json").exists()


class _ES:
    slug = "demo"


def _queue(monkeypatch, recorder):
    ev = Events()
    q = IndexQueue(ev)
    monkeypatch.setattr(q, "_make_ingester", lambda: (recorder, False))
    return ev, q


def test_index_queue_in_order(tmp_path, monkeypatch):
    calls = []

    class Rec:
        def index_existing(self, doc_dir, _es):
            calls.append(doc_dir.name)
            return True

    ev, q = _queue(monkeypatch, Rec())
    for name in ("a", "b", "c"):
        q.enqueue(tmp_path / name, _ES())
    q.stop()
    assert calls == ["a", "b", "c"]
    kinds = [e["kind"] for e in ev.since(0)[1]]
    assert kinds.count("indexed") == 3 and kinds[-1] == "index_idle" and q.pending == 0


def test_index_queue_survives_a_failure(tmp_path, monkeypatch):
    class Rec:
        def index_existing(self, doc_dir, _es):
            if doc_dir.name == "bad":
                raise RuntimeError("nope")
            return True

    ev, q = _queue(monkeypatch, Rec())
    q.enqueue(tmp_path / "bad", _ES())
    q.enqueue(tmp_path / "good", _ES())
    q.stop()
    done = [(e["uuid"], e["ok"]) for e in ev.since(0)[1] if e["kind"] == "indexed"]
    assert done == [("bad", False), ("good", True)]


# ── single instance ──────────────────────────────────────────────────────────


def test_raise_opens_the_named_document(server, app, monkeypatch):
    def _no_window(*_args, **_kwargs):
        return None

    monkeypatch.setattr(web, "raise_window", _no_window)
    status, body = call(
        server,
        "POST",
        "/api/raise",
        {"set": "case", "doc": "u1", "pane": "label"},
    )
    assert status == 200 and body == {"ok": True}
    opened = [e for e in app.events.since(0)[1] if e["kind"] == "open"]
    assert opened[-1]["slug"] == "case"
    assert opened[-1]["uuid"] == "u1"
    assert opened[-1]["pane"] == "label"


def test_second_launch_raises_running_instance(server, app, monkeypatch, capsys):
    import json as _json

    lp = web.lock_path(app.data_dir)
    lp.write_text(_json.dumps({"url": server + "/", "pid": 1}))
    raised = []
    monkeypatch.setattr(web, "raise_window", lambda: raised.append(True))
    web.serve_gui(EvidConfig(data_dir=app.data_dir), headless=True)
    assert raised == [True]
    assert "Raised the running evid GUI" in capsys.readouterr().out


def test_no_instance_for_other_data_dir(server, app, tmp_path):
    web.lock_path(tmp_path / "elsewhere").write_text(
        json.dumps({"url": server + "/", "pid": 1})
    )
    assert web.running_instance(tmp_path / "elsewhere") is None
    assert web.running_instance(tmp_path / "never") is None


def test_serve_gui_headless_quits(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    monkeypatch.setattr(web.Handler, "window", None)
    cfg = EvidConfig(data_dir=tmp_path / "d")
    t = threading.Thread(
        target=web.serve_gui,
        args=(cfg,),
        kwargs={"port": 18790, "headless": True},
        daemon=True,
    )
    t.start()
    lp = web.lock_path(cfg.data_dir)
    for _ in range(100):
        if lp.exists():
            break
        time.sleep(0.05)
    url = json.loads(lp.read_text())["url"].rstrip("/")
    assert call(url, "POST", "/api/quit", {})[0] == 200
    t.join(10)
    assert not t.is_alive() and not lp.exists()


def test_doc_files_list_and_open(server, doc, app, monkeypatch):
    import evid.open_external as oe

    d = app.data_dir / "sets" / "case" / "docs" / doc
    (d / "extra").mkdir()
    (d / "extra" / "note.txt").write_text("hi")
    _, r = call(server, "GET", f"/api/sets/case/docs/{doc}/files")
    names = [e["name"] for e in r["entries"]]
    assert names[0] == "extra"  # folders first
    assert "info.yml" in names and "original.pdf" in names
    sub = call(server, "GET", f"/api/sets/case/docs/{doc}/files?sub=extra")[1][
        "entries"
    ]
    assert [(e["name"], e["path"], e["size"]) for e in sub] == [
        ("note.txt", "extra/note.txt", 2)
    ]
    assert call(server, "GET", f"/api/sets/case/docs/{doc}/files?sub=..")[0] == 400
    assert call(server, "GET", f"/api/sets/case/docs/{doc}/files?sub=nope")[0] == 404

    opened = []
    monkeypatch.setattr(
        oe, "open_local_path", lambda p, editor=None: opened.append((p.name, editor))
    )
    assert (
        call(
            server,
            "POST",
            f"/api/sets/case/docs/{doc}/open",
            {"what": "file", "path": "info.yml"},
        )[0]
        == 200
    )
    assert (
        call(
            server,
            "POST",
            f"/api/sets/case/docs/{doc}/open",
            {"what": "file", "path": "original.pdf"},
        )[0]
        == 200
    )
    assert opened == [
        ("info.yml", "true"),
        ("original.pdf", None),
    ]  # text files go to the editor
    assert (
        call(
            server,
            "POST",
            f"/api/sets/case/docs/{doc}/open",
            {"what": "file", "path": "../../x"},
        )[0]
        == 400
    )


def test_doc_rows_carry_author_and_date(server, doc):
    call(
        server,
        "PUT",
        f"/api/sets/case/docs/{doc}",
        {"authors": "Dr. A", "dates": "2024-03-12"},
    )
    row = call(server, "GET", "/api/sets/case/docs")[1][0]
    assert (row["authors"], row["dates"]) == ("Dr. A", "2024-03-12")


def test_source_name_recorded_and_kept(server, doc, app):
    info_path = app.data_dir / "sets" / "case" / "docs" / doc / "info.yml"
    info = yaml.safe_load(info_path.read_text())
    assert info["original_name"] == "original.pdf"  # where the PDF lives
    assert info["source_name"] == "a.pdf"  # what it was called
    assert (
        call(server, "GET", f"/api/sets/case/docs/{doc}")[1]["source_name"] == "a.pdf"
    )
    call(server, "PUT", f"/api/sets/case/docs/{doc}", {"title": "Edited"})
    assert (
        yaml.safe_load(info_path.read_text())["source_name"] == "a.pdf"
    )  # a detail save keeps it


def test_ingest_uses_given_source_name(server, tmp_path):
    call(server, "POST", "/api/sets", {"name": "Case"})
    pdf = _make_pdf(tmp_path / "tmpabc.pdf", "fetched")
    r = ingest(server, "case", pdf, source_name="Afgørelse 2024.pdf")
    assert (
        call(server, "GET", f"/api/sets/case/docs/{r['uuid']}")[1]["source_name"]
        == "Afgørelse 2024.pdf"
    )


def test_annotations_api(server, doc, app):
    status, r = call(
        server,
        "PUT",
        f"/api/sets/case/docs/{doc}/annotations",
        {"path": "original.pdf", "text": "Signed copy."},
    )
    assert status == 200 and r["annotations"] == {"original.pdf": "Signed copy."}
    files = call(server, "GET", f"/api/sets/case/docs/{doc}/files")[1]["entries"]
    by = {e["name"]: e for e in files}
    assert by["original.pdf"]["note"] == "Signed copy." and "annotations.yml" not in by
    call(server, "PUT", f"/api/sets/case/docs/{doc}", {"notes": "Key exhibit."})
    det = call(server, "GET", f"/api/sets/case/docs/{doc}")[1]
    assert det["notes"] == "Key exhibit." and det["annotations"]["."] == "Key exhibit."
    assert call(server, "GET", "/api/sets/case/docs")[1][0]["note"] == "Key exhibit."
    assert (
        call(
            server,
            "PUT",
            f"/api/sets/case/docs/{doc}/annotations",
            {"path": "../x", "text": "y"},
        )[0]
        == 400
    )
    # annotations travel with a copy
    call(server, "POST", "/api/sets", {"name": "Other"})
    call(server, "POST", "/api/sets/case/copy", {"uuids": [doc], "dest": "other"})
    assert call(server, "GET", f"/api/sets/other/docs/{doc}")[1]["annotations"] == {
        ".": "Key exhibit.",
        "original.pdf": "Signed copy.",
    }


def test_actions_reach_the_log_pane(server, doc):
    call(server, "POST", "/api/sets/case/tag", {"uuids": [doc], "tag": "psych"})
    call(
        server,
        "PUT",
        f"/api/sets/case/docs/{doc}/annotations",
        {"path": "../x", "text": "y"},
    )
    _, r = call(server, "GET", "/api/events?since=0")
    logs = [e["msg"] for e in r["events"] if e["kind"] == "log"]
    assert any("Adding a.pdf" in m for m in logs)  # job start
    assert any("Added a.pdf to 'case'" in m for m in logs)
    assert any("Tagged 1 document(s) with case.psych" in m for m in logs)
    assert any("failed: path outside the document folder" in m for m in logs)


# ── agent pane ───────────────────────────────────────────────────────────────


def test_vendor_files(server):
    assert call(server, "GET", "/vendor/xterm.js")[0] == 200
    assert call(server, "GET", "/vendor/nope.js")[0] == 404


def _agents(app, monkeypatch, agent=""):
    agents = web.SetAgents(
        app.data_dir,
        "http://127.0.0.1:1/",
        agent,
        lambda slug: app.events.emit("agents", slug=slug),
    )
    monkeypatch.setattr(web.Handler, "agents", agents)
    return agents


def test_terminal_websocket(server, app, monkeypatch):
    import base64
    import socket

    from evid.web.term import ws_frame

    monkeypatch.setenv("SHELL", "/bin/sh")
    monkeypatch.setenv("PS1", "$ ")
    agents = _agents(app, monkeypatch)
    call(server, "POST", "/api/sets", {"name": "Case"})
    assert call(server, "GET", "/api/config")[1]["term"] is True
    assert (
        call(server, "GET", "/api/terms?slug=case")[1]["terms"] == []
    )  # looking attaches nothing
    r = call(
        server, "POST", "/api/term/new", {"slug": "case", "agent": "echo hi-there"}
    )[1]
    term = agents.get(app.sets.load_set("case")).get(r["id"])
    host, port = server.removeprefix("http://").split(":")
    token = web.Handler.token

    def handshake(origin, tok=token, slug="case"):
        s = socket.create_connection((host, int(port)), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall(
            (
                f"GET /api/term?token={tok}&slug={slug}&id={r['id']} HTTP/1.1\r\nHost: {host}:{port}\r\nOrigin: {origin}\r\n"
                f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n\r\n"
            ).encode()
        )
        return s

    for bad in (
        handshake("http://evil.example"),
        handshake(f"http://{host}:{port}", tok="wrong"),
    ):
        assert b"403" in bad.recv(1024)
        bad.close()
    other = handshake(f"http://{host}:{port}", slug="nope")
    assert b"404" in other.recv(1024)
    other.close()
    s = handshake(f"http://{host}:{port}")
    data, deadline = b"", time.time() + 10
    while (
        b"hi-there" not in data.split(b"echo hi-there")[-1] and time.time() < deadline
    ):
        data += s.recv(65536)
    assert b"101 Switching Protocols" in data and b'"hello"' in data

    def send(op, payload):
        frame = ws_frame(op, payload)
        s.sendall(
            frame[:1]
            + bytes([frame[1] | 0x80])
            + frame[2 : 2 + (len(frame) - 2 - len(payload))]
            + b"\0\0\0\0"
            + payload
        )

    send(1, json.dumps({"t": "resize", "rows": 30, "cols": 100}).encode())
    send(1, json.dumps({"t": "in", "d": "echo [$EVID_SET][$PWD]\r"}).encode())
    data, deadline = b"", time.time() + 10
    want = f"[case][{app.data_dir / 'sets' / 'case'}]".encode()
    while want not in data and time.time() < deadline:
        data += s.recv(65536)
    assert want in data  # the set's terminal: EVID_SET and the set's folder
    assert term.size == (30, 100)
    send(8, b"")
    s.close()
    agents.stop()
    assert not term.alive


def test_terminals_are_per_set(server, app, monkeypatch):
    agents = _agents(app, monkeypatch, agent="claude")
    call(server, "POST", "/api/sets", {"name": "Case"})
    call(server, "POST", "/api/sets", {"name": "Other"})
    r = call(server, "POST", "/api/term/new", {"slug": "case", "agent": "claude"})[1]
    assert r["id"] == "1" and r["terms"][0]["label"] == "claude"
    assert (
        call(server, "GET", "/api/terms?slug=other")[1]["terms"] == []
    )  # not shared across sets
    sets = {x["slug"]: x for x in call(server, "GET", "/api/sets")[1]}
    assert (
        sets["case"]["agents"] == {"terms": 1, "alive": 0, "names": ["claude"]}
        and sets["other"]["agents"] is None
    )
    events = call(server, "GET", "/api/events?since=0")[1]["events"]
    assert any(e["kind"] == "agents" and e["slug"] == "case" for e in events)
    assert (
        call(server, "POST", "/api/term/close", {"slug": "other", "id": "1"})[0] == 404
    )
    assert (
        call(server, "POST", "/api/term/close", {"slug": "case", "id": "1"})[1]["terms"]
        == []
    )
    assert {x["slug"]: x for x in call(server, "GET", "/api/sets")[1]}["case"][
        "agents"
    ] is None
    assert call(server, "GET", "/api/terms?slug=missing")[0] == 404
    agents.stop()
    monkeypatch.setattr(web.Handler, "agents", None)
    assert call(server, "GET", "/api/terms?slug=case")[0] == 404


def test_terminal_env_points_evid_at_the_data_dir_and_set(tmp_path, monkeypatch):
    monkeypatch.setenv("EVID_IN_APP", "1")
    env = web.terminal_env(tmp_path, "http://127.0.0.1:1/", "case")
    assert env["EVID_DB"] == str(tmp_path) and env["EVID_SET"] == "case"
    assert "EVID_IN_APP" not in env and env["TERM"] == "xterm-256color"
    assert "EVID_SET" not in web.terminal_env(tmp_path, "http://127.0.0.1:1/")


def test_agent_name():
    names = [
        "grok",
        "fish",
        "claude --continue",
        "opencode",
        "hermes --skills evid",
        "codex",
        "/usr/bin/fish",
        "env FOO=1 codex",
        "npx opencode",
        "",
    ]
    assert [web.agent_name(n) for n in names] == [
        "grok",
        "fish",
        "claude",
        "opencode",
        "hermes",
        "codex",
        "fish",
        "codex",
        "opencode",
        "shell",
    ]


def test_feedback_routes(server, doc, app):
    status, x = call(
        server,
        "POST",
        "/api/sets/case/feedback",
        {"uuid": doc, "text": "Check the date."},
    )
    assert status == 200 and x["id"] == 1 and x["path"] == "."
    assert (
        call(
            server,
            "POST",
            "/api/sets/case/feedback",
            {"uuid": doc, "path": "nope.pdf", "text": "x"},
        )[0]
        == 404
    )
    assert (
        call(server, "POST", "/api/sets/case/feedback", {"uuid": doc, "text": " "})[0]
        == 400
    )
    assert call(server, "GET", "/api/sets/case/docs")[1][0]["fb_open"] == 1
    assert (
        call(
            server,
            "PUT",
            "/api/sets/case/feedback/1",
            {"reply": "2024-06-03", "status": "done"},
        )[1]["status"]
        == "done"
    )
    assert call(server, "GET", "/api/sets/case/docs")[1][0]["fb_open"] == 0
    assert [
        i["reply"]
        for i in call(server, "GET", f"/api/sets/case/feedback?uuid={doc}")[1]
    ] == ["2024-06-03"]
    assert (
        call(server, "PUT", "/api/sets/case/feedback/9", {"status": "done"})[0] == 404
    )
    assert call(server, "POST", "/api/sets/case/feedback/1/delete", {})[1] == {
        "ok": True
    }
    assert call(server, "GET", "/api/sets/case/feedback")[1] == []
