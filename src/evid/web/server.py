"""The evid GUI: a loopback HTTP server for ``page.html`` plus a JSON API.

The same page runs in the ``evid-app`` Tauri window and in a browser. Closing
the window stops the server. A second ``evid gui`` on the same data directory
raises the running one instead of starting another.

Guards (local only): the Host header must be loopback (DNS rebinding), and every
mutating ``/api`` request carries ``X-Evid: 1`` (a custom header a foreign page
cannot send without a CORS preflight we never answer).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen

from evid import extras
from evid.config import EvidConfig
from evid.services import doc_ops
from evid.services.set_manager import SetManager
from evid.services.tag_service import TagService
from evid.web.jobs import (
    EventLogHandler,
    Events,
    IndexQueue,
    Jobs,
    LabelWatcher,
    rebuild_labels,
)
from evid.web.term import Sessions, ws_accept

logger = logging.getLogger(__name__)

CONTEXT_CHARS = 600  # vector-hit preview: characters each side of the chunk
LOOPBACK = ("127.0.0.1", "localhost", "::1")


class HTTPError(Exception):
    def __init__(self, status: int, msg: str) -> None:
        super().__init__(msg)
        self.status = status
        self.msg = msg


# ── application state ─────────────────────────────────────────────────────────


class EvidApp:
    """Services and background workers behind the HTTP handler."""

    def __init__(self, config: EvidConfig) -> None:
        self.config = config
        self.data_dir = Path(config.data_dir).expanduser()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sets = SetManager(self.data_dir)
        self.tags = TagService(self.data_dir)
        self.events = Events()
        self.jobs = Jobs(self.events)
        self.watcher = LabelWatcher(self.events)
        self.has_vec = extras.has_vec()
        self._vec = None
        self._vec_lock = threading.Lock()
        self.index = IndexQueue(self.events, before_index=self._release_vec)
        self.temps: dict[str, object] = {}  # fetch token -> TemporaryDirectory
        self._log_handler: logging.Handler | None = None

    # vec ------------------------------------------------------------------

    def vec(self):
        """The search-side VecService (warm across queries)."""
        if not self.has_vec:
            raise HTTPError(400, extras.VEC_INSTALL)
        if self._vec is None:
            from evid.services.vec_service import VecService

            self._vec = VecService()
        return self._vec

    def _release_vec(self, slug: str) -> None:
        """Drop the search client's lock on *slug*'s vecdb before indexing it."""
        if self._vec is not None:
            with self._vec_lock:
                self._vec.close(slug)

    def enqueue_index(self, doc_dir: Path, evidence_set) -> bool:
        if not self.has_vec:
            return False
        self.index.enqueue(doc_dir, evidence_set)
        return True

    # lookups --------------------------------------------------------------

    def evidence_set(self, slug: str):
        if not slug or "/" in slug or slug.startswith("."):
            raise HTTPError(400, f"bad set name: {slug!r}")
        return self.sets.load_set(slug)

    def doc_dir(self, slug: str, uuid: str) -> tuple[Any, Path]:
        es = self.evidence_set(slug)
        try:
            return es, doc_ops.doc_dir_of(es, uuid)
        except ValueError as exc:
            raise HTTPError(400, str(exc)) from exc

    def attach_log(self) -> None:
        """Send evid's INFO+ log records to the page's log pane."""
        evid_log = logging.getLogger("evid")
        evid_log.setLevel(min(evid_log.getEffectiveLevel(), logging.INFO))
        if self._log_handler is None:
            self._log_handler = EventLogHandler(self.events)
            evid_log.addHandler(self._log_handler)

    def shutdown(self) -> None:
        if self._log_handler is not None:
            logging.getLogger("evid").removeHandler(self._log_handler)
            self._log_handler = None
        self.watcher.stop()
        self.index.stop()
        for tmp in self.temps.values():
            with contextlib.suppress(Exception):
                tmp.cleanup()
        self.temps.clear()


# ── serialisation ─────────────────────────────────────────────────────────────


def doc_name(doc_dir: Path) -> str:
    """'Label (uuid8)' for log lines."""
    from evid.utils.yaml_io import load_yaml

    try:
        with (doc_dir / "info.yml").open(encoding="utf-8") as f:
            info = load_yaml(f) or {}
        label = str(info.get("label") or info.get("title") or "")
    except (OSError, ValueError):
        label = ""
    return f"{label} ({doc_dir.name[:8]})" if label else doc_dir.name[:8]


def doc_row(doc) -> dict:
    from evid.services.doc_tags import resolve_doc_pdf

    return {
        "uuid": doc.uuid,
        "label": str(doc.label or ""),
        "tags": list(doc.tags),
        "added": doc.added.strftime("%Y-%m-%d"),
        "indexed": bool(doc.indexed),
        "url": str(doc.source_url or ""),
        "authors": str(doc.authors or ""),
        "note": str(doc.notes or ""),
        "dates": str(doc.dates or ""),
        "has_pdf": resolve_doc_pdf(doc.path) is not None,
        "has_json": (doc.path / "label.json").exists(),
    }


def vec_preview(typ_path: Path, char_start: int, chunk: str) -> dict | None:
    """The chunk in its label.typ context: before / match / after (plain text)."""
    try:
        text = typ_path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text:
        return None
    start = max(0, min(char_start, len(text)))
    end = min(len(text), start + len(chunk))
    lo, hi = max(0, start - CONTEXT_CHARS), min(len(text), end + CONTEXT_CHARS)
    return {
        "before": ("…" if lo > 0 else "") + text[lo:start],
        "match": text[start:end],
        "after": text[end:hi] + ("…" if hi < len(text) else ""),
    }


def label_rows(doc_dir: Path) -> list[dict]:
    from evid.core.prompt import label_entries

    return [
        {
            "key": key,
            "text": str(val.get("text", "") or ""),
            "note": str(val.get("note", "") or ""),
            "page": str(val.get("opage", "") or ""),
            "section": str(val.get("title", "") or ""),
            "raw": val,
        }
        for key, val in label_entries(doc_dir)
    ]


def list_dir(path: str, pdf_only: bool) -> dict:
    """A directory listing for the page's file / folder picker."""
    p = Path(path or ".").expanduser()
    p = p.resolve() if p.exists() else Path.cwd()
    if p.is_file():
        p = p.parent
    entries = []
    try:
        for child in sorted(
            p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())
        ):
            if child.name.startswith("."):
                continue
            is_dir = child.is_dir()
            if pdf_only and not is_dir and child.suffix.lower() != ".pdf":
                continue
            entries.append({"name": child.name, "dir": is_dir})
    except PermissionError as exc:
        raise HTTPError(403, str(exc)) from exc
    return {
        "dir": str(p),
        "parent": str(p.parent) if p.parent != p else "",
        "entries": entries,
    }


# ── HTTP ──────────────────────────────────────────────────────────────────────

PAGE = (resources.files(__package__) / "page.html").read_text("utf-8")
ASSETS = {"evid.svg": "image/svg+xml", "evid.png": "image/png"}
VENDOR = {
    "xterm.js": "text/javascript; charset=utf-8",
    "xterm.css": "text/css; charset=utf-8",
    "addon-fit.js": "text/javascript; charset=utf-8",
}

Route = tuple[str, re.Pattern, str]
ROUTES: list[Route] = []


def route(method: str, pattern: str):
    rx = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$")

    def deco(fn):
        ROUTES.append((method, rx, fn.__name__))
        return fn

    return deco


class Handler(BaseHTTPRequestHandler):
    app: EvidApp
    loopback = True
    in_app = False  # the page is shown in the evid-app window
    window: subprocess.Popen | None = None  # the evid-app process we launched
    url = ""
    raise_file: Path | None = None
    server_version = "evid"
    # proves a terminal connection comes from the page we served
    token = secrets.token_urlsafe(18)
    terms: Sessions | None = None  # the agent pane's terminals
    agent = ""  # what the first terminal runs (empty: a shell)

    def log_message(self, *args):
        pass

    # plumbing -------------------------------------------------------------

    def send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, obj: Any) -> None:
        self.send(
            status,
            json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except ValueError as exc:
            raise HTTPError(400, "invalid JSON") from exc
        if not isinstance(data, dict):
            raise HTTPError(400, "expected a JSON object")
        return data

    def do_GET(self):
        self.dispatch("GET")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_POST(self):
        self.dispatch("POST")

    def do_DELETE(self):
        self.dispatch("DELETE")

    def dispatch(self, method: str) -> None:
        u = urlparse(self.path)
        self.q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if self.loopback:
                host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
                if host not in LOOPBACK:
                    raise HTTPError(403, "bad Host header")
            if (
                u.path.startswith("/api/")
                and method != "GET"
                and self.headers.get("X-Evid") != "1"
            ):
                raise HTTPError(403, "missing X-Evid header")
            for m, rx, name in ROUTES:
                hit = rx.match(u.path)
                if m == method and hit:
                    args = {k: unquote(v) for k, v in hit.groupdict().items()}
                    return getattr(self, name)(**args)
            raise HTTPError(404, "no such endpoint")
        except HTTPError as e:
            self.fail(method, u.path, e.status, e.msg)
        except FileNotFoundError as e:
            self.fail(method, u.path, 404, str(e))
        except (PermissionError, FileExistsError, ValueError) as e:
            self.fail(
                method, u.path, 403 if isinstance(e, PermissionError) else 400, str(e)
            )
        except ConnectionError:
            pass  # the page went away
        except Exception as e:
            logger.exception("%s %s failed", method, u.path)
            with contextlib.suppress(ConnectionError):
                self.send_json(500, {"error": f"{type(e).__name__}: {e}"})

    def fail(self, method: str, path: str, status: int, msg: str) -> None:
        """Answer an error, and put it in the log pane (failed actions are not silent)."""
        if path.startswith("/api/") and path != "/api/events":
            logger.warning("%s %s failed: %s", method, path, msg)
        self.send_json(status, {"error": msg})

    # page -----------------------------------------------------------------

    @route("GET", "/")
    def page(self):
        cfg = json.dumps(self._config())
        self.send(
            200,
            PAGE.replace("/*EVID_CONFIG*/{}", cfg.replace("</", "<\\/")).encode(
                "utf-8"
            ),
            "text/html; charset=utf-8",
        )

    @route("GET", "/vendor/{name}")
    def vendor(self, name: str):
        if name not in VENDOR:
            raise HTTPError(404, "no such file")
        self.send(
            200,
            (resources.files("evid.web") / "vendor" / name).read_bytes(),
            VENDOR[name],
        )

    @route("GET", "/assets/{name}")
    def asset(self, name: str):
        if name not in ASSETS:
            raise HTTPError(404, "no such file")
        self.send(
            200,
            (resources.files("evid.web") / "assets" / name).read_bytes(),
            ASSETS[name],
        )

    def _config(self) -> dict:
        a = self.app
        return {
            "app": self.in_app,
            "data_dir": str(a.data_dir),
            "cwd": str(Path.cwd()),
            "editor": a.config.editor,
            "has_vec": a.has_vec,
            "vec_install": extras.VEC_INSTALL,
            "version": _version(),
            "token": self.token,
            "term": self.terms is not None,
            "agent": self.agent,
            "ptyxis": bool(shutil.which("ptyxis") or shutil.which("gnome-terminal")),
        }

    @route("GET", "/api/config")
    def get_config(self):
        self.send_json(200, self._config())

    @route("GET", "/api/events")
    def get_events(self):
        last, evs = self.app.events.since(int(self.q.get("since", "0") or 0))
        self.send_json(
            200, {"last": last, "events": evs, "pending": self.app.index.pending}
        )

    @route("POST", "/api/log")
    def page_log(self):
        msg = str(self.body().get("msg", ""))[:2000]
        logger.error("page: %s", msg)
        self.send_json(200, {"ok": True})

    # sets -----------------------------------------------------------------

    @route("GET", "/api/sets")
    def list_sets(self):
        out = []
        for s in self.app.sets.list_sets():
            out.append(
                {
                    "slug": s.slug,
                    "name": s.name,
                    "description": s.description,
                    "docs": len(self.app.sets.list_documents(s.slug)),
                }
            )
        self.send_json(200, out)

    @route("POST", "/api/sets")
    def create_set(self):
        name = str(self.body().get("name", "")).strip()
        if not name:
            raise HTTPError(400, "a set needs a name")
        es = self.app.sets.create_set(name)
        logger.info("Created set '%s'", es.slug)
        self.send_json(200, {"slug": es.slug, "name": es.name})

    @route("POST", "/api/sets/import")
    def import_dir(self):
        from evid.services.import_service import import_evid_dir, import_evid_dir_single

        b = self.body()
        src = Path(str(b.get("path", ""))).expanduser()
        if not src.is_dir():
            raise HTTPError(400, f"not a directory: {src}")
        name = str(b.get("name", "")).strip() or src.name
        try:
            import_evid_dir_single(src, name, self.app.sets)
            count = 1
        except ValueError:
            count = len(import_evid_dir(src, self.app.sets))
        logger.info("Imported %d set(s) from %s", count, src)
        self.send_json(200, {"count": count})

    @route("GET", "/api/sets/{slug}/docs")
    def list_docs(self, slug: str):
        self.app.evidence_set(slug)
        docs = doc_ops.collect_documents(self.app.sets, slug)
        self.send_json(200, [doc_row(d) for d in docs])

    @route("POST", "/api/sets/{slug}/index")
    def index_set(self, slug: str):
        if not self.app.has_vec:
            raise HTTPError(400, extras.VEC_INSTALL)
        es = self.app.evidence_set(slug)
        todo = [
            d for d in doc_ops.collect_documents(self.app.sets, slug) if not d.indexed
        ]
        for d in todo:
            self.app.enqueue_index(d.path, es)
        logger.info(
            "Queued %d document(s) of '%s' for vector indexing", len(todo), slug
        )
        self.send_json(200, {"queued": len(todo)})

    @route("POST", "/api/sets/{slug}/delete")
    def delete_docs(self, slug: str):
        uuids = list(self.body().get("uuids") or [])
        for u in uuids:
            _, d = self.app.doc_dir(slug, u)
            name = doc_name(d)
            doc_ops.delete_doc(d)
            logger.info("Deleted %s from '%s'", name, slug)
        self.app.events.emit("docs_changed", slug=slug)
        self.send_json(200, {"deleted": len(uuids)})

    @route("POST", "/api/sets/{slug}/copy")
    def copy_docs(self, slug: str):
        b = self.body()
        dest = self.app.evidence_set(str(b.get("dest", "")))
        if dest.slug == slug:
            raise HTTPError(400, "source and destination are the same set")
        copied = 0
        for u in list(b.get("uuids") or []):
            _, src = self.app.doc_dir(slug, u)
            dest_dir, new = doc_ops.copy_doc(src, dest)
            if new:
                copied += 1
                self.app.enqueue_index(dest_dir, dest)
        logger.info("Copied %d doc(s) to '%s'", copied, dest.slug)
        self.app.events.emit("docs_changed", slug=dest.slug)
        self.send_json(200, {"copied": copied, "dest": dest.slug})

    @route("POST", "/api/sets/{slug}/quotes")
    def quotes(self, slug: str):
        from evid.core.prompt import quotes_markdown, quotes_yaml

        b = self.body()
        dirs = [self.app.doc_dir(slug, u)[1] for u in list(b.get("uuids") or [])]
        fn = quotes_markdown if b.get("format") == "markdown" else quotes_yaml
        self.send_json(200, {"text": fn(dirs)})

    @route("POST", "/api/sets/{slug}/tag")
    def tag_docs(self, slug: str):
        from evid.services.doc_tags import assign_doc_tag, remove_doc_tag

        b = self.body()
        es = self.app.evidence_set(slug)
        tag = str(b.get("tag", "")).strip()
        if not tag:
            raise HTTPError(400, "empty tag")
        if not b.get("remove"):
            tag = self.app.tags.qualify(tag, es.slug)
        fn = remove_doc_tag if b.get("remove") else assign_doc_tag
        n = 0
        for u in list(b.get("uuids") or []):
            _, d = self.app.doc_dir(slug, u)
            n += bool(fn(self.app.tags, es.slug, u, d / "info.yml", tag))
        verb = (
            "Removed tag %s from %d document(s)"
            if b.get("remove")
            else "Tagged %d document(s) with %s"
        )
        args = (tag, n) if b.get("remove") else (n, tag)
        logger.info(verb, *args)
        self.send_json(200, {"tag": tag, "changed": n})

    # one document ---------------------------------------------------------

    @route("GET", "/api/sets/{slug}/docs/{uuid}")
    def get_doc(self, slug: str, uuid: str):
        _, d = self.app.doc_dir(slug, uuid)
        self.send_json(200, {**doc_ops.get_doc(d), "labels": label_rows(d)})

    @route("PUT", "/api/sets/{slug}/docs/{uuid}")
    def put_doc(self, slug: str, uuid: str):
        _, d = self.app.doc_dir(slug, uuid)
        b = self.body()
        out = doc_ops.update_doc(d, b)
        logger.info("Saved details of %s", doc_name(d))
        self.send_json(200, {**out, "labels": label_rows(d)})

    @route("POST", "/api/sets/{slug}/docs/{uuid}/labels-yaml")
    def labels_yaml(self, slug: str, uuid: str):
        from evid.core.prompt import labels_to_yaml

        _, d = self.app.doc_dir(slug, uuid)
        keys = set(self.body().get("keys") or [])
        info = doc_ops.get_doc(d)
        pairs = [(r["key"], r["raw"]) for r in label_rows(d) if r["key"] in keys]
        ref = {
            "uuid": uuid,
            "title": info["title"],
            "authors": info["authors"],
            "url": info["url"],
        }
        self.send_json(200, {"text": labels_to_yaml([(ref, pairs)])})

    @route("POST", "/api/sets/{slug}/docs/{uuid}/open")
    def open_doc(self, slug: str, uuid: str):
        from evid.open_external import open_local_path, open_url
        from evid.services.doc_tags import resolve_doc_pdf

        _, d = self.app.doc_dir(slug, uuid)
        b = self.body()
        what = b.get("what", "dir")
        if what == "pdf":
            pdf = resolve_doc_pdf(d)
            if pdf is None:
                raise HTTPError(404, "this document has no PDF")
            err = open_local_path(pdf)
        elif what == "url":
            url = doc_ops.get_doc(d)["url"]
            if not url:
                raise HTTPError(404, "this document has no URL")
            err = open_url(url)
        elif what == "file":
            # a file from the detail pane's file list: text files go to the editor
            f = doc_ops.doc_path(d, str(b.get("path", "")))
            text = f.is_file() and f.suffix.lower() in doc_ops.TEXT_SUFFIXES
            err = open_local_path(f, editor=self.app.config.editor if text else None)
            if not err and f.suffix.lower() == ".typ":
                self.app.watcher.watch(f, slug, uuid)  # saving it rebuilds the labels
        else:
            err = open_local_path(d)
        if err:
            raise HTTPError(500, err)
        logger.info("Opened %s of %s", b.get("path") or what, doc_name(d))
        self.send_json(200, {"ok": True})

    @route("PUT", "/api/sets/{slug}/docs/{uuid}/annotations")
    def put_annotation(self, slug: str, uuid: str):
        """Set or (empty text) remove the note on a file of the doc ("." = the doc)."""
        from evid.core.annotations import write_annotation

        _, d = self.app.doc_dir(slug, uuid)
        b = self.body()
        path = str(b.get("path", "."))
        notes = write_annotation(d, path, str(b.get("text", "")))
        target = "the document" if path in ("", ".") else path
        logger.info(
            "%s note on %s of %s",
            "Set" if str(b.get("text", "")).strip() else "Removed",
            target,
            doc_name(d),
        )
        self.app.events.emit("docs_changed", slug=slug)
        self.send_json(200, {"annotations": notes})

    @route("GET", "/api/sets/{slug}/docs/{uuid}/files")
    def doc_files(self, slug: str, uuid: str):
        _, d = self.app.doc_dir(slug, uuid)
        sub = self.q.get("sub", "")
        self.send_json(
            200, {"dir": str(d), "sub": sub, "entries": doc_ops.list_doc_files(d, sub)}
        )

    @route("POST", "/api/sets/{slug}/docs/{uuid}/label")
    def label_doc(self, slug: str, uuid: str):
        """Make sure label.typ exists (a job: generating it reads the whole PDF),
        start watching it, and open it in the editor unless ``editor`` is false."""
        from evid.open_external import open_local_path

        _, d = self.app.doc_dir(slug, uuid)
        want_editor = self.body().get("editor", True)
        app = self.app

        def run(progress, _job):
            if not doc_ops.find_label_typ(d).exists():
                progress("Generating label.typ…")
            typ = doc_ops.ensure_label_typ(d)
            app.watcher.watch(typ, slug, uuid)
            if want_editor:
                err = open_local_path(typ, editor=app.config.editor)
                if err:
                    logger.warning("%s", err)
                    raise RuntimeError(err)
            return {"slug": slug, "uuid": uuid, "path": str(typ)}

        jid = app.jobs.start("label", run, f"Label {uuid[:8]}")
        self.send_json(200, {"job": jid})

    @route("GET", "/api/sets/{slug}/docs/{uuid}/typ")
    def get_typ(self, slug: str, uuid: str):
        _, d = self.app.doc_dir(slug, uuid)
        typ = doc_ops.find_label_typ(d)
        if not typ.exists():
            return self.send_json(200, {"exists": False, "path": str(typ)})
        st = typ.stat()
        self.send_json(
            200,
            {
                "exists": True,
                "path": str(typ),
                "content": typ.read_text("utf-8"),
                "mtime": str(st.st_mtime_ns),
            },
        )

    @route("PUT", "/api/sets/{slug}/docs/{uuid}/typ")
    def put_typ(self, slug: str, uuid: str):
        """Save the in-page editor's label.typ, then rebuild label.json / .bib.
        Refuses (409) when the file changed on disk since ``mtime``, unless ``force``.
        ``mtime`` is nanoseconds as a string: as a JSON number it would not survive JS."""
        _, d = self.app.doc_dir(slug, uuid)
        b = self.body()
        typ = doc_ops.find_label_typ(d)
        if (
            typ.exists()
            and not b.get("force")
            and b.get("mtime") is not None
            and str(typ.stat().st_mtime_ns) != str(b["mtime"])
        ):
            return self.send_json(
                409,
                {
                    "error": "label.typ changed on disk",
                    "content": typ.read_text("utf-8"),
                    "mtime": str(typ.stat().st_mtime_ns),
                },
            )
        typ.write_text(str(b.get("content", "")), encoding="utf-8")
        self.app.watcher.watch(typ, slug, uuid)
        self.app.watcher.mark_seen(typ)
        logger.info("Saved %s of %s", typ.name, doc_name(d))
        ok, msg = rebuild_labels(self.app.events, typ, slug, uuid)
        self.send_json(
            200,
            {
                "ok": ok,
                "msg": msg,
                "mtime": str(typ.stat().st_mtime_ns),
                "labels": label_rows(d),
            },
        )

    # tags -----------------------------------------------------------------

    @route("GET", "/api/tags")
    def list_tags(self):
        self.send_json(200, sorted(t.name for t in self.app.tags.list_tags()))

    @route("POST", "/api/tags")
    def create_tag(self):
        b = self.body()
        es = self.app.evidence_set(str(b.get("slug", "")))
        name = self.app.tags.qualify(str(b.get("name", "")).strip(), es.slug)
        try:
            self.app.tags.get_tag(name)
        except KeyError:
            self.app.tags.create_tag(name, es.slug)
            logger.info("Created tag %s", name)
        self.send_json(200, {"tag": name})

    # ingest ---------------------------------------------------------------

    @route("POST", "/api/ingest/meta")
    def ingest_meta(self):
        from evid.core.pdf_metadata import extract_pdf_metadata

        p = Path(str(self.body().get("path", ""))).expanduser()
        if not p.is_file():
            raise HTTPError(404, f"no such file: {p}")
        title, authors, dates = extract_pdf_metadata(p, p.name)
        self.send_json(
            200,
            {
                "path": str(p.resolve()),
                "title": title,
                "authors": authors,
                "dates": dates,
                "label": title,
            },
        )

    @route("POST", "/api/fetch")
    def fetch_url(self):
        from evid.core.pdf_metadata import extract_pdf_metadata
        from evid.services.doc_ingester import resolve_source

        url = str(self.body().get("url", "")).strip()
        if not url.startswith(("http://", "https://")):
            raise HTTPError(400, "enter an http(s) URL")
        app = self.app

        def run(progress, job):
            progress(f"Fetching {url}")
            logger.info("Fetching URL: %s", url)
            res = resolve_source(url)
            if job["cancelled"]:
                if res.temp_dir is not None:
                    with contextlib.suppress(Exception):
                        res.temp_dir.cleanup()
                return None
            token = secrets.token_hex(8)
            if res.temp_dir is not None:
                app.temps[token] = res.temp_dir
            logger.info(
                "URL fetch complete — %s (title=%r)", res.pdf_path.name, res.title
            )
            # Like a local PDF: fill what the page did not say from the PDF itself.
            try:
                auto_title, auto_authors, auto_dates = extract_pdf_metadata(
                    res.pdf_path, res.pdf_path.name
                )
            except Exception:
                logger.exception("Could not read metadata from %s", res.pdf_path)
                auto_title, auto_authors, auto_dates = "", "", ""
            title = res.title or auto_title or res.pdf_path.stem
            return {
                "path": str(res.pdf_path),
                "title": title,
                "authors": res.authors or auto_authors,
                "dates": res.dates or auto_dates,
                "label": title,
                "url": res.source_url or url,
                "source_name": res.original_name or "",
                "token": token,
            }

        self.send_json(200, {"job": app.jobs.start("fetch", run, f"Fetching {url}")})

    @route("POST", "/api/ingest")
    def ingest(self):
        """Add one PDF (fast: no vector index — that goes to the background queue)."""
        from evid.services.doc_ingester import DocIngester
        from evid.services.doc_tags import parse_tags_field

        b = self.body()
        app = self.app
        es = app.evidence_set(str(b.get("slug", "")))
        pdf = Path(str(b.get("path", ""))).expanduser()
        if not pdf.is_file():
            raise HTTPError(404, f"no such file: {pdf}")
        temp_dir = app.temps.pop(str(b.get("token", "")), None)
        tags = b.get("tags")
        tags = (
            [str(t).strip() for t in tags if str(t).strip()]
            if isinstance(tags, list)
            else parse_tags_field(str(tags or ""))
        )

        def run(progress, _job):
            ing = DocIngester(vec_service=None)
            ing.progress = lambda _s, _n, msg: progress(f"{msg}…")
            doc = ing.ingest(
                pdf_path=pdf,
                evidence_set=es,
                label=str(b.get("label", "")),
                title=str(b.get("title", "")),
                authors=str(b.get("authors", "")),
                dates=str(b.get("dates", "")),
                tags=tags,
                source_url=str(b.get("url", "")),
                temp_dir=temp_dir,
                do_index=False,
                source_name=str(b.get("source_name", "")),
            )
            existing = bool(ing.last_was_existing)
            if not existing:
                app.enqueue_index(es.path / "docs" / doc.uuid, es)
            app.events.emit("docs_changed", slug=es.slug)
            if existing:
                logger.info(
                    "%s is already in '%s' (%s)", pdf.name, es.slug, doc.uuid[:8]
                )
            else:
                logger.info(
                    "Added %s to '%s' as %s",
                    pdf.name,
                    es.slug,
                    doc_name(es.path / "docs" / doc.uuid),
                )
            return {"slug": es.slug, "uuid": doc.uuid, "existing": existing}

        self.send_json(
            200, {"job": app.jobs.start("ingest", run, f"Adding {pdf.name}")}
        )

    @route("POST", "/api/jobs/{jid}/cancel")
    def cancel_job(self, jid: str):
        self.send_json(200, {"ok": self.app.jobs.cancel(int(jid))})

    # search ---------------------------------------------------------------

    @route("POST", "/api/search/meta")
    def search_meta(self):
        from evid.core.doc_loader import search_meta_documents

        b = self.body()
        es = self.app.evidence_set(str(b.get("slug", "")))
        docs = search_meta_documents(es.path, str(b.get("pattern", "")))
        logger.info(
            "Meta search %r in '%s': %d document(s)",
            str(b.get("pattern", "")),
            es.slug,
            len(docs),
        )
        self.send_json(200, [doc_row(d) for d in docs])

    @route("POST", "/api/search/vec")
    def search_vec(self):
        b = self.body()
        es = self.app.evidence_set(str(b.get("slug", "")))
        n = max(1, min(100, int(b.get("n", 10) or 10)))
        vec = self.app.vec()
        with self.app._vec_lock:
            results = vec.query(es, str(b.get("query", "")), n_results=n)
        logger.info(
            "Vector search %r in '%s': %d hit(s)",
            str(b.get("query", "")),
            es.slug,
            len(results),
        )
        out = []
        for r in results:
            out.append(
                {
                    **doc_row(r.doc),
                    "score": r.score,
                    "chunk_idx": r.chunk_idx,
                    "chunk": r.chunk_text,
                    "preview": vec_preview(
                        es.path / "docs" / r.doc.uuid / "label.typ",
                        r.char_start,
                        r.chunk_text,
                    ),
                }
            )
        self.send_json(200, out)

    @route("POST", "/api/search/text")
    def search_text(self):
        from evid.core.fulltext import search_fulltext

        b = self.body()
        es = self.app.evidence_set(str(b.get("slug", "")))
        n = max(1, min(100, int(b.get("n", 10) or 10)))
        hits = search_fulltext(
            es.path, str(b.get("query", "")), regex=bool(b.get("regex")), n=n
        )
        logger.info(
            "Full-text search %r in '%s': %d hit(s)",
            str(b.get("query", "")),
            es.slug,
            len(hits),
        )
        self.send_json(
            200,
            [
                {
                    "uuid": h.uuid,
                    "label": h.label,
                    "page": h.page,
                    "snippet": h.snippet,
                    "score": h.score,
                }
                for h in hits
            ],
        )

    # files / window -------------------------------------------------------

    @route("GET", "/api/files")
    def files(self):
        self.send_json(200, list_dir(self.q.get("dir", ""), self.q.get("pdf") == "1"))

    @route("POST", "/api/open-path")
    def open_path(self):
        from evid.open_external import open_local_path

        err = open_local_path(str(self.body().get("path", "")))
        if err:
            raise HTTPError(500, err)
        self.send_json(200, {"ok": True})

    @route("POST", "/api/raise")
    def raise_window(self):
        """A second `evid gui`: bring this one forward (or reopen it)."""
        raise_window()
        self.send_json(200, {"ok": True})

    # agent pane --------------------------------------------------------------

    def sessions(self) -> Sessions:
        if self.terms is None:
            raise HTTPError(404, "the agent pane is off")
        return self.terms

    @route("GET", "/api/terms")
    def list_terms(self):
        self.send_json(200, {"terms": self.sessions().list()})

    @route("POST", "/api/term/new")
    def new_term(self):
        terms = self.sessions()
        sid = terms.add(str(self.body().get("agent") or ""))
        logger.info("Agent pane: new terminal %s", terms.get(sid).label())
        self.send_json(200, {"id": sid, "terms": terms.list()})

    @route("POST", "/api/term/close")
    def close_term(self):
        terms = self.sessions()
        if not terms.close(str(self.body().get("id", ""))):
            raise HTTPError(404, "no such terminal")
        self.send_json(200, {"terms": terms.list()})

    @route("POST", "/api/term/external")
    def external_term(self):
        terms = self.sessions()
        cmd = external_terminal(Path(terms.cwd), terms.env, self.agent)
        self.send_json(200, {"ok": True, "cmd": cmd})

    @route("GET", "/api/term")
    def terminal(self):
        """Upgrade to a WebSocket onto one of the agent pane's terminals (?id=, default the first)."""
        terms = self.sessions()
        term = terms.get(self.q.get("id") or next(iter(terms.terms), ""))
        if term is None:
            raise HTTPError(404, "no such terminal")
        if not secrets.compare_digest(self.q.get("token", ""), self.token):
            raise HTTPError(403, "bad terminal token")
        if self.headers.get("Origin") != f"http://{self.headers.get('Host')}":
            raise HTTPError(403, "terminal connections must come from the evid page")
        key = self.headers.get("Sec-WebSocket-Key")
        if not key or "websocket" not in (self.headers.get("Upgrade") or "").lower():
            raise HTTPError(400, "expected a WebSocket upgrade")
        self.protocol_version = (
            "HTTP/1.1"  # WebKit (the app window) rejects a 101 sent as HTTP/1.0
        )
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", ws_accept(key))
        self.end_headers()
        self.wfile.flush()
        self.close_connection = True
        with contextlib.suppress(
            OSError
        ):  # the page went away; never answer an upgraded socket with HTTP
            term.serve(self.connection, self.rfile)

    @route("POST", "/api/quit")
    def quit(self):
        self.send_json(200, {"ok": True})
        if Handler.window is not None:
            Handler.window.terminate()  # serve_gui() then stops the server
        else:
            threading.Thread(target=self.server.shutdown, daemon=True).start()


def external_terminal(cwd: Path, env: dict, agent: str) -> str:
    """Open the agent (or a shell) in Ptyxis / GNOME Terminal. The env goes on the command line,
    because these terminals hand new windows to an already running instance."""
    shell = env.get("SHELL") or "/bin/sh"
    keep = [
        f"{k}={v}"
        for k, v in env.items()
        if k.startswith("EVID_") and k != "EVID_IN_APP"
    ]
    inner = [shell, "-ic", f"{agent}; exec {shell}"] if agent else [shell, "-i"]
    run = ["env", *keep, *inner]
    if shutil.which("ptyxis"):
        cmd = ["ptyxis", "--new-window", "--working-directory", str(cwd), "--", *run]
    elif shutil.which("gnome-terminal"):
        cmd = ["gnome-terminal", f"--working-directory={cwd}", "--", *run]
    else:
        raise HTTPError(404, "neither ptyxis nor gnome-terminal is installed")
    subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return " ".join(cmd[:4])


def terminal_env(data_dir: Path, url: str) -> dict:
    """The environment of the agent pane: `evid` there uses this GUI's data dir (EVID_DB)."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("EVID_IN_APP", "EVID_RAISE_FILE")
    }
    env.update(
        TERM="xterm-256color",
        COLORTERM="truecolor",
        EVID_DB=str(data_dir),
        EVID_URL=url,
    )
    return env


def raise_window() -> None:
    win = Handler.window
    app_alive = (win is not None and win.poll() is None) or os.environ.get(
        "EVID_IN_APP"
    ) == "1"
    if app_alive and Handler.raise_file is not None:
        Handler.raise_file.write_text(str(time.time()))  # evid-app polls this file
        return
    exe = find_app()
    if exe:
        Handler.window = subprocess.Popen([exe, "--url", Handler.url, *_raise_args()])
    else:
        webbrowser.open(Handler.url)


def _raise_args() -> list[str]:
    return ["--raise-file", str(Handler.raise_file)] if Handler.raise_file else []


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("evid")
    except PackageNotFoundError:
        return ""


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], ConnectionError):
            super().handle_error(request, client_address)


# ── launch ────────────────────────────────────────────────────────────────────


def find_app() -> str | None:
    """The evid-app window: $EVID_APP, else evid-app on PATH, else the newest build in app/target."""
    env = os.environ.get("EVID_APP")
    if env:
        return env if os.access(env, os.X_OK) else None
    hit = shutil.which("evid-app")
    if hit:
        return hit
    target = Path(__file__).resolve().parents[3] / "app" / "target"
    builds = [
        b
        for b in (target / "release" / "evid-app", target / "debug" / "evid-app")
        if b.is_file() and os.access(b, os.X_OK)
    ]
    return str(max(builds, key=lambda b: b.stat().st_mtime)) if builds else None


def _runtime_dir() -> Path:
    d = Path(os.environ.get("XDG_RUNTIME_DIR") or Path.home() / ".cache" / "evid")
    d.mkdir(parents=True, exist_ok=True)
    return d


def lock_path(data_dir: Path) -> Path:
    key = hashlib.sha1(
        str(Path(data_dir).expanduser().resolve()).encode(), usedforsecurity=False
    ).hexdigest()[:12]
    return _runtime_dir() / f"evid-gui-{key}.json"


def running_instance(data_dir: Path) -> str | None:
    """The URL of a live evid GUI for *data_dir*, if one answers."""
    lp = lock_path(data_dir)
    try:
        info = json.loads(lp.read_text())
        url = info["url"]
        with urlopen(Request(url + "api/config"), timeout=2) as r:
            cfg = json.loads(r.read())
        if Path(cfg.get("data_dir", "")) == Path(data_dir).expanduser().resolve():
            return url
    except (OSError, ValueError, KeyError, URLError):
        return None
    return None


def ask_raise(url: str) -> bool:
    try:
        with urlopen(
            Request(
                url + "api/raise",
                data=b"{}",
                method="POST",
                headers={"X-Evid": "1", "Content-Type": "application/json"},
            ),
            timeout=3,
        ):
            return True
    except (OSError, URLError):
        return False


def serve_gui(
    config: EvidConfig,
    *,
    port: int = 8790,
    browser: bool = False,
    headless: bool = False,
    agent: str = "",
) -> None:
    """Serve the GUI on 127.0.0.1 and show it in evid-app (else the browser).

    The agent pane's first terminal runs *agent* (or $EVID_AGENT; empty: a shell)
    in the current directory, with ``EVID_DB`` set to the data dir.

    Closing the window stops the server. With *headless* nothing is opened (the
    server runs until Ctrl+C or ``/api/quit``).
    """
    config.data_dir = Path(config.data_dir).expanduser().resolve()
    url = running_instance(config.data_dir)
    if url and ask_raise(url):
        print(f"Raised the running evid GUI ({url}).")
        return

    app = EvidApp(config)
    Handler.app = app
    srv = None
    for p in range(port, port + 20):
        try:
            srv = Server(("127.0.0.1", p), Handler)
            break
        except OSError:
            continue
    if srv is None:
        sys.exit(f"evid: no free port in {port}-{port + 19}")
    url = f"http://127.0.0.1:{srv.server_port}/"
    Handler.url = url
    lp = lock_path(config.data_dir)
    lp.write_text(json.dumps({"url": url, "pid": os.getpid()}))
    # evid-app started us (EVID_IN_APP) and watches its own raise file; else we pass ours
    Handler.raise_file = (
        Path(os.environ["EVID_RAISE_FILE"])
        if os.environ.get("EVID_RAISE_FILE")
        else lp.with_suffix(".raise")
    )

    app.attach_log()
    Handler.agent = agent or os.environ.get("EVID_AGENT", "")
    Handler.terms = Sessions(
        str(Path.cwd()), terminal_env(config.data_dir, url), Handler.agent
    )

    print(
        f"evid  {config.data_dir}\n  open {url}\n  agent {Handler.agent or 'shell'} (Agent pane)"
    )
    exe = None if headless or browser else find_app()
    Handler.in_app = bool(exe) or os.environ.get("EVID_IN_APP") == "1"
    try:
        if exe:
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            Handler.window = subprocess.Popen([exe, "--url", url, *_raise_args()])
            try:
                while (
                    True
                ):  # a raise may relaunch the window; stop once it stays closed
                    Handler.window.wait()
                    time.sleep(0.3)
                    if Handler.window.poll() is not None:
                        break
            except KeyboardInterrupt:
                Handler.window.terminate()
            finally:
                srv.shutdown()
            return
        if not headless and not browser:
            print(
                "  (evid-app not built — `make app-build` or set EVID_APP; using the browser)"
            )
        print("  (Ctrl+C to stop)")
        if not headless:
            threading.Timer(0.4, webbrowser.open, [url]).start()
        with contextlib.suppress(KeyboardInterrupt):
            srv.serve_forever()
    finally:
        if Handler.terms is not None:
            Handler.terms.stop()
        app.shutdown()
        srv.server_close()
        with contextlib.suppress(OSError):
            if json.loads(lp.read_text()).get("pid") == os.getpid():
                lp.unlink()
        with contextlib.suppress(OSError):
            Handler.raise_file.unlink()
