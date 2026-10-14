"""The evid GUI: a loopback HTTP server for ``page.html`` plus a JSON API.

The same page runs in the ``evid-app`` Tauri window and in a browser. Closing
the window stops a server this process started. A second ``evid gui`` on the
same data directory does not start another server: it opens the Tauri window
on the one already running, or raises that window when it is already open.

More than one data directory can be open in that one window. Each directory is
a trunk in the set tree. The configured directory is the primary trunk
(``global``). ``GET /api/sets`` without ``?root=`` is that primary directory,
so callers that list sets keep seeing only it.

Guards (local only): the Host header must be loopback (DNS rebinding), and every
mutating ``/api`` request carries ``X-Evid: 1`` (a custom header a foreign page
cannot send without a CORS preflight we never answer).
"""

from __future__ import annotations

import base64
import contextlib
import contextvars
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
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.error import HTTPError as UrlHTTPError
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
)
from evid.web.live import DiskWatch
from evid.web.roots import (
    PRIMARY,
    disambiguate,
    is_set_dir,
    label_for,
    load_saved,
    prepare,
    root_id,
    save_saved,
)
from evid.web.roots import overlaps as paths_overlap
from evid.web.term import Sessions, ws_accept

logger = logging.getLogger(__name__)

CONTEXT_CHARS = 600  # vector-hit preview: characters each side of the chunk
LOOPBACK = ("127.0.0.1", "localhost", "::1")
# Which trunk the request is aimed at. Empty means the primary data directory.
# Set from ``?root=`` — the body is read once, so the root cannot travel there.
_ROOT: contextvars.ContextVar[str] = contextvars.ContextVar("evid_root", default="")


class HTTPError(Exception):
    def __init__(self, status: int, msg: str) -> None:
        super().__init__(msg)
        self.status = status
        self.msg = msg


# ── application state ─────────────────────────────────────────────────────────


@dataclass
class Trunk:
    """One connected data directory: its sets, its tags, and its own disk watch."""

    id: str
    path: Path
    name: str
    primary: bool
    sets: SetManager
    tags: TagService
    disk: DiskWatch


class EvidApp:
    """Services and background workers behind the HTTP handler."""

    def __init__(self, config: EvidConfig) -> None:
        self.config = config
        self.data_dir = Path(config.data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.events = Events()
        self.jobs = Jobs(self.events)
        self.has_vec = extras.has_vec()
        self._vec = None
        self._vec_lock = threading.Lock()
        self._roots_lock = threading.RLock()
        self._trunks: dict[str, Trunk] = {}
        self._order: list[str] = []
        self._watching = False
        primary = self._make_trunk(PRIMARY, self.data_dir, primary=True, name="global")
        self._trunks[PRIMARY] = primary
        self._order.append(PRIMARY)
        self._load_saved_roots()
        # The index thread outlives the request, so it cannot see ``_ROOT``.
        # ``note_index`` finds the document's trunk by the set slug.
        self.index = IndexQueue(
            self.events, before_index=self._release_vec, on_write=self.note_index
        )
        self.temps: dict[str, object] = {}  # fetch token -> TemporaryDirectory
        self._log_handler: logging.Handler | None = None

    def _make_trunk(self, rid: str, path: Path, *, primary: bool, name: str) -> Trunk:
        path.mkdir(parents=True, exist_ok=True)
        return Trunk(
            id=rid,
            path=path,
            name=name,
            primary=primary,
            sets=SetManager(path),
            tags=TagService(path),
            disk=DiskWatch(path, self.events, root_id="" if primary else rid),
        )

    def _save_locked(self) -> None:
        paths = [
            self._trunks[i].path
            for i in self._order
            if i != PRIMARY and i in self._trunks
        ]
        save_saved(self.data_dir, paths)

    def _load_saved_roots(self) -> None:
        saved, dirty = load_saved(self.data_dir)
        kept: list[Path] = []
        with self._roots_lock:
            taken = {t.name for t in self._trunks.values()}
            for raw in saved:
                try:
                    path = Path(raw).expanduser().resolve()
                except OSError:
                    dirty = True
                    continue
                if not path.is_dir() or is_set_dir(path):
                    dirty = True
                    continue
                if any(
                    t.path == path or paths_overlap(t.path, path)
                    for t in self._trunks.values()
                ):
                    dirty = True
                    continue
                rid = root_id(path)
                if rid in self._trunks:
                    dirty = True
                    continue
                name = disambiguate(label_for(path, primary=False), taken)
                taken.add(name)
                trunk = self._make_trunk(rid, path, primary=False, name=name)
                self._trunks[rid] = trunk
                self._order.append(rid)
                kept.append(path)
            if dirty or [str(p) for p in kept] != _resolved(saved):
                self._save_locked()

    def trunks(self) -> list[Trunk]:
        with self._roots_lock:
            return [self._trunks[i] for i in self._order if i in self._trunks]

    def trunk(self, root: str | None = None) -> Trunk:
        """The trunk for *root*, or the one named by ``?root=`` on this request.

        Empty and ``main`` are the primary data directory.
        """
        if root is None:
            root = _ROOT.get()
        if root == PRIMARY:
            root = ""
        with self._roots_lock:
            if not root:
                return self._trunks[PRIMARY]
            found = self._trunks.get(root)
        if found is None:
            raise HTTPError(404, f"no such data directory: {root}")
        return found

    @property
    def sets(self) -> SetManager:
        """Set manager of the trunk this request is aimed at (primary when none)."""
        return self.trunk(None).sets

    @property
    def tags(self) -> TagService:
        return self.trunk(None).tags

    @property
    def disk(self) -> DiskWatch:
        """The primary directory's watch. Tests and startup use this."""
        return self._trunks[PRIMARY].disk

    def connect_root(self, raw: str) -> Trunk:
        """Connect a data directory. The same path again returns the trunk already open."""
        path = prepare(raw)
        with self._roots_lock:
            for t in self._trunks.values():
                if t.path == path:
                    return t
            for t in self._trunks.values():
                if paths_overlap(t.path, path):
                    raise ValueError(
                        f"{path} overlaps the connected directory {t.path}"
                    )
            rid = root_id(path)
            extra = 0
            while rid in self._trunks:
                extra += 1
                rid = hashlib.sha256(
                    f"{path}\n{extra}".encode(), usedforsecurity=False
                ).hexdigest()[:8]
            name = disambiguate(
                label_for(path, primary=False),
                {t.name for t in self._trunks.values()},
            )
            trunk = self._make_trunk(rid, path, primary=False, name=name)
            self._trunks[rid] = trunk
            self._order.append(rid)
            self._save_locked()
            watching = self._watching
        if watching:
            trunk.disk.start()
        self.events.emit("sets_changed")
        logger.info("Connected data directory %s as %s", path, name)
        return trunk

    def disconnect_root(self, rid: str) -> None:
        """Drop a trunk from the tree. The directory and its files stay on disk."""
        if not rid or rid == PRIMARY:
            raise ValueError("the global data directory stays connected")
        with self._roots_lock:
            trunk = self._trunks.get(rid)
            if trunk is None:
                raise FileNotFoundError(f"no such data directory: {rid}")
            if trunk.primary:
                raise ValueError("the global data directory stays connected")
            self._order.remove(rid)
            del self._trunks[rid]
            self._save_locked()
        trunk.disk.stop()
        self.events.emit("sets_changed")
        logger.info("Disconnected data directory %s", trunk.path)

    def start_watches(self) -> None:
        """Watch every trunk. A directory connected later is watched too."""
        with self._roots_lock:
            self._watching = True
            trunks = list(self._trunks.values())
        for t in trunks:
            t.disk.start()

    def note(self, slug: str, uuid: str = "") -> None:
        """The GUI is about to write *slug* in the trunk this request is aimed at."""
        self.trunk(None).disk.touch(slug, uuid)

    def note_index(self, slug: str, uuid: str) -> None:
        """Mark a GUI write from the index thread, which has no request trunk.

        The same slug in two trunks is touched in both. That is rare, and a
        touch only tells the page the next change was ours.
        """
        from evid.services.layout import find_set_dir

        hit = False
        for t in self.trunks():
            if find_set_dir(t.path, slug) is not None:
                t.disk.touch(slug, uuid)
                hit = True
        if not hit:
            self.disk.touch(slug, uuid)

    def emit_docs(self, slug: str, root: str | None = None) -> None:
        """``docs_changed`` for *slug*. A non-primary trunk names itself."""
        rid = self.trunk(root).id
        if rid == PRIMARY:
            self.events.emit("docs_changed", slug=slug)
        else:
            self.events.emit("docs_changed", slug=slug, root=rid)

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

    def enqueue_index(
        self, doc_dir: Path, evidence_set, root: str | None = None
    ) -> bool:
        if not self.has_vec:
            return False
        rid = self.trunk(root).id
        self.index.enqueue(doc_dir, evidence_set, "" if rid == PRIMARY else rid)
        return True

    # lookups --------------------------------------------------------------

    def evidence_set(self, slug: str, root: str | None = None):
        if not slug or "/" in slug or slug.startswith("."):
            raise HTTPError(400, f"bad set name: {slug!r}")
        return self.trunk(root).sets.load_set(slug)

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
        for t in self.trunks():
            t.disk.stop()
        self.index.stop()
        for tmp in self.temps.values():
            with contextlib.suppress(Exception):
                tmp.cleanup()
        self.temps.clear()


# ── serialisation ─────────────────────────────────────────────────────────────


def _resolved(paths: list[Path]) -> list[str] | None:
    out = []
    for p in paths:
        try:
            out.append(str(Path(p).expanduser().resolve()))
        except OSError:
            return None
    return out


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
        "has_json": (doc.path / "label" / "labels.json").exists(),
        "nlabels": count_labels(doc.path),
        "nmachine": count_machine(doc.path),
        "nstale": count_stale(doc.path),
    }


def count_stale(doc_dir: Path) -> int:
    """Labels, annotations and machine quotes that lost their place (after a replace)."""
    from evid.core.quote_pass import MACHINE_DIR

    n = 0
    p = doc_dir / "label" / "labels.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        for kind in ("labels", "annotations"):
            n += sum(
                1 for r in data.get(kind) or [] if isinstance(r, dict) and r.get("lost")
            )
        for f in (doc_dir / MACHINE_DIR).glob("*.json"):
            found = (json.loads(f.read_text(encoding="utf-8")) or {}).get("found") or []
            n += sum(1 for q in found if isinstance(q, dict) and q.get("lost"))
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning("Could not count the stale labels of %s: %s", doc_dir.name, exc)
    return n


def count_labels(doc_dir: Path) -> int:
    """How many manual labels the doc has (``label/labels.json``)."""
    p = doc_dir / "label" / "labels.json"
    if not p.exists():
        return 0
    try:
        rows = (json.loads(p.read_text(encoding="utf-8")) or {}).get("labels") or []
        return sum(1 for r in rows if not (isinstance(r, dict) and r.get("lost")))
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning("Could not count the labels of %s: %s", doc_dir.name, exc)
        return 0


def count_machine(doc_dir: Path) -> int:
    """How many machine quotes the doc shows (``pass/*.json`` ``found``, not lost)."""
    from evid.core.quote_pass import MACHINE_DIR

    folder = doc_dir / MACHINE_DIR
    if not folder.is_dir():
        return 0
    n = 0
    for path in folder.glob("*.json"):
        try:
            found = (json.loads(path.read_text(encoding="utf-8")) or {}).get(
                "found"
            ) or []
        except (OSError, ValueError, AttributeError) as exc:
            logger.warning(
                "Could not count the machine quotes of %s: %s", path.name, exc
            )
            continue
        n += sum(1 for q in found if isinstance(q, dict) and not q.get("lost"))
    return n


def vec_preview(typ_path: Path, char_start: int, chunk: str) -> dict | None:
    """The chunk in its context in the document's text (label/text.txt): before / match / after."""
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


def text_view(doc_dir: Path) -> dict:
    """Canonical text, page bands, and the human and machine records on it."""
    from evid.core.labels import adopt_legacy_document_note, ensure_text, read
    from evid.core.quote_pass import found_with_notes, list_passes

    adopt_legacy_document_note(doc_dir)
    text, pages = ensure_text(doc_dir)
    data = read(doc_dir)

    def one(rec: dict, field: str) -> dict:
        return {
            field: rec[field],
            "start": rec.get("start"),
            "end": rec.get("end"),
            "page": rec.get("page"),
            "text": rec.get("text") or "",
            "notes": list(rec.get("notes") or []),
        }

    passes = []
    for qp in list_passes(doc_dir):
        quotes = [
            {
                "key": q.get("key"),
                "start": q.get("start"),
                "end": q.get("end"),
                "page": q.get("page"),
                "text": q.get("text") or "",
                "notes": list(q.get("notes") or []),
            }
            for q in found_with_notes(qp)
            if not q.get("lost") and "start" in q
        ]
        passes.append(
            {
                "id": qp.id,
                "timestamp": qp.timestamp,
                "model": qp.model,
                "job": qp.job,
                "matched": sum(1 for r in qp.results if r.matched),
                "tried": len(qp.results),
                "quotes": quotes,
            }
        )
    mig = doc_dir / "label" / "migration.json"
    unplaced = []
    if mig.is_file():
        try:
            raw = json.loads(mig.read_text(encoding="utf-8")) or {}
        except (OSError, json.JSONDecodeError):
            raw = {}
        unplaced = [
            {
                "key": r.get("key") or "",
                "text": r.get("text") or "",
                "score": r.get("score"),
            }
            for r in raw.get("unplaced") or []
            if isinstance(r, dict)
        ]
    return {
        "text": text,
        "pages": pages,
        "labels": [one(r, "key") for r in data["labels"] if not r.get("lost")],
        "annotations": [one(r, "id") for r in data["annotations"] if not r.get("lost")],
        "document": [
            {
                "id": rec.get("id") or "",
                "kind": rec.get("kind") or "annotation",
                "key": rec.get("key") or "",
                "created": rec.get("created") or "",
                "by": rec.get("by") or "",
                "notes": list(rec.get("notes") or []),
            }
            for rec in data.get("document") or []
            if isinstance(rec, dict)
        ],
        "stale": [
            {
                "kind": kind[:-1],
                "key": r.get("key") or r.get("id") or "",
                "text": r.get("text") or "",
            }
            for kind in ("labels", "annotations")
            for r in data[kind]
            if r.get("lost")
        ],
        "passes": passes,
        "unplaced": unplaced,
    }


def _span_from_body(doc_dir: Path, body: dict):
    """A span from ``start``/``end``, or from a ``text`` passage to locate."""
    from evid.core.labels import span_at, span_of

    if "start" in body and "end" in body:
        return span_at(doc_dir, int(body["start"]), int(body["end"]))
    passage = str(body.get("text") or "")
    if not passage.strip():
        raise HTTPError(400, "select a passage")
    span, _score, _how = span_of(doc_dir, passage)
    return span


def _missing(exc: KeyError) -> HTTPError:
    msg = str(exc.args[0]) if exc.args else "not found"
    return HTTPError(404, msg)


def _note_index(raw: str) -> int:
    if not str(raw).isdigit():
        raise HTTPError(400, "bad note index")
    return int(raw)


def _commit_view(doc_dir: Path, verb: str) -> dict:
    """Commit ``label/`` and ``pass/``, then return the reader payload."""
    from evid.core.bibtex_utils import load_title
    from evid.core.gitops import commit_labels

    title = load_title(doc_dir / "info.yml") or doc_dir.name[:8]
    view = text_view(doc_dir)
    view["commit"] = commit_labels(doc_dir, f"label: {title} ({verb})")
    return view


def _screenshot_sources(pages: list, dest: Path) -> list[str]:
    """Ordered image paths. Pasted pages are written under *dest*."""
    from evid.services.screenshots import IMAGE_SUFFIXES

    sources: list[str] = []
    for i, page in enumerate(pages):
        raw_path = str(page.get("path") or "").strip()
        if raw_path:
            sources.append(raw_path)
            continue
        payload = str(page.get("png_base64") or "")
        if "," in payload and payload.lstrip().lower().startswith("data:"):
            payload = payload.split(",", 1)[1]
        try:
            data = base64.b64decode(payload, validate=True)
        except ValueError as exc:
            raise ValueError(f"Cannot read pasted image {i + 1}.") from exc
        if not data:
            raise ValueError(f"Cannot read pasted image {i + 1}.")
        suffix = Path(str(page.get("name") or "")).suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            suffix = ".png"
        out = dest / f"paste-{i:04d}{suffix}"
        out.write_bytes(data)
        sources.append(str(out))
    return sources


def list_dir(path: str, pdf_only: bool, images_only: bool = False) -> dict:
    """A directory listing for the page's file / folder picker."""
    from evid.services.screenshots import IMAGE_SUFFIXES, natural_name

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
            if (
                images_only
                and not is_dir
                and child.suffix.lower() not in IMAGE_SUFFIXES
            ):
                continue
            entries.append({"name": child.name, "dir": is_dir})
    except PermissionError as exc:
        raise HTTPError(403, str(exc)) from exc
    if images_only:
        # page2 before page10, so a folder of captures is already page order.
        entries.sort(key=lambda e: (not e["dir"], natural_name(e["name"])))
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
    headless = False  # embedded server: /api/raise must not open evid-app or a browser
    window: subprocess.Popen | None = None  # the evid-app process we launched
    url = ""
    raise_file: Path | None = None
    server_version = "evid"
    # proves a terminal connection comes from the page we served
    token = secrets.token_urlsafe(18)
    agents: SetAgents | None = None  # the agent pane's terminals, per evidence set
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
        token = _ROOT.set(self.q.get("root") or "")
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
        finally:
            _ROOT.reset(token)

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
            "term": self.agents is not None,
            "agent": self.agent,
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

    def _set_rows(self, trunk: Trunk) -> list[dict]:
        agents = self.agents.summary() if self.agents is not None else {}
        rows = []
        for s in trunk.sets.list_sets():
            key = s.slug if trunk.primary else f"{trunk.id}/{s.slug}"
            rows.append(
                {
                    "slug": s.slug,
                    "name": s.name,
                    "type": s.set_type.value,
                    "description": s.description,
                    "docs": len(trunk.sets.list_documents(s.slug)),
                    "agents": agents.get(key),
                    "root": trunk.id,
                }
            )
        return rows

    def _root_row(self, trunk: Trunk) -> dict:
        return {
            "id": trunk.id,
            "path": str(trunk.path),
            "name": trunk.name,
            "primary": trunk.primary,
            "sets": self._set_rows(trunk),
        }

    # data directories (trunks) --------------------------------------------

    @route("GET", "/api/roots")
    def list_roots(self):
        self.send_json(200, [self._root_row(t) for t in self.app.trunks()])

    @route("POST", "/api/roots")
    def connect_root(self):
        path = str(self.body().get("path", "")).strip()
        if not path:
            raise HTTPError(400, "a path is required")
        self.send_json(200, self._root_row(self.app.connect_root(path)))

    @route("DELETE", "/api/roots/{rid}")
    def disconnect_root(self, rid: str):
        self.app.disconnect_root(rid)
        self.send_json(200, {"ok": True})

    # sets -----------------------------------------------------------------

    @route("GET", "/api/sets")
    def list_sets(self):
        # No ``?root=`` (and ``root=main``) is the primary directory only.
        self.send_json(200, self._set_rows(self.app.trunk(None)))

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
        from evid.core import feedback

        es = self.app.evidence_set(slug)
        docs = doc_ops.collect_documents(self.app.sets, slug)
        open_fb = feedback.open_counts(feedback.read(es.path))
        self.send_json(
            200, [{**doc_row(d), "fb_open": open_fb.get(d.uuid, 0)} for d in docs]
        )

    # requests to the agent (as treedit's feedback) ------------------------------

    @route("GET", "/api/sets/{slug}/feedback")
    def list_feedback(self, slug: str):
        from evid.core import feedback

        es = self.app.evidence_set(slug)
        items = feedback.read(es.path)
        uuid = self.q.get("uuid")
        self.send_json(200, [x for x in items if not uuid or x["uuid"] == uuid])

    @route("POST", "/api/sets/{slug}/feedback")
    def add_feedback(self, slug: str):
        from evid.core import feedback

        b = self.body()
        es, d = self.app.doc_dir(slug, str(b.get("uuid", "")))
        path = str(b.get("path") or ".")
        if path != ".":
            doc_ops.doc_path(d, path)  # must be a file of the document
        self.app.note(slug, "feedback")
        item = feedback.add(es.path, d.name, str(b.get("text", "")), path)
        logger.info("Request #%d to the agent on %s", item["id"], doc_name(d))
        self.send_json(200, item)

    @route("PUT", "/api/sets/{slug}/feedback/{fid}")
    def update_feedback(self, slug: str, fid: str):
        from evid.core import feedback

        es = self.app.evidence_set(slug)
        b = self.body()
        self.app.note(slug, "feedback")
        try:
            item = feedback.update(
                es.path,
                int(fid),
                text=b.get("text"),
                status=b.get("status"),
                reply=b.get("reply"),
            )
        except KeyError as exc:
            raise HTTPError(404, str(exc).strip("'\"")) from exc
        self.send_json(200, item)

    @route("POST", "/api/sets/{slug}/feedback/{fid}/delete")
    def delete_feedback(self, slug: str, fid: str):
        from evid.core import feedback

        es = self.app.evidence_set(slug)
        self.app.note(slug, "feedback")
        try:
            feedback.delete(es.path, int(fid))
        except KeyError as exc:
            raise HTTPError(404, str(exc).strip("'\"")) from exc
        self.send_json(200, {"ok": True})

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

    @route("GET", "/api/sets/{slug}/stale")
    def set_stale(self, slug: str):
        """Labels and quotes that lost their place after a document was replaced."""
        from evid.services.doc_replace import stale

        rows = stale(self.app.evidence_set(slug).path)
        self.send_json(
            200, {"docs": rows, "count": sum(len(d["records"]) for d in rows)}
        )

    @route("POST", "/api/sets/{slug}/repair")
    def set_repair(self, slug: str):
        """Ask a model where each stale label now points (verbatim matches only), as a job."""
        from evid.services.doc_replace import repair, stale

        es = self.app.evidence_set(slug)

        def run(progress, job):
            done = {"repaired": 0, "stale": 0}
            for d in stale(es.path):
                if job["cancelled"]:
                    break
                progress(f"Re-anchoring {d['title'] or d['uuid'][:8]}")
                r = repair(es.path / "docs" / d["uuid"])
                done["repaired"] += r["repaired"]
                done["stale"] += r["stale"]
            self.app.emit_docs(slug)
            return done

        self.send_json(
            200,
            {
                "job": self.app.jobs.start(
                    "repair", run, f"Re-anchoring stale labels in {slug}"
                )
            },
        )

    @route("POST", "/api/sets/{slug}/delete")
    def delete_docs(self, slug: str):
        uuids = list(self.body().get("uuids") or [])
        for u in uuids:
            _, d = self.app.doc_dir(slug, u)
            name = doc_name(d)
            self.app.note(slug, u)
            doc_ops.delete_doc(d)
            logger.info("Deleted %s from '%s'", name, slug)
        self.app.emit_docs(slug)
        self.send_json(200, {"deleted": len(uuids)})

    @route("POST", "/api/sets/{slug}/copy")
    def copy_docs(self, slug: str):
        b = self.body()
        src_trunk = self.app.trunk(None)
        dest_key = str(b.get("destRoot") or "")
        dest_trunk = self.app.trunk(dest_key) if dest_key else src_trunk
        dest = self.app.evidence_set(str(b.get("dest", "")), root=dest_trunk.id)
        if dest_trunk.id == src_trunk.id and dest.slug == slug:
            raise HTTPError(400, "source and destination are the same set")
        copied = 0
        for u in list(b.get("uuids") or []):
            _, src = self.app.doc_dir(slug, u)
            dest_trunk.disk.touch(dest.slug, u)
            dest_dir, new = doc_ops.copy_doc(src, dest)
            if new:
                copied += 1
                self.app.enqueue_index(dest_dir, dest, root=dest_trunk.id)
        logger.info("Copied %d doc(s) to '%s'", copied, dest.slug)
        self.app.emit_docs(dest.slug, root=dest_trunk.id)
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
            self.app.note(es.slug, u)
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
        self.app.note(slug, uuid)
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
        self.app.note(slug, uuid)
        notes = write_annotation(d, path, str(b.get("text", "")))
        target = "the document" if path in ("", ".") else path
        logger.info(
            "%s note on %s of %s",
            "Set" if str(b.get("text", "")).strip() else "Removed",
            target,
            doc_name(d),
        )
        self.app.emit_docs(slug)
        self.send_json(200, {"annotations": notes})

    @route("GET", "/api/sets/{slug}/docs/{uuid}/history")
    def doc_history(self, slug: str, uuid: str):
        from evid.services.doc_history import doc_history

        _, d = self.app.doc_dir(slug, uuid)
        self.send_json(200, doc_history(d, limit=int(self.q.get("n", "50") or 50)))

    @route("GET", "/api/sets/{slug}/docs/{uuid}/files")
    def doc_files(self, slug: str, uuid: str):
        _, d = self.app.doc_dir(slug, uuid)
        sub = self.q.get("sub", "")
        self.send_json(
            200, {"dir": str(d), "sub": sub, "entries": doc_ops.list_doc_files(d, sub)}
        )

    @route("GET", "/api/sets/{slug}/docs/{uuid}/text")
    def get_text(self, slug: str, uuid: str):
        _, d = self.app.doc_dir(slug, uuid)
        self.send_json(200, text_view(d))

    @route("POST", "/api/sets/{slug}/docs/{uuid}/labels")
    def post_label(self, slug: str, uuid: str):
        from evid.core.labels import add_label, suggest_key, taken_keys

        _, d = self.app.doc_dir(slug, uuid)
        b = self.body()
        self.app.note(slug, uuid)
        span = _span_from_body(d, b)
        key = str(b.get("key") or "").strip()
        if not key:
            key = suggest_key(span["text"], taken_keys(d))
        rec = add_label(d, span, key, str(b.get("note") or ""))
        logger.info("Labelled %s of %s", rec["key"], doc_name(d))
        self.send_json(200, _commit_view(d, f"+{rec['key']}"))

    @route("POST", "/api/sets/{slug}/docs/{uuid}/labels/{key}/notes")
    def post_label_note(self, slug: str, uuid: str, key: str):
        from evid.core.labels import add_note

        _, d = self.app.doc_dir(slug, uuid)
        self.app.note(slug, uuid)
        try:
            add_note(d, key, str(self.body().get("text") or ""))
        except KeyError as exc:
            raise _missing(exc) from exc
        logger.info("Noted %s of %s", key, doc_name(d))
        self.send_json(200, _commit_view(d, f"{key} note"))

    @route("PUT", "/api/sets/{slug}/docs/{uuid}/labels/{key}/notes/{index}")
    def put_label_note(self, slug: str, uuid: str, key: str, index: str):
        from evid.core.labels import edit_note

        _, d = self.app.doc_dir(slug, uuid)
        self.app.note(slug, uuid)
        try:
            edit_note(d, key, _note_index(index), str(self.body().get("text") or ""))
        except KeyError as exc:
            raise _missing(exc) from exc
        logger.info("Edited a note on %s of %s", key, doc_name(d))
        self.send_json(200, _commit_view(d, f"{key} note"))

    @route("DELETE", "/api/sets/{slug}/docs/{uuid}/labels/{key}/notes/{index}")
    def delete_label_note(self, slug: str, uuid: str, key: str, index: str):
        from evid.core.labels import remove_note

        _, d = self.app.doc_dir(slug, uuid)
        self.app.note(slug, uuid)
        try:
            remove_note(d, key, _note_index(index))
        except KeyError as exc:
            raise _missing(exc) from exc
        logger.info("Removed a note on %s of %s", key, doc_name(d))
        self.send_json(200, _commit_view(d, f"{key} note"))

    @route("PUT", "/api/sets/{slug}/docs/{uuid}/labels/{key}")
    def put_label(self, slug: str, uuid: str, key: str):
        from evid.core.labels import rename_label

        _, d = self.app.doc_dir(slug, uuid)
        new = str(self.body().get("key") or "").strip()
        if not new:
            raise HTTPError(400, "missing key")
        self.app.note(slug, uuid)
        try:
            rename_label(d, key, new)
        except KeyError as exc:
            raise _missing(exc) from exc
        logger.info("Renamed label %s to %s of %s", key, new, doc_name(d))
        self.send_json(200, _commit_view(d, f"{key} -> {new}"))

    @route("DELETE", "/api/sets/{slug}/docs/{uuid}/labels/{key}")
    def delete_label(self, slug: str, uuid: str, key: str):
        from evid.core.labels import remove_label

        _, d = self.app.doc_dir(slug, uuid)
        self.app.note(slug, uuid)
        try:
            remove_label(d, key)
        except KeyError as exc:
            raise _missing(exc) from exc
        logger.info("Removed label %s of %s", key, doc_name(d))
        self.send_json(200, _commit_view(d, f"-{key}"))

    @route("POST", "/api/sets/{slug}/docs/{uuid}/annotations-on-text")
    def post_annotation_on_text(self, slug: str, uuid: str):
        from evid.core.labels import add_annotation, span_at, span_of

        _, d = self.app.doc_dir(slug, uuid)
        b = self.body()
        note = str(b.get("note") or b.get("text") or "")
        self.app.note(slug, uuid)
        if "start" in b and "end" in b:
            span = span_at(d, int(b["start"]), int(b["end"]))
        else:
            passage = str(b.get("passage") or "")
            if not passage.strip():
                raise HTTPError(400, "select a passage")
            span, _score, _how = span_of(d, passage)
        rec = add_annotation(d, span, note)
        logger.info("Annotated %s of %s", rec["id"], doc_name(d))
        self.send_json(200, _commit_view(d, f"+annotation {rec['id']}"))

    @route("PUT", "/api/sets/{slug}/docs/{uuid}/annotations-on-text/{ann_id}")
    def put_annotation_on_text(self, slug: str, uuid: str, ann_id: str):
        from evid.core.labels import annotate

        _, d = self.app.doc_dir(slug, uuid)
        self.app.note(slug, uuid)
        try:
            annotate(d, ann_id, str(self.body().get("text") or ""))
        except KeyError as exc:
            raise _missing(exc) from exc
        logger.info("Noted annotation %s of %s", ann_id, doc_name(d))
        self.send_json(200, _commit_view(d, f"annotation {ann_id} note"))

    @route(
        "PUT", "/api/sets/{slug}/docs/{uuid}/annotations-on-text/{ann_id}/notes/{index}"
    )
    def put_annotation_note(self, slug: str, uuid: str, ann_id: str, index: str):
        from evid.core.labels import edit_annotation_note

        _, d = self.app.doc_dir(slug, uuid)
        self.app.note(slug, uuid)
        try:
            edit_annotation_note(
                d, ann_id, _note_index(index), str(self.body().get("text") or "")
            )
        except KeyError as exc:
            raise _missing(exc) from exc
        logger.info("Edited a note on annotation %s of %s", ann_id, doc_name(d))
        self.send_json(200, _commit_view(d, f"annotation {ann_id} note"))

    @route(
        "DELETE",
        "/api/sets/{slug}/docs/{uuid}/annotations-on-text/{ann_id}/notes/{index}",
    )
    def delete_annotation_note(self, slug: str, uuid: str, ann_id: str, index: str):
        from evid.core.labels import remove_annotation_note

        _, d = self.app.doc_dir(slug, uuid)
        self.app.note(slug, uuid)
        try:
            remove_annotation_note(d, ann_id, _note_index(index))
        except KeyError as exc:
            raise _missing(exc) from exc
        logger.info("Removed a note on annotation %s of %s", ann_id, doc_name(d))
        self.send_json(200, _commit_view(d, f"annotation {ann_id} note"))

    @route("DELETE", "/api/sets/{slug}/docs/{uuid}/annotations-on-text/{ann_id}")
    def delete_annotation_on_text(self, slug: str, uuid: str, ann_id: str):
        from evid.core.labels import remove_annotation

        _, d = self.app.doc_dir(slug, uuid)
        self.app.note(slug, uuid)
        try:
            remove_annotation(d, ann_id)
        except KeyError as exc:
            raise _missing(exc) from exc
        logger.info("Removed annotation %s of %s", ann_id, doc_name(d))
        self.send_json(200, _commit_view(d, f"-annotation {ann_id}"))

    @route("POST", "/api/sets/{slug}/docs/{uuid}/document/labels")
    def post_document_label(self, slug: str, uuid: str):
        from evid.core.labels import add_document_label

        _, d = self.app.doc_dir(slug, uuid)
        b = self.body()
        self.app.note(slug, uuid)
        rec = add_document_label(d, str(b.get("key") or ""), str(b.get("note") or ""))
        logger.info("Labelled document %s of %s", rec["key"], doc_name(d))
        self.send_json(200, _commit_view(d, f"+{rec['key']}"))

    @route("POST", "/api/sets/{slug}/docs/{uuid}/document/annotations")
    def post_document_annotation(self, slug: str, uuid: str):
        from evid.core.labels import add_document_annotation

        _, d = self.app.doc_dir(slug, uuid)
        self.app.note(slug, uuid)
        rec = add_document_annotation(d, str(self.body().get("text") or ""))
        logger.info("Annotated document %s of %s", rec["id"], doc_name(d))
        self.send_json(200, _commit_view(d, f"+document {rec['id']}"))

    @route("POST", "/api/sets/{slug}/docs/{uuid}/document/{rec_id}/notes")
    def post_document_note(self, slug: str, uuid: str, rec_id: str):
        from evid.core.labels import add_document_note

        _, d = self.app.doc_dir(slug, uuid)
        self.app.note(slug, uuid)
        try:
            add_document_note(d, rec_id, str(self.body().get("text") or ""))
        except KeyError as exc:
            raise _missing(exc) from exc
        logger.info("Noted document record %s of %s", rec_id, doc_name(d))
        self.send_json(200, _commit_view(d, f"document {rec_id} note"))

    @route("PUT", "/api/sets/{slug}/docs/{uuid}/document/{rec_id}/notes/{index}")
    def put_document_note(self, slug: str, uuid: str, rec_id: str, index: str):
        from evid.core.labels import edit_document_note

        _, d = self.app.doc_dir(slug, uuid)
        self.app.note(slug, uuid)
        try:
            edit_document_note(
                d, rec_id, _note_index(index), str(self.body().get("text") or "")
            )
        except KeyError as exc:
            raise _missing(exc) from exc
        logger.info("Edited a note on document record %s of %s", rec_id, doc_name(d))
        self.send_json(200, _commit_view(d, f"document {rec_id} note"))

    @route("DELETE", "/api/sets/{slug}/docs/{uuid}/document/{rec_id}/notes/{index}")
    def delete_document_note(self, slug: str, uuid: str, rec_id: str, index: str):
        from evid.core.labels import remove_document_note

        _, d = self.app.doc_dir(slug, uuid)
        self.app.note(slug, uuid)
        try:
            remove_document_note(d, rec_id, _note_index(index))
        except KeyError as exc:
            raise _missing(exc) from exc
        logger.info("Removed a note on document record %s of %s", rec_id, doc_name(d))
        self.send_json(200, _commit_view(d, f"document {rec_id} note"))

    @route("PUT", "/api/sets/{slug}/docs/{uuid}/document/{rec_id}")
    def put_document_label(self, slug: str, uuid: str, rec_id: str):
        from evid.core.labels import rename_document_label

        _, d = self.app.doc_dir(slug, uuid)
        new = str(self.body().get("key") or "").strip()
        if not new:
            raise HTTPError(400, "missing key")
        self.app.note(slug, uuid)
        try:
            rename_document_label(d, rec_id, new)
        except KeyError as exc:
            raise _missing(exc) from exc
        logger.info("Renamed document label %s of %s", rec_id, doc_name(d))
        self.send_json(200, _commit_view(d, f"document {rec_id} -> {new}"))

    @route("DELETE", "/api/sets/{slug}/docs/{uuid}/document/{rec_id}")
    def delete_document_record(self, slug: str, uuid: str, rec_id: str):
        from evid.core.labels import remove_document

        _, d = self.app.doc_dir(slug, uuid)
        self.app.note(slug, uuid)
        try:
            remove_document(d, rec_id)
        except KeyError as exc:
            raise _missing(exc) from exc
        logger.info("Removed document record %s of %s", rec_id, doc_name(d))
        self.send_json(200, _commit_view(d, f"-document {rec_id}"))

    @route("POST", "/api/sets/{slug}/docs/{uuid}/quotes/{key}/notes")
    def post_quote_note(self, slug: str, uuid: str, key: str):
        from evid.core.quote_pass import note_quote

        _, d = self.app.doc_dir(slug, uuid)
        b = self.body()
        self.app.note(slug, uuid)
        try:
            note_quote(
                d,
                key,
                str(b.get("text") or ""),
                pass_id=str(b.get("pass") or "") or None,
            )
        except KeyError as exc:
            raise _missing(exc) from exc
        logger.info("Noted machine quote %s of %s", key, doc_name(d))
        self.send_json(200, _commit_view(d, f"{key} note"))

    @route("PUT", "/api/sets/{slug}/docs/{uuid}/quotes/{key}/notes/{index}")
    def put_quote_note(self, slug: str, uuid: str, key: str, index: str):
        from evid.core.quote_pass import edit_quote_note

        _, d = self.app.doc_dir(slug, uuid)
        b = self.body()
        self.app.note(slug, uuid)
        try:
            edit_quote_note(
                d,
                key,
                _note_index(index),
                str(b.get("text") or ""),
                pass_id=str(b.get("pass") or "") or None,
            )
        except KeyError as exc:
            raise _missing(exc) from exc
        logger.info("Edited a note on machine quote %s of %s", key, doc_name(d))
        self.send_json(200, _commit_view(d, f"{key} note"))

    @route("DELETE", "/api/sets/{slug}/docs/{uuid}/quotes/{key}/notes/{index}")
    def delete_quote_note(self, slug: str, uuid: str, key: str, index: str):
        from evid.core.quote_pass import remove_quote_note

        _, d = self.app.doc_dir(slug, uuid)
        self.app.note(slug, uuid)
        try:
            remove_quote_note(
                d,
                key,
                _note_index(index),
                pass_id=self.q.get("pass") or None,
            )
        except KeyError as exc:
            raise _missing(exc) from exc
        logger.info("Removed a note on machine quote %s of %s", key, doc_name(d))
        self.send_json(200, _commit_view(d, f"{key} note"))

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
            app.note(es.slug)  # the new doc's id is not known yet
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
            app.note(es.slug, doc.uuid)
            existing = bool(ing.last_was_existing)
            if not existing:
                if b.get("screenshot"):
                    from evid.services.screenshots import annotate_screenshot

                    annotate_screenshot(doc.path)
                app.enqueue_index(es.path / "docs" / doc.uuid, es)
            app.emit_docs(es.slug)
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

    @route("POST", "/api/ingest/screenshots")
    def ingest_screenshots(self):
        """OCR page images into a temp PDF. The Add document dialog ingests it."""
        import tempfile

        from evid.services.screenshots import resolve_screenshots

        b = self.body()
        pages = b.get("pages")
        if not isinstance(pages, list) or not pages:
            raise HTTPError(400, "add at least one screenshot")
        for page in pages:
            if not isinstance(page, dict) or not (
                str(page.get("path") or "").strip() or page.get("png_base64")
            ):
                raise HTTPError(400, "each page needs a path or an image")
        lang = str(b.get("lang") or "dan+eng").strip() or "dan+eng"
        app = self.app

        class ShotCancelledError(Exception):
            pass

        def run(progress, job):
            work = tempfile.TemporaryDirectory()
            resolved = None
            try:
                sources = _screenshot_sources(pages, Path(work.name))

                def on_page(i: int, n: int, _name: str) -> None:
                    if job["cancelled"]:
                        raise ShotCancelledError
                    progress(f"Reading page {i} of {n}…")

                resolved = resolve_screenshots(sources, lang=lang, progress=on_page)
            except ShotCancelledError:
                return None
            finally:
                work.cleanup()
            if job["cancelled"] or resolved is None:
                if resolved is not None and resolved.temp_dir is not None:
                    with contextlib.suppress(Exception):
                        resolved.temp_dir.cleanup()
                return None
            token = secrets.token_hex(8)
            if resolved.temp_dir is not None:
                app.temps[token] = resolved.temp_dir
            logger.info(
                "Screenshots ready — %d page(s), %s",
                len(pages),
                resolved.original_name,
            )
            title = resolved.title or resolved.pdf_path.stem
            return {
                "path": str(resolved.pdf_path),
                "title": title,
                "authors": "",
                "dates": "",
                "label": title,
                "url": "",
                "source_name": resolved.original_name or "",
                "token": token,
                "screenshot": True,
            }

        self.send_json(
            200,
            {"job": app.jobs.start("screenshots", run, "Reading screenshots")},
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
                    "char_start": r.char_start,
                    "char_end": r.char_start + len(r.chunk_text),
                    "preview": vec_preview(
                        es.path / "docs" / r.doc.uuid / "label" / "text.txt",
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
                    "char_start": h.char_start,
                    "char_end": h.char_end,
                    "score": h.score,
                }
                for h in hits
            ],
        )

    # files / window -------------------------------------------------------

    @route("GET", "/api/files")
    def files(self):
        self.send_json(
            200,
            list_dir(
                self.q.get("dir", ""),
                self.q.get("pdf") == "1",
                self.q.get("images") == "1",
            ),
        )

    @route("POST", "/api/open-path")
    def open_path(self):
        from evid.open_external import open_local_path

        err = open_local_path(str(self.body().get("path", "")))
        if err:
            raise HTTPError(500, err)
        self.send_json(200, {"ok": True})

    @route("POST", "/api/raise")
    def raise_window(self):
        """A second `evid gui`: bring this one forward (or reopen it).

        A body of ``{"set", "doc", "pane"}`` also asks the page to open that
        document (``evid doc label``).
        """
        body = self.body() or {}
        slug = str(body.get("slug") or body.get("set") or "")
        uuid = str(body.get("uuid") or body.get("doc") or "")
        pane = str(body.get("pane") or "")
        if slug or uuid:
            self.app.events.emit("open", slug=slug, uuid=uuid, pane=pane or "label")
        raise_window()
        self.send_json(200, {"ok": True})

    # agent pane --------------------------------------------------------------

    def sessions(self, slug: str, create: bool = True) -> Sessions | None:
        """The terminals of one evidence set (an agent never spans sets)."""
        if self.agents is None:
            raise HTTPError(404, "the agent pane is off")
        trunk = self.app.trunk(None)
        es = self.app.evidence_set(slug)
        root = "" if trunk.primary else trunk.id
        return self.agents.get(es, create=create, data_dir=trunk.path, root=root)

    @route("GET", "/api/terms")
    def list_terms(self):
        terms = self.sessions(
            self.q.get("slug", ""), create=False
        )  # looking attaches nothing
        self.send_json(200, {"terms": terms.list() if terms else []})

    @route("POST", "/api/term/new")
    def new_term(self):
        b = self.body()
        slug = str(b.get("slug", ""))
        terms = self.sessions(slug)
        sid = terms.add(str(b.get("agent") or ""))
        logger.info("Agent pane of '%s': new terminal %s", slug, terms.get(sid).label())
        self.send_json(200, {"id": sid, "terms": terms.list()})

    @route("POST", "/api/term/close")
    def close_term(self):
        b = self.body()
        terms = self.sessions(str(b.get("slug", "")), create=False)
        if terms is None or not terms.close(str(b.get("id", ""))):
            raise HTTPError(404, "no such terminal")
        self.send_json(200, {"terms": terms.list()})

    @route("GET", "/api/term")
    def terminal(self):
        """Upgrade to a WebSocket onto one of a set's terminals (?slug=&id=, default the first)."""
        terms = self.sessions(self.q.get("slug", ""), create=False)
        if terms is None:
            raise HTTPError(404, "no terminals for this set")
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
        win = Handler.window
        # raise() on a headless server records a window. That process exiting,
        # or still being open, must not leave the server running: a windowed
        # launch stops when its window does, and a headless one is blocked in
        # serve_forever until this shutdown.
        if win is not None and win.poll() is None:
            win.terminate()
        threading.Thread(target=self.server.shutdown, daemon=True).start()


class SetAgents:
    """The Agent pane's terminals, kept per evidence set. A set's terminals start in
    the set's folder with EVID_DB / EVID_SET set, so `evid` there works on that set;
    the pane only ever shows the selected set's terminals."""

    def __init__(
        self, data_dir: Path, url: str, agent: str = "", on_change=None
    ) -> None:
        self.data_dir, self.url, self.agent = data_dir, url, agent
        self.on_change = on_change  # (slug) -> None, when a set's terminals change
        self.lock = threading.Lock()
        self.by_slug: dict[str, Sessions] = {}

    def get(
        self,
        evidence_set,
        create: bool = True,
        *,
        data_dir: Path | None = None,
        root: str = "",
    ) -> Sessions | None:
        slug = evidence_set.slug
        # The primary directory stays keyed by slug, so an existing session is found.
        key = slug if not root or root == PRIMARY else f"{root}/{slug}"
        db = self.data_dir if data_dir is None else Path(data_dir)
        with self.lock:
            if key not in self.by_slug and create:
                ping = (lambda k=key: self.on_change(k)) if self.on_change else None
                env = terminal_env(db, self.url, slug)
                self.by_slug[key] = Sessions(str(evidence_set.path), env, None, ping)
            return self.by_slug.get(key)

    def summary(self) -> dict[str, dict]:
        """{slug: {terms, alive, names}} for the sets that have terminals; names are the
        agents in them (claude, codex, …), or the shell (fish, bash) for a plain one."""
        out = {}
        for slug, sess in list(self.by_slug.items()):
            items = sess.list()
            if items:
                names = list(dict.fromkeys(agent_name(t["label"]) for t in items))
                out[slug] = {
                    "terms": len(items),
                    "alive": sum(1 for t in items if t["alive"]),
                    "names": names,
                }
        return out

    def stop(self) -> None:
        for sess in list(self.by_slug.values()):
            sess.stop()


def agent_name(command: str) -> str:
    """'hermes --skills evid' -> 'hermes', '/usr/bin/fish' -> 'fish', 'env X=1 codex' -> 'codex'."""
    words = [
        w
        for w in command.split()
        if "=" not in w and w not in ("env", "exec", "npx", "uvx")
    ]
    return Path(words[0]).name if words else (command.strip() or "shell")


def terminal_env(data_dir: Path, url: str, slug: str = "") -> dict:
    """The environment of the agent pane: `evid` there uses this GUI's data dir (EVID_DB)
    and, for a set's terminal, that set by default (EVID_SET)."""
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
    if slug:
        env["EVID_SET"] = slug
    return env


def raise_window() -> None:
    win = Handler.window
    app_alive = (win is not None and win.poll() is None) or os.environ.get(
        "EVID_IN_APP"
    ) == "1"
    if app_alive and Handler.raise_file is not None:
        Handler.raise_file.write_text(str(time.time()))  # evid-app polls this file
        return
    # A headless server is the page inside workbench. A second `evid gui` asks
    # this process to come forward; opening evid-app here is a loose window.
    if Handler.headless:
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


def ask_raise(url: str, open_at: dict | None = None) -> bool:
    try:
        with urlopen(
            Request(
                url + "api/raise",
                data=json.dumps(open_at or {}).encode(),
                method="POST",
                headers={"X-Evid": "1", "Content-Type": "application/json"},
            ),
            timeout=3,
        ):
            return True
    except (OSError, URLError):
        return False


def lacks_roots(url: str) -> bool:
    """True when this GUI was started before connected directories existed.

    Only a 404 counts. Any other answer, including a failure to connect, leaves
    the running GUI in place.
    """
    try:
        with urlopen(Request(url.rstrip("/") + "/api/roots"), timeout=2) as resp:
            resp.read()
    except UrlHTTPError as exc:
        return exc.code == 404
    except (OSError, URLError):
        return False
    return False


def ask_quit(url: str) -> bool:
    try:
        with urlopen(
            Request(
                url.rstrip("/") + "/api/quit",
                data=b"{}",
                method="POST",
                headers={"X-Evid": "1", "Content-Type": "application/json"},
            ),
            timeout=3,
        ):
            return True
    except (OSError, URLError):
        return False


def _wait_down(data_dir: Path, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if running_instance(data_dir) is None:
            return True
        time.sleep(0.05)
    return running_instance(data_dir) is None


def _open_query(open_at: dict | None) -> str:
    """Query string that opens one document in the GUI (``set``, ``doc``, ``pane``)."""
    if not open_at:
        return ""
    from urllib.parse import urlencode

    fields = {}
    if open_at.get("set") or open_at.get("slug"):
        fields["set"] = open_at.get("set") or open_at.get("slug")
    if open_at.get("doc") or open_at.get("uuid"):
        fields["doc"] = open_at.get("doc") or open_at.get("uuid")
    if open_at.get("pane"):
        fields["pane"] = open_at["pane"]
    return urlencode(fields)


def _server_in_app(url: str) -> bool:
    """True when that GUI is already shown in an evid-app window."""
    try:
        with urlopen(Request(url.rstrip("/") + "/api/config"), timeout=2) as resp:
            return bool(json.loads(resp.read()).get("app"))
    except (OSError, ValueError, URLError):
        return False


def _window_note(data_dir: Path) -> Path:
    return lock_path(data_dir).with_suffix(".window")


def _app_process_alive(pid: int) -> bool:
    cmd = Path(f"/proc/{pid}/cmdline")
    if cmd.exists():
        try:
            return b"evid-app" in cmd.read_bytes().replace(b"\x00", b" ")
        except OSError:
            return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _focus_attached(data_dir: Path) -> bool:
    """Bring forward the evid-app this data directory already opened.

    A headless server (workbench) ignores raise, so the window is remembered
    next to the lock file and brought forward by touching its raise file.
    """
    try:
        info = json.loads(_window_note(data_dir).read_text())
        pid = int(info["pid"])
        raise_path = Path(info["raise"])
    except (OSError, ValueError, KeyError):
        return False
    if not _app_process_alive(pid):
        return False
    raise_path.write_text(str(time.time()))
    return True


def _open_url(url: str, open_at: dict | None) -> str:
    query = _open_query(open_at)
    base = url if url.endswith("/") else url + "/"
    return f"{base}?{query}" if query else base


def _open_attached(config: EvidConfig, url: str, open_at: dict | None) -> None:
    """Show *url* in evid-app and wait until that window closes.

    The server keeps running. Closing this window does not stop it.
    """
    open_url = _open_url(url, open_at)
    exe = find_app()
    if not exe:
        print(
            "  (evid-app not built — `make app-build` or set EVID_APP; using the browser)"
        )
        webbrowser.open(open_url)
        print(f"Opened the browser on the running GUI ({open_url}).")
        return
    raise_path = lock_path(config.data_dir).with_suffix(".app-raise")
    raise_path.write_text(str(time.time()))
    proc = subprocess.Popen([exe, "--url", open_url, "--raise-file", str(raise_path)])
    _window_note(config.data_dir).write_text(
        json.dumps({"pid": proc.pid, "raise": str(raise_path)})
    )
    print(f"Opened evid-app on the running GUI ({open_url}).")
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)


def _claim_running(
    config: EvidConfig,
    open_at: dict | None,
    replace: bool,
    *,
    browser: bool = False,
    headless: bool = False,
) -> bool:
    """True when this process should serve. False when an existing GUI was used.

    ``replace`` quits the GUI already serving this data directory so the caller,
    usually the workbench, keeps the new process as its own child. A GUI from
    before connected directories is replaced either way: it cannot take the
    case directory.

    A windowed launch opens evid-app on a server that has no window of its own
    (workbench's ``evid gui --headless``). The server is left running.
    """
    url = running_instance(config.data_dir)
    if not url:
        return True
    # Do not raise first when this process is taking over. raise() on a
    # headless GUI opens a window and records it, and quit then used to
    # close only that window.
    if replace or lacks_roots(url):
        reason = (
            "this launch takes its place" if replace else "it has no directory list"
        )
        print(f"Restarting the evid GUI at {url}: {reason}.")
        # A connection error from quit still counts when the GUI is gone: the
        # request can lose the race with the process exiting.
        ask_quit(url)
        if _wait_down(config.data_dir):
            return True
        if replace:
            sys.exit(f"evid: the GUI at {url} did not stop")
    if not headless and not browser and not _server_in_app(url):
        if _focus_attached(config.data_dir):
            if not ask_raise(url, open_at):
                return True
            print(f"Raised the running evid GUI ({url}).")
            return False
        _open_attached(config, url, open_at)
        return False
    if not ask_raise(url, open_at):
        return True
    print(f"Raised the running evid GUI ({url}).")
    return False


def serve_gui(
    config: EvidConfig,
    *,
    port: int = 8790,
    browser: bool = False,
    headless: bool = False,
    replace: bool = False,
    agent: str = "",
    open_at: dict | None = None,
) -> None:
    """Serve the GUI on 127.0.0.1 and show it in evid-app (else the browser).

    The agent pane's first terminal runs *agent* (or $EVID_AGENT; empty: a shell)
    in the current directory, with ``EVID_DB`` set to the data dir.

    Closing the window stops a server this process started. A server that is
    already running keeps going; the window only attaches to it. With *headless*
    nothing is opened (the server runs until Ctrl+C or ``/api/quit``).
    """
    config.data_dir = Path(config.data_dir).expanduser().resolve()
    if not _claim_running(config, open_at, replace, browser=browser, headless=headless):
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
    query = _open_query(open_at)
    open_url = f"{url}?{query}" if query else url
    lp = lock_path(config.data_dir)
    lp.write_text(json.dumps({"url": url, "pid": os.getpid()}))
    # evid-app started us (EVID_IN_APP) and watches its own raise file; else we pass ours
    Handler.raise_file = (
        Path(os.environ["EVID_RAISE_FILE"])
        if os.environ.get("EVID_RAISE_FILE")
        else lp.with_suffix(".raise")
    )

    app.attach_log()
    app.start_watches()
    Handler.agent = agent or os.environ.get("EVID_AGENT", "")
    Handler.agents = SetAgents(
        config.data_dir,
        url,
        Handler.agent,
        lambda slug: app.events.emit("agents", slug=slug),
    )

    print(
        f"evid  {config.data_dir}\n  open {open_url}\n  agent {Handler.agent or 'shell'} (Agent pane)"
    )
    exe = None if headless or browser else find_app()
    Handler.headless = headless
    Handler.in_app = bool(exe) or os.environ.get("EVID_IN_APP") == "1"
    try:
        if exe:
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            Handler.window = subprocess.Popen([exe, "--url", open_url, *_raise_args()])
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
            threading.Timer(0.4, webbrowser.open, [open_url]).start()
        with contextlib.suppress(KeyboardInterrupt):
            srv.serve_forever()
    finally:
        Handler.headless = False
        if Handler.agents is not None:
            Handler.agents.stop()
        app.shutdown()
        srv.server_close()
        with contextlib.suppress(OSError):
            if json.loads(lp.read_text()).get("pid") == os.getpid():
                lp.unlink()
        with contextlib.suppress(OSError):
            Handler.raise_file.unlink()
