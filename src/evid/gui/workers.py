"""Qt worker threads for evidmgr — keeps the UI responsive during long operations."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

if TYPE_CHECKING:
    from evid.models import EvidenceSet
    from evid.services.doc_ingester import DocIngester


def track_worker(workers: list, worker: QThread, *done_signals) -> QThread:
    """Keep *worker* alive until it emits one of *done_signals*, then drop it."""
    workers.append(worker)

    def _drop(*_args) -> None:
        try:
            workers.remove(worker)
        except ValueError:
            return
        worker.deleteLater()

    for sig in done_signals:
        sig.connect(_drop)
    return worker


class IngestWorker(QThread):
    """Runs DocIngester.ingest() in a background thread."""

    progress = Signal(int, int, str)  # step, total, message
    finished = Signal(str)  # doc_uuid
    error = Signal(str)  # error message

    def __init__(
        self,
        ingester: DocIngester,
        pdf_path: Path,
        evidence_set: EvidenceSet,
        label: str = "",
        title: str = "",
        authors: str = "",
        dates: str = "",
        tags: list[str] | None = None,
        source_url: str = "",
        temp_dir: object = None,
        do_index: bool = True,
    ) -> None:
        super().__init__()
        self._ingester = ingester
        self._pdf_path = pdf_path
        self._evidence_set = evidence_set
        self._label = label
        self._title = title
        self._authors = authors
        self._dates = dates
        self._tags = tags or []
        self._source_url = source_url
        self._temp_dir = temp_dir
        self._do_index = do_index

    def run(self) -> None:
        def on_progress(step: int, total: int, msg: str) -> None:
            self.progress.emit(step, total, msg)

        self._ingester.progress = on_progress
        try:
            doc = self._ingester.ingest(
                pdf_path=self._pdf_path,
                evidence_set=self._evidence_set,
                label=self._label,
                title=self._title,
                authors=self._authors,
                dates=self._dates,
                tags=self._tags,
                source_url=self._source_url,
                temp_dir=self._temp_dir,
                do_index=self._do_index,
            )
            self.finished.emit(doc.uuid)
        except Exception as exc:
            self.error.emit(str(exc))


class IndexQueueWorker(QThread):
    """Serialized background vecdb indexing queue.

    A single long-lived thread that indexes documents one at a time, so only one
    niced ChromaDB-writing subprocess ever touches a given set's vecdb at a
    moment — no file-lock contention, no laptop freeze. Submit jobs with
    ``enqueue(doc_dir, evidence_set)`` from the GUI thread; stop cleanly with
    ``stop()``.
    """

    item_done = Signal(str, str, bool)  # set_slug, doc_uuid, ok
    queue_changed = Signal(int)  # jobs still pending (incl. the in-flight one)
    idle = Signal()  # emitted when the queue drains

    def __init__(self) -> None:
        super().__init__()
        import queue as _queue
        import threading

        self._queue: _queue.Queue = _queue.Queue()
        self._lock = threading.Lock()
        self._pending = 0

    def enqueue(self, doc_dir: Path, evidence_set: EvidenceSet) -> None:
        with self._lock:
            self._pending += 1
            pending = self._pending
        self._queue.put((doc_dir, evidence_set))
        self.queue_changed.emit(pending)

    def stop(self) -> None:
        """Ask the worker to exit after finishing any in-flight job."""
        self._queue.put(None)

    def run(self) -> None:
        import logging

        from evid.services.doc_ingester import DocIngester
        from evid.services.vec_service import VecService

        _log = logging.getLogger(__name__)
        ingester = DocIngester(vec_service=VecService())
        while True:
            job = self._queue.get()
            if job is None:
                break
            doc_dir, evidence_set = job
            doc_uuid = doc_dir.name
            ok = False
            try:
                _log.info(
                    "Background indexing %s into '%s'", doc_uuid, evidence_set.slug
                )
                ok = bool(ingester.index_existing(doc_dir, evidence_set))
            except Exception as exc:
                _log.exception("Background index failed for %s: %s", doc_uuid, exc)
            with self._lock:
                self._pending = max(0, self._pending - 1)
                pending = self._pending
            self.item_done.emit(evidence_set.slug, doc_uuid, ok)
            self.queue_changed.emit(pending)
            if pending == 0:
                self.idle.emit()


class UrlFetchWorker(QThread):
    """Download a URL and convert to PDF in a background thread.

    Emits ``ready`` with the local PDF path, page title, authors, and original
    URL so the caller can open an ``AddDocDialog`` pre-filled.
    Emits ``error`` on failure.
    """

    ready = Signal(str, str, str, str)  # pdf_path, page_title, authors, url
    error = Signal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url
        self._cancelled = False
        self.temp_dir: object = (
            None  # tempfile.TemporaryDirectory, kept alive by caller
        )

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        import logging

        _log = logging.getLogger(__name__)

        if self._cancelled:
            self.error.emit("Cancelled")
            return

        try:
            from evid.services.doc_ingester import resolve_source

            _log.info("Fetching URL: %s", self._url)
            resolved = resolve_source(self._url)
            if self._cancelled:
                if resolved.temp_dir is not None:
                    with contextlib.suppress(Exception):
                        resolved.temp_dir.cleanup()
                self.error.emit("Cancelled")
                return

            self.temp_dir = resolved.temp_dir
            _log.info(
                "URL fetch complete — %s (title=%r)",
                resolved.pdf_path.name,
                resolved.title,
            )
            self.ready.emit(
                str(resolved.pdf_path),
                resolved.title or "",
                resolved.authors,
                resolved.source_url or self._url,
            )
        except Exception as exc:
            self.error.emit(str(exc))


class LabelWorker(QThread):
    """Runs generate_bib_from_typ() in a background thread."""

    finished = Signal(str)  # doc_uuid
    error = Signal(str)  # error message

    def __init__(self, typ_path: Path, doc_uuid: str) -> None:
        super().__init__()
        self._typ_path = typ_path
        self._doc_uuid = doc_uuid

    def run(self) -> None:
        try:
            from evid.core.bibtex import generate_bib_from_typ

            ok, msg = generate_bib_from_typ(self._typ_path)
            if ok:
                self.finished.emit(self._doc_uuid)
            else:
                self.error.emit(msg or "typst query failed")
        except Exception as exc:
            self.error.emit(str(exc))


class TypGenWorker(QThread):
    """Generates a .typ file from a PDF or text source in a background thread."""

    finished = Signal(str)  # typ_path as str
    error = Signal(str)  # error message

    def __init__(self, source_path: Path, typ_path: Path) -> None:
        super().__init__()
        self._source_path = source_path
        self._typ_path = typ_path

    def run(self) -> None:
        try:
            from evid.core.typst_generation import (
                text_to_typst,
                textpdf_to_typst,
            )

            if self._source_path.suffix.lower() == ".pdf":
                textpdf_to_typst(self._source_path, self._typ_path)
            else:
                text_to_typst(self._source_path, self._typ_path)
            self.finished.emit(str(self._typ_path))
        except Exception as exc:
            self.error.emit(str(exc))


class CopyDocWorker(QThread):
    """Copy a document directory to another evidence set.

    Vector indexing is the background queue's job — this worker only copies
    files and leaves ``indexed: false`` so the GUI is not blocked.
    """

    progress = Signal(int, int, str)
    finished = Signal(str, str)  # doc_uuid, dest_slug
    error = Signal(str)

    def __init__(self, src_doc_dir: Path, dest_set: EvidenceSet) -> None:
        super().__init__()
        self._src_doc_dir = src_doc_dir
        self._dest_set = dest_set

    def run(self) -> None:
        import logging
        import shutil

        _log = logging.getLogger(__name__)
        doc_uuid = self._src_doc_dir.name
        dest_doc_dir = self._dest_set.path / "docs" / doc_uuid
        try:
            self.progress.emit(
                1, 2, f"Copying {doc_uuid[:8]}… to '{self._dest_set.name}'"
            )
            if dest_doc_dir.exists():
                _log.info(
                    "Doc %s already present in '%s' — skipping copy",
                    doc_uuid,
                    self._dest_set.slug,
                )
                self.finished.emit(doc_uuid, self._dest_set.slug)
                return
            shutil.copytree(str(self._src_doc_dir), str(dest_doc_dir))
            _log.debug("Copied %s → %s", self._src_doc_dir, dest_doc_dir)

            self.progress.emit(2, 2, "Updating metadata…")
            meta = {"notes": "", "indexed": False}
            from evid.core.evid_meta import write_meta

            write_meta(dest_doc_dir, meta)

            self.finished.emit(doc_uuid, self._dest_set.slug)
        except Exception as exc:
            _log.exception("CopyDocWorker failed for %s", doc_uuid)
            self.error.emit(str(exc))


class MetaSearchWorker(QThread):
    """Run meta (regex) search over info.yml in a background thread."""

    finished = Signal(list)  # list[Document]
    error = Signal(str)

    def __init__(self, evidence_set: EvidenceSet, pattern: str) -> None:
        super().__init__()
        self._evidence_set = evidence_set
        self._pattern = pattern

    def run(self) -> None:
        try:
            from evid.core.doc_loader import search_meta_documents

            docs = search_meta_documents(self._evidence_set.path, self._pattern)
            self.finished.emit(docs)
        except Exception as exc:
            self.error.emit(str(exc))


class VectorSearchWorker(QThread):
    """Run vector similarity search in a background thread."""

    finished = Signal(list)  # list[VecResult]
    error = Signal(str)

    def __init__(
        self, vec_service, evidence_set: EvidenceSet, query: str, n_results: int
    ):
        super().__init__()
        self._vec_service = vec_service
        self._evidence_set = evidence_set
        self._query = query
        self._n_results = n_results

    def run(self) -> None:
        try:
            results = self._vec_service.query(
                self._evidence_set, self._query, n_results=self._n_results
            )
            self.finished.emit(results)
        except Exception as exc:
            self.error.emit(str(exc))


class FullTextSearchWorker(QThread):
    """Run full-text (substring/regex) body search in a background thread."""

    finished = Signal(list)  # list[TextHit]
    error = Signal(str)

    def __init__(
        self,
        evidence_set: EvidenceSet,
        query: str,
        regex: bool,
        n_results: int,
    ):
        super().__init__()
        self._evidence_set = evidence_set
        self._query = query
        self._regex = regex
        self._n_results = n_results

    def run(self) -> None:
        try:
            from evid.core.fulltext import search_fulltext

            hits = search_fulltext(
                self._evidence_set.path,
                self._query,
                regex=self._regex,
                n=self._n_results,
            )
            self.finished.emit(hits)
        except Exception as exc:
            self.error.emit(str(exc))
