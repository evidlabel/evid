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


def doc_path(data_dir, slug, uuid):
    """On-disk document directory for a set the server created."""
    from evid.services.layout import find_set_dir

    return find_set_dir(Path(data_dir), slug) / "docs" / uuid


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
        doc_path(
            Path(call(server, "GET", "/api/config")[1]["data_dir"]), "case", doc
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
    d = doc_path(app.data_dir, "case", doc)
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
    status, out = call(
        server,
        "POST",
        f"/api/sets/case/docs/{doc}/quotes/q1/notes",
        {"text": "check this", "pass": "p1"},
    )
    assert status == 200
    assert out["passes"][0]["quotes"][0]["notes"][0]["text"] == "check this"
    status, out = call(
        server,
        "PUT",
        f"/api/sets/case/docs/{doc}/quotes/q1/notes/0",
        {"text": "check the date", "pass": "p1"},
    )
    assert status == 200
    assert out["passes"][0]["quotes"][0]["notes"][0]["text"] == "check the date"
    status, out = call(
        server, "DELETE", f"/api/sets/case/docs/{doc}/quotes/q1/notes/0?pass=p1"
    )
    assert status == 200 and out["passes"][0]["quotes"][0]["notes"] == []
    assert (
        call(
            server,
            "POST",
            f"/api/sets/case/docs/{doc}/quotes/missing/notes",
            {"text": "x"},
        )[0]
        == 404
    )
    assert (
        call(
            server,
            "POST",
            f"/api/sets/case/docs/{doc}/quotes/q1/notes",
            {"text": "  "},
        )[0]
        == 400
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
        server,
        "PUT",
        f"/api/sets/case/docs/{doc}/labels/hello/notes/0",
        {"text": "why, revised"},
    )
    assert status == 200 and out["labels"][0]["notes"][0]["text"] == "why, revised"
    status, out = call(
        server, "DELETE", f"/api/sets/case/docs/{doc}/labels/hello/notes/1"
    )
    assert status == 200 and [n["text"] for n in out["labels"][0]["notes"]] == [
        "why, revised"
    ]
    assert (
        call(server, "DELETE", f"/api/sets/case/docs/{doc}/labels/hello/notes/5")[0]
        == 404
    )
    assert (
        call(
            server,
            "PUT",
            f"/api/sets/case/docs/{doc}/labels/hello/notes/0",
            {"text": "  "},
        )[0]
        == 400
    )
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
    status, out = call(
        server,
        "PUT",
        f"/api/sets/case/docs/{doc}/annotations-on-text/{aid}/notes/0",
        {"text": "check this"},
    )
    assert status == 200 and out["annotations"][0]["notes"][0]["text"] == "check this"
    status, out = call(
        server,
        "DELETE",
        f"/api/sets/case/docs/{doc}/annotations-on-text/{aid}/notes/1",
    )
    assert status == 200 and len(out["annotations"][0]["notes"]) == 1
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


def test_whole_document_labels(server, doc):
    status, out = call(
        server,
        "POST",
        f"/api/sets/case/docs/{doc}/document/labels",
        {"key": "exhibit", "note": "Key exhibit."},
    )
    assert status == 200, out
    rec = out["document"][0]
    assert rec["kind"] == "label" and rec["key"] == "exhibit"
    assert rec["notes"][0]["text"] == "Key exhibit."
    assert "start" not in rec and "text" not in rec
    status, out = call(
        server,
        "POST",
        f"/api/sets/case/docs/{doc}/document/annotations",
        {"text": "Watch the date."},
    )
    assert status == 200 and out["document"][1]["kind"] == "annotation"
    ann = out["document"][1]["id"]
    status, out = call(
        server,
        "POST",
        f"/api/sets/case/docs/{doc}/document/{ann}/notes",
        {"text": "And the names."},
    )
    assert status == 200 and len(out["document"][1]["notes"]) == 2
    status, out = call(
        server,
        "DELETE",
        f"/api/sets/case/docs/{doc}/document/{ann}/notes/0",
    )
    assert status == 200
    status, out = call(
        server,
        "DELETE",
        f"/api/sets/case/docs/{doc}/document/{ann}/notes/0",
    )
    assert status == 200 and len(out["document"]) == 1  # last note removes it
    assert (
        call(
            server,
            "POST",
            f"/api/sets/case/docs/{doc}/document/labels",
            {"key": "exhibit"},
        )[0]
        == 400
    )
    # the old single note becomes one whole-document annotation on the label view
    call(
        server,
        "PUT",
        f"/api/sets/case/docs/{doc}/annotations",
        {"path": ".", "text": "From annotations.yml."},
    )
    view = call(server, "GET", f"/api/sets/case/docs/{doc}/text")[1]
    texts = [n["text"] for rec in view["document"] for n in rec["notes"]]
    assert "From annotations.yml." in texts
    det = call(server, "GET", f"/api/sets/case/docs/{doc}")[1]
    assert "." not in det["annotations"]


def test_quotes_and_labels(server, doc, app):
    d = doc_path(app.data_dir, "case", doc)
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

    _write_text(doc_path(app.data_dir, "case", doc), "the needle is here\n", [[0, 1]])
    hits = call(
        server, "POST", "/api/search/text", {"slug": "case", "query": "NEEDLE"}
    )[1]
    assert hits and hits[0]["uuid"] == doc and hits[0]["page"] == 1
    assert (
        "the needle is here\n"[hits[0]["char_start"] : hits[0]["char_end"]] == "needle"
    )
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


def _png(path, width):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, width, 16), 0)
    pix.clear_with(240)
    pix.save(str(path))
    return path


def _stub_ocr(pix, _lang):
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=60)
    page.insert_text((20, 36), f"page-text {pix.width}")
    raw = doc.tobytes(garbage=4, deflate=True, no_new_id=True, reproducible=True)
    doc.close()
    return raw


def test_screenshot_ingest(server, tmp_path, monkeypatch):
    from evid.services import screenshots as shots

    monkeypatch.setattr(shots, "ocr_pixmap", _stub_ocr)
    call(server, "POST", "/api/sets", {"name": "Case"})
    a = _png(tmp_path / "a.png", 30)
    b = _png(tmp_path / "b.png", 80)
    assert call(server, "POST", "/api/ingest/screenshots", {"pages": []})[0] == 400
    _, started = call(
        server,
        "POST",
        "/api/ingest/screenshots",
        {"lang": "dan+eng", "pages": [{"path": str(a)}, {"path": str(b)}]},
    )
    event = wait_job(server, started["job"])
    assert event["state"] == "done", event
    meta = event["result"]
    assert meta["screenshot"] is True
    assert meta["source_name"] == "screenshots.pdf"
    with pymupdf.open(meta["path"]) as pdf:
        assert pdf.page_count == 2
    added = ingest(
        server,
        "case",
        meta["path"],
        title="From the viewer",
        url="https://issuu.com/x",
        token=meta["token"],
        screenshot=True,
        source_name=meta["source_name"],
    )
    assert added["existing"] is False
    doc = doc_path(
        Path(call(server, "GET", "/api/config")[1]["data_dir"]), "case", added["uuid"]
    )
    text = (doc / "label" / "text.txt").read_text(encoding="utf-8")
    assert "page-text 30" in text and "page-text 80" in text
    labels = json.loads((doc / "label" / "labels.json").read_text(encoding="utf-8"))
    assert labels["document"][0]["notes"][0]["text"] == shots.SCREENSHOT_NOTE


def test_image_picker_lists_pages_in_order(server, tmp_path):
    _png(tmp_path / "page10.png", 10)
    _png(tmp_path / "page2.png", 12)
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    names = [
        e["name"]
        for e in call(server, "GET", f"/api/files?dir={tmp_path}&images=1")[1][
            "entries"
        ]
        if not e["dir"]
    ]
    assert names == ["page2.png", "page10.png"]


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


def test_headless_raise_does_not_open_evid_app(monkeypatch):
    """The headless server must not spawn evid-app. A windowed launch does that."""
    opened = []
    monkeypatch.setattr(web.Handler, "headless", True)
    monkeypatch.setattr(web.Handler, "window", None)
    monkeypatch.delenv("EVID_IN_APP", raising=False)
    monkeypatch.setattr(web, "find_app", lambda: "/usr/bin/evid-app")
    monkeypatch.setattr(web.subprocess, "Popen", lambda *a, **_k: opened.append(a))
    monkeypatch.setattr(
        web.webbrowser, "open", lambda *_a, **_k: opened.append("browser")
    )
    web.raise_window()
    assert opened == []


class _AppProc:
    pid = 4242

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        return None


def test_windowed_launch_opens_the_tauri_app(server, app, monkeypatch, capsys):
    """A headless server has no window. `evid gui` opens evid-app on its URL."""
    web.lock_path(app.data_dir).write_text(json.dumps({"url": server + "/", "pid": 1}))
    opened = []
    monkeypatch.setattr(web, "find_app", lambda: "/usr/bin/evid-app")
    monkeypatch.setattr(
        web.subprocess,
        "Popen",
        lambda cmd, **_k: opened.append(list(cmd)) or _AppProc(),
    )
    monkeypatch.setattr(
        web.webbrowser, "open", lambda *_a, **_k: opened.append("browser")
    )
    web.serve_gui(
        EvidConfig(data_dir=app.data_dir),
        open_at={"set": "case", "doc": "u1", "pane": "label"},
    )
    assert opened[0][0] == "/usr/bin/evid-app"
    assert opened[0][1:3] == ["--url", f"{server}/?set=case&doc=u1&pane=label"]
    assert opened[0][3] == "--raise-file"
    assert "browser" not in opened
    note = json.loads(web._window_note(app.data_dir).read_text())
    assert note["pid"] == _AppProc.pid
    assert "Opened evid-app on the running GUI" in capsys.readouterr().out


def test_second_windowed_launch_raises_the_app(server, app, monkeypatch, capsys):
    """The evid-app already opened for this data directory is brought forward."""
    web.lock_path(app.data_dir).write_text(json.dumps({"url": server + "/", "pid": 1}))
    raise_path = web.lock_path(app.data_dir).with_suffix(".app-raise")
    raise_path.write_text("0")
    web._window_note(app.data_dir).write_text(
        json.dumps({"pid": 99, "raise": str(raise_path)})
    )
    opened = []
    monkeypatch.setattr(web, "_app_process_alive", lambda _pid: True)
    monkeypatch.setattr(web, "raise_window", lambda: None)
    monkeypatch.setattr(
        web.subprocess, "Popen", lambda *_a, **_k: opened.append("popen")
    )
    web.serve_gui(EvidConfig(data_dir=app.data_dir))
    assert opened == []
    assert raise_path.read_text() != "0"
    assert "Raised the running evid GUI" in capsys.readouterr().out


def test_windowed_launch_raises_when_the_server_is_already_the_app(
    server, app, monkeypatch, capsys
):
    web.lock_path(app.data_dir).write_text(json.dumps({"url": server + "/", "pid": 1}))
    monkeypatch.setattr(web.Handler, "in_app", True)
    opened = []
    monkeypatch.setattr(web, "raise_window", lambda: None)
    monkeypatch.setattr(
        web.subprocess, "Popen", lambda *_a, **_k: opened.append("popen")
    )
    web.serve_gui(EvidConfig(data_dir=app.data_dir))
    assert opened == []
    assert "Raised the running evid GUI" in capsys.readouterr().out


def test_headless_second_launch_does_not_open_the_app(server, app, monkeypatch):
    web.lock_path(app.data_dir).write_text(json.dumps({"url": server + "/", "pid": 1}))
    opened = []
    monkeypatch.setattr(web, "find_app", lambda: "/usr/bin/evid-app")
    monkeypatch.setattr(web, "raise_window", lambda: None)
    monkeypatch.setattr(
        web.subprocess, "Popen", lambda *_a, **_k: opened.append("popen")
    )
    web.serve_gui(EvidConfig(data_dir=app.data_dir), headless=True)
    assert opened == []


def test_second_launch_raises_running_instance(server, app, monkeypatch, capsys):
    import json as _json

    lp = web.lock_path(app.data_dir)
    lp.write_text(_json.dumps({"url": server + "/", "pid": 1}))
    raised = []
    monkeypatch.setattr(web, "raise_window", lambda: raised.append(True))
    web.serve_gui(EvidConfig(data_dir=app.data_dir), headless=True)
    assert raised == [True]
    assert "Raised the running evid GUI" in capsys.readouterr().out


class _OldGui:
    """Stand-in for an evid GUI from before ``/api/roots``."""

    def __init__(self, data_dir: Path, roots_body: bytes | None = None):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path == "/api/config":
                    body = json.dumps({"data_dir": str(data_dir.resolve())}).encode()
                    self._json(200, body)
                elif path == "/api/roots":
                    if roots_body is None:
                        self._json(404, b'{"error":"no such endpoint"}')
                    else:
                        self._json(200, roots_body)
                else:
                    self._json(404, b"no")

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                if n:
                    self.rfile.read(n)
                path = self.path.split("?", 1)[0]
                code = 200 if path in ("/api/raise", "/api/quit") else 404
                self._json(code, b'{"ok":true}')
                if path == "/api/quit":
                    parent.quit_started.set()
                    threading.Thread(target=self.server.shutdown, daemon=True).start()

            def _json(self, code, body):
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                return

        self.quit_started = threading.Event()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


def test_a_gui_without_roots_is_replaced(tmp_path, monkeypatch):
    """A GUI started before /api/roots answers 404. The next launch takes over."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    monkeypatch.setattr(web.Handler, "window", None)
    data = tmp_path / "d"
    data.mkdir()
    old = _OldGui(data)
    web.lock_path(data).write_text(json.dumps({"url": old.url, "pid": 1}))
    assert web.lacks_roots(old.url)

    fresh = threading.Thread(
        target=web.serve_gui,
        args=(EvidConfig(data_dir=data),),
        kwargs={"port": 18791, "headless": True},
        daemon=True,
    )
    fresh.start()
    url = _replaced_url(web.lock_path(data), old)
    assert url
    assert call(url, "GET", "/api/roots")[0] == 200
    assert call(url, "POST", "/api/quit", {})[0] == 200
    fresh.join(10)
    assert not fresh.is_alive()


def test_replace_takes_a_running_gui(tmp_path, monkeypatch):
    """``--replace`` quits a current GUI and serves in this process."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    monkeypatch.setattr(web.Handler, "window", None)
    data = tmp_path / "owned"
    data.mkdir()
    old = _OldGui(data, roots_body=b"[]")
    web.lock_path(data).write_text(json.dumps({"url": old.url, "pid": 1}))
    assert not web.lacks_roots(old.url)
    fresh = threading.Thread(
        target=web.serve_gui,
        args=(EvidConfig(data_dir=data),),
        kwargs={"port": 18792, "headless": True, "replace": True},
        daemon=True,
    )
    fresh.start()
    url = _replaced_url(web.lock_path(data), old)
    assert url
    assert call(url, "GET", "/api/roots")[0] == 200
    assert call(url, "POST", "/api/quit", {})[0] == 200
    fresh.join(10)
    assert not fresh.is_alive()


def _replaced_url(lock, old: _OldGui) -> str:
    previous = old.url.rstrip("/")
    for _ in range(200):
        if old.quit_started.is_set() and lock.is_file():
            url = json.loads(lock.read_text()).get("url", "").rstrip("/")
            if url and url != previous:
                return url
        time.sleep(0.05)
    return ""


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


def test_quit_stops_a_headless_server_that_opened_a_window(tmp_path, monkeypatch):
    """A headless GUI that raise() pointed at evid-app still has to exit on quit.

    Otherwise ``evid gui --replace`` reports that the GUI did not stop, and the
    workbench's Datasets tab never comes up.
    """

    class _Window:
        def poll(self):
            return 0  # already exited; still recorded on Handler.window

        def terminate(self):
            raise AssertionError("the window is already gone")

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    monkeypatch.setattr(web.Handler, "window", _Window())
    cfg = EvidConfig(data_dir=tmp_path / "raised")
    t = threading.Thread(
        target=web.serve_gui,
        args=(cfg,),
        kwargs={"port": 18793, "headless": True},
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


def test_replace_quits_without_raising(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    data = tmp_path / "d"
    data.mkdir()
    calls = []
    monkeypatch.setattr(web, "running_instance", lambda _d: "http://127.0.0.1:9/")
    monkeypatch.setattr(web, "lacks_roots", lambda _u: False)
    monkeypatch.setattr(
        web, "ask_raise", lambda *_a, **_k: calls.append("raise") or True
    )
    monkeypatch.setattr(web, "ask_quit", lambda *_a, **_k: calls.append("quit") or True)
    monkeypatch.setattr(web, "_wait_down", lambda *_a, **_k: True)
    assert web._claim_running(EvidConfig(data_dir=data), None, True) is True
    assert calls == ["quit"]


def test_replace_proceeds_when_quit_loses_the_connection(tmp_path, monkeypatch):
    """The GUI can exit before the quit response is read. That is a stopped GUI."""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    data = tmp_path / "d"
    data.mkdir()

    def _no_raise(*_a, **_k):
        raise AssertionError("raised")

    monkeypatch.setattr(web, "running_instance", lambda _d: "http://127.0.0.1:9/")
    monkeypatch.setattr(web, "lacks_roots", lambda _u: False)
    monkeypatch.setattr(web, "ask_raise", _no_raise)
    monkeypatch.setattr(web, "ask_quit", lambda *_a, **_k: False)
    monkeypatch.setattr(web, "_wait_down", lambda *_a, **_k: True)
    assert web._claim_running(EvidConfig(data_dir=data), None, True) is True


def test_doc_files_list_and_open(server, doc, app, monkeypatch):
    import evid.open_external as oe

    d = doc_path(app.data_dir, "case", doc)
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


def test_doc_rows_count_manual_and_machine_labels(server, doc, app):
    row = call(server, "GET", "/api/sets/case/docs")[1][0]
    assert row["nlabels"] == 0 and row["nmachine"] == 0
    doc_dir = doc_path(app.data_dir, "case", doc)
    label_doc(
        doc_dir,
        labels=[{"key": "found", "text": "The committee found for the appellant."}],
        quotes=[
            {"text": "The committee found for the appellant."},
            {"text": "Costs follow the event."},
        ],
    )
    row = call(server, "GET", "/api/sets/case/docs")[1][0]
    assert row["nlabels"] == 1 and row["nmachine"] == 2
    # a quote the text no longer holds is not a label you can open
    path = next((doc_dir / "pass").glob("*.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["found"][0]["lost"] = True
    path.write_text(json.dumps(data), encoding="utf-8")
    assert call(server, "GET", "/api/sets/case/docs")[1][0]["nmachine"] == 1


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
    info_path = doc_path(app.data_dir, "case", doc) / "info.yml"
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
    assert det["notes"] == "Key exhibit." and "." not in det["annotations"]
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
    copied = call(server, "GET", f"/api/sets/other/docs/{doc}")[1]
    assert copied["notes"] == "Key exhibit."
    assert copied["annotations"] == {"original.pdf": "Signed copy."}


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
    want = f"[case][{app.sets.load_set('case').path}]".encode()
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


def test_sets_report_type(server, tmp_path):
    from evid.services.set_manager import SetManager

    call(server, "POST", "/api/sets", {"name": "Reference"})
    sets = call(server, "GET", "/api/sets")[1]
    assert {s["slug"]: s["type"] for s in sets}["reference"] == "normal"
    data_dir = Path(call(server, "GET", "/api/config")[1]["data_dir"])
    SetManager(data_dir).create_set("Case anon", set_type="anon")
    sets = call(server, "GET", "/api/sets")[1]
    assert {s["slug"]: s["type"] for s in sets}["case-anon"] == "anon"


def test_stale_route_and_counts(server, doc, tmp_path):
    """After a replace, lost labels show as stale: per set, per document, in the text view."""
    from evid.core import labels
    from evid.services.doc_replace import replace

    data_dir = Path(call(server, "GET", "/api/config")[1]["data_dir"])
    d = doc_path(data_dir, "case", doc)
    span, _, _ = labels.span_of(d, "Hello evidence world")
    labels.add_label(d, span, "hello")
    assert call(server, "GET", "/api/sets/case/stale")[1] == {"docs": [], "count": 0}
    replace(d, _make_pdf(tmp_path / "v2.pdf", "Something else entirely"), {})
    status, st = call(server, "GET", "/api/sets/case/stale")
    assert (
        status == 200
        and st["count"] == 1
        and st["docs"][0]["records"][0]["key"] == "hello"
    )
    rows = call(server, "GET", "/api/sets/case/docs")[1]
    row = next(
        r
        for r in (rows["docs"] if isinstance(rows, dict) else rows)
        if r["uuid"] == doc
    )
    assert row["nstale"] == 1 and row["nlabels"] == 0
    view = call(server, "GET", f"/api/sets/case/docs/{doc}/text")[1]
    assert view["labels"] == [] and view["stale"][0]["key"] == "hello"


def test_connected_directories_are_separate_trunks(server, tmp_path):
    """A second data directory shows up beside the global one, and stays off GET /api/sets."""
    from evid.services.layout import find_set_dir
    from evid.services.set_manager import SetManager

    call(server, "POST", "/api/sets", {"name": "Global"})
    case = tmp_path / "case" / "evid"
    case.mkdir(parents=True)
    SetManager(case).create_set("Interview")
    status, row = call(server, "POST", "/api/roots", {"path": str(case)})
    assert status == 200 and row["name"] == "case" and row["primary"] is False
    rid = row["id"]
    roots = call(server, "GET", "/api/roots")[1]
    assert [r["name"] for r in roots] == ["global", "case"]
    assert roots[0]["id"] == "main" and roots[0]["primary"] is True
    assert "interview" in [s["slug"] for s in roots[1]["sets"]]
    primary = call(server, "GET", "/api/sets")[1]
    assert [s["slug"] for s in primary] == ["global"]
    assert all(s["root"] == "main" for s in primary)
    assert call(server, "GET", f"/api/sets/interview/docs?root={rid}")[0] == 200
    assert call(server, "GET", "/api/sets/interview/docs")[0] == 404
    assert call(server, "POST", f"/api/sets?root={rid}", {"name": "Local"})[0] == 200
    data_dir = Path(call(server, "GET", "/api/config")[1]["data_dir"])
    assert find_set_dir(case, "local") is not None
    assert find_set_dir(data_dir, "local") is None
    there = call(server, "GET", f"/api/sets?root={rid}")[1]
    assert {s["slug"] for s in there} == {"interview", "local"}
    assert "local" not in [s["slug"] for s in call(server, "GET", "/api/sets")[1]]
    assert call(server, "DELETE", "/api/roots/main")[0] == 400
    assert (
        call(server, "POST", "/api/roots", {"path": str(data_dir)})[1]["id"] == "main"
    )
    assert (
        call(server, "POST", "/api/roots", {"path": str(data_dir / "plain")})[0] == 400
    )
    assert (
        call(
            server, "POST", "/api/roots", {"path": str(find_set_dir(case, "interview"))}
        )[0]
        == 400
    )
    assert (
        call(server, "POST", "/api/roots", {"path": str(tmp_path / "missing")})[0]
        == 400
    )
    work = tmp_path / "work"
    work.mkdir()
    made = call(server, "POST", "/api/roots", {"path": str(work / "evid")})
    assert made[0] == 200 and (work / "evid").is_dir() and made[1]["name"] == "work"
    assert call(server, "DELETE", f"/api/roots/{rid}")[0] == 200
    assert find_set_dir(case, "interview") is not None  # disconnect leaves the files
    assert all(r["id"] != rid for r in call(server, "GET", "/api/roots")[1])
    assert call(server, "POST", "/api/roots", {"path": str(case)})[1]["id"] == rid
    saved = yaml.safe_load((data_dir / "roots.yml").read_text())
    assert str(case.resolve()) in saved and str((work / "evid").resolve()) in saved


def test_saved_roots_reload_and_a_bad_file_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    data = tmp_path / "data"
    extra = tmp_path / "case" / "evid"
    extra.mkdir(parents=True)
    app = web.EvidApp(EvidConfig(data_dir=data, editor="true"))
    trunk = app.connect_root(str(extra))
    assert trunk.name == "case" and app.connect_root(str(extra)).id == trunk.id
    app.shutdown()
    again = web.EvidApp(EvidConfig(data_dir=data, editor="true"))
    assert [t.name for t in again.trunks()] == ["global", "case"]
    again.shutdown()
    (data / "roots.yml").write_text(":\n")
    broken = web.EvidApp(EvidConfig(data_dir=data, editor="true"))
    assert [t.id for t in broken.trunks()] == ["main"]
    assert yaml.safe_load((data / "roots.yml").read_text()) == []
    broken.shutdown()
    (data / "roots.yml").write_text("- /no/such/evid-dir\n")
    skipped = web.EvidApp(EvidConfig(data_dir=data, editor="true"))
    assert [t.id for t in skipped.trunks()] == ["main"]
    assert yaml.safe_load((data / "roots.yml").read_text()) == []
    skipped.shutdown()
