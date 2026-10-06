"""Background work for the GUI server: an event log, jobs, the index queue and
the label.typ watcher.

The page polls ``/api/events?since=N``; everything that happens off the request
thread (job progress, indexing, label rebuilds, log lines) lands in
:class:`Events`. Every exception is logged and turned into an error event, never
swallowed.
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from evid.models import EvidenceSet

logger = logging.getLogger(__name__)


class Events:
    """Ring buffer of numbered events, read by the page with ``since``."""

    def __init__(self, maxlen: int = 2000) -> None:
        self._lock = threading.Lock()
        self._buf: deque[dict] = deque(maxlen=maxlen)
        self._seq = 0

    def emit(self, kind: str, **data: Any) -> int:
        with self._lock:
            self._seq += 1
            self._buf.append({**data, "id": self._seq, "kind": kind, "t": time.time()})
            return self._seq

    def since(self, n: int) -> tuple[int, list[dict]]:
        with self._lock:
            return self._seq, [e for e in self._buf if e["id"] > n]

    @property
    def last(self) -> int:
        with self._lock:
            return self._seq


class EventLogHandler(logging.Handler):
    """Feed log records into the page's log pane (kind ``log``)."""

    def __init__(self, events: Events, level: int = logging.INFO) -> None:
        super().__init__(level)
        self._events = events
        self.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._events.emit("log", level=record.levelname, msg=self.format(record))
        except Exception:
            self.handleError(record)


class Jobs:
    """One thread per job; progress, result and errors go to :class:`Events`."""

    def __init__(self, events: Events) -> None:
        self._events = events
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self._jobs: dict[int, dict] = {}

    def start(
        self,
        kind: str,
        fn: Callable[[Callable[[str], None], dict], Any],
        label: str = "",
    ) -> int:
        """Run ``fn(progress, job)`` in a thread. ``job["cancelled"]`` is set by
        :meth:`cancel`; *fn* checks it. Returns the job id."""
        jid = next(self._ids)
        job = {
            "id": jid,
            "kind": kind,
            "label": label,
            "state": "running",
            "cancelled": False,
        }
        with self._lock:
            self._jobs[jid] = job

        def progress(msg: str) -> None:
            logger.info("%s", msg)
            self._events.emit("job", job_id=jid, job=kind, state="running", msg=msg)

        def run() -> None:
            try:
                result = fn(progress, job)
            except Exception as exc:
                logger.exception("%s failed", label or kind)
                job["state"] = "error"
                self._events.emit(
                    "job",
                    job_id=jid,
                    job=kind,
                    state="error",
                    error=str(exc) or type(exc).__name__,
                )
                return
            job["state"] = "cancelled" if job["cancelled"] else "done"
            if job["cancelled"]:
                logger.info("%s: cancelled", label or kind)
            self._events.emit(
                "job", job_id=jid, job=kind, state=job["state"], result=result
            )

        if label:
            logger.info("%s", label)
        self._events.emit("job", job_id=jid, job=kind, state="running", msg=label)
        threading.Thread(target=run, name=f"evid-{kind}-{jid}", daemon=True).start()
        return jid

    def cancel(self, jid: int) -> bool:
        with self._lock:
            job = self._jobs.get(jid)
        if job is None:
            return False
        job["cancelled"] = True
        return True


class IndexQueue:
    """Serialized background vecdb indexing: one thread, one doc at a time.

    Only one niced ChromaDB-writing subprocess touches a set's vecdb at a moment.
    The ``IndexWorkerPool`` child (warm embedding model) lives while the queue
    has work and is closed when it drains, so the vecdb lock is not held idle.
    """

    def __init__(
        self,
        events: Events,
        before_index: Callable[[str], None] | None = None,
        on_write: Callable[[str, str], None] | None = None,
    ) -> None:
        self._events = events
        self._before_index = before_index
        self._on_write = on_write  # (slug, uuid): indexing rewrites evid_meta — that is the app, not an agent
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._pending = 0
        self._thread: threading.Thread | None = None

    @property
    def pending(self) -> int:
        with self._lock:
            return self._pending

    def enqueue(self, doc_dir: Path, evidence_set: EvidenceSet) -> None:
        with self._lock:
            self._pending += 1
            pending = self._pending
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="evid-index", daemon=True
                )
                self._thread.start()
        if self._before_index:
            self._before_index(evidence_set.slug)
        self._queue.put((doc_dir, evidence_set))
        self._events.emit("index_queue", pending=pending)

    def stop(self, timeout: float = 5.0) -> None:
        if self._thread is None:
            return
        self._queue.put(None)
        self._thread.join(timeout)

    def _make_ingester(self):
        from evid import extras
        from evid.services.doc_ingester import DocIngester
        from evid.services.vec_service import VecService

        vec = VecService() if extras.has_vec() else None
        return DocIngester(vec_service=vec), vec is not None

    def _make_pool(self):
        from evid.vec.safe_index import IndexWorkerPool

        return IndexWorkerPool()

    def _run(self) -> None:
        ingester, has_vec = self._make_ingester()
        pool = None
        try:
            while True:
                job = self._queue.get()
                if job is None:
                    break
                doc_dir, evidence_set = job
                ok = False
                if self._on_write:
                    self._on_write(evidence_set.slug, doc_dir.name)
                try:
                    if has_vec and pool is None:
                        pool = self._make_pool()
                    logger.info(
                        "Background indexing %s into '%s'",
                        doc_dir.name,
                        evidence_set.slug,
                    )
                    if pool is not None:
                        ok = bool(
                            ingester.index_existing(doc_dir, evidence_set, pool=pool)
                        )
                    else:
                        ok = bool(ingester.index_existing(doc_dir, evidence_set))
                except Exception:
                    logger.exception("Background index failed for %s", doc_dir.name)
                if not ok:
                    logger.warning(
                        "Background index did not complete for %s", doc_dir.name
                    )
                if self._on_write:
                    self._on_write(evidence_set.slug, doc_dir.name)
                with self._lock:
                    self._pending = max(0, self._pending - 1)
                    pending = self._pending
                self._events.emit(
                    "indexed",
                    slug=evidence_set.slug,
                    uuid=doc_dir.name,
                    ok=ok,
                    pending=pending,
                )
                if pending == 0:
                    if pool is not None:
                        pool.close()
                        pool = None
                    self._events.emit("index_idle")
        finally:
            if pool is not None:
                pool.close()


class LabelWatcher:
    """Poll watched ``.typ`` files; on a change rebuild label.json / label.bib.

    Replaces ``QFileSystemWatcher``. Polling the mtime survives editors that save
    by write+rename (a new inode), which inotify-style watchers lose.
    """

    def __init__(self, events: Events, interval: float = 1.0) -> None:
        self._events = events
        self._interval = interval
        self._lock = threading.Lock()
        self._watched: dict[Path, dict] = {}  # typ path -> {slug, uuid, mtime}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def watch(self, typ_path: Path, slug: str, uuid: str) -> None:
        with self._lock:
            self._watched[typ_path] = {
                "slug": slug,
                "uuid": uuid,
                "mtime": _mtime(typ_path),
            }
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="evid-label-watch", daemon=True
                )
                self._thread.start()

    def mark_seen(self, typ_path: Path) -> None:
        """Record the current mtime (after a save the server already rebuilt)."""
        with self._lock:
            if typ_path in self._watched:
                self._watched[typ_path]["mtime"] = _mtime(typ_path)

    def stop(self) -> None:
        self._stop.set()

    def poll(self) -> None:
        """Check every watched file once (the thread calls this; tests too)."""
        with self._lock:
            items = list(self._watched.items())
        for path, w in items:
            m = _mtime(path)
            if m is None or m == w["mtime"]:
                continue
            with self._lock:
                w["mtime"] = m
            rebuild_labels(self._events, path, w["slug"], w["uuid"])

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.poll()
            except Exception:
                logger.exception("Label watcher failed")


def rebuild_labels(
    events: Events, typ_path: Path, slug: str, uuid: str
) -> tuple[bool, str]:
    """Run ``generate_bib_from_typ`` and report the outcome as an event."""
    from evid.core.bibtex import generate_bib_from_typ

    try:
        ok, msg = generate_bib_from_typ(typ_path)
    except Exception as exc:
        logger.exception("Label rebuild failed for %s", typ_path)
        ok, msg = False, str(exc)
    if ok:
        logger.info("Labels updated for %s", uuid[:8])
        events.emit("labels_updated", slug=slug, uuid=uuid)
    else:
        logger.warning("Label rebuild failed for %s: %s", uuid[:8], msg)
        events.emit(
            "label_error", slug=slug, uuid=uuid, error=msg or "typst query failed"
        )
    return ok, msg or ""


def _mtime(p: Path) -> float | None:
    try:
        return p.stat().st_mtime_ns / 1e9
    except OSError:
        return None
