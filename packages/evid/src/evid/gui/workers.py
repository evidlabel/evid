"""Qt worker threads for evidmgr — keeps the UI responsive during long operations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

if TYPE_CHECKING:
    from evid.models import EvidenceSet
    from evid.services.doc_ingester import DocIngester


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
    ChromaDB-writing subprocess ever touches a given set's vecdb at a moment —
    no file-lock contention. Submit jobs with ``enqueue(doc_dir, evidence_set)``
    from the GUI thread; stop cleanly with ``stop()``.
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
        import tempfile
        from pathlib import Path
        from urllib.parse import urlparse

        _log = logging.getLogger(__name__)

        if self._cancelled:
            self.error.emit("Cancelled")
            return

        try:
            import requests

            from evid.core.typst_generation import (
                _BROWSER_HEADERS,
                web_to_pdf,
            )

            _log.info("Fetching URL: %s", self._url)
            response = requests.get(self._url, timeout=15, headers=_BROWSER_HEADERS)
            if self._cancelled:
                self.error.emit("Cancelled")
                return
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            _log.debug(
                "Content-Type: %s  size: %d bytes", content_type, len(response.content)
            )

            tmp = tempfile.TemporaryDirectory()
            self.temp_dir = tmp
            page_title = ""
            authors = ""

            if "application/pdf" in content_type:
                file_name = Path(self._url.split("/")[-1] or "document").stem + ".pdf"
                pdf_path = Path(tmp.name) / file_name
                pdf_path.write_bytes(response.content)
                authors = urlparse(self._url).netloc
                _log.info("Saved PDF from URL: %s", file_name)
            else:
                _log.info("HTML page detected — converting to PDF via Typst")
                try:
                    from bs4 import BeautifulSoup

                    soup = BeautifulSoup(response.text, "html.parser")
                    meta_author = soup.find("meta", attrs={"name": "author"})
                    authors = (
                        meta_author.get("content", "") if meta_author else ""
                    ) or urlparse(self._url).netloc
                except Exception:
                    authors = urlparse(self._url).netloc

                pdf_path, page_title = web_to_pdf(
                    self._url, Path(tmp.name), html=response.text
                )
                _log.info("web_to_pdf produced: %s (title=%r)", pdf_path, page_title)

            _log.info("URL fetch complete — opening metadata dialog")
            self.ready.emit(str(pdf_path), page_title or "", authors, self._url)
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
    """Copy a document directory to another evidence set and re-index into its vecdb."""

    progress = Signal(int, int, str)
    finished = Signal(str, str)  # doc_uuid, dest_slug
    error = Signal(str)

    def __init__(
        self,
        src_doc_dir: Path,
        dest_set: EvidenceSet,
        vec_service=None,
    ) -> None:
        super().__init__()
        self._src_doc_dir = src_doc_dir
        self._dest_set = dest_set
        self._vec_service = vec_service

    def run(self) -> None:
        import logging
        import shutil

        import yaml

        _log = logging.getLogger(__name__)
        doc_uuid = self._src_doc_dir.name
        dest_doc_dir = self._dest_set.path / "docs" / doc_uuid
        try:
            self.progress.emit(
                1, 3, f"Copying {doc_uuid[:8]}… to '{self._dest_set.name}'"
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

            self.progress.emit(2, 3, "Updating metadata…")
            meta = {"notes": "", "indexed": False}
            from evid.core.evid_meta import write_meta

            write_meta(dest_doc_dir, meta)

            self.progress.emit(3, 3, "Indexing into vector store…")
            if self._vec_service is not None:
                try:
                    from datetime import UTC, datetime

                    from evid.models import Document

                    info: dict = {}
                    info_path = dest_doc_dir / "info.yml"
                    if info_path.exists():
                        with info_path.open(encoding="utf-8") as fh:
                            info = yaml.safe_load(fh) or {}
                    tags_raw = info.get("tags", "")
                    tags = (
                        [t.strip() for t in tags_raw.split(",") if t.strip()]
                        if isinstance(tags_raw, str)
                        else [str(t).strip() for t in tags_raw if str(t).strip()]
                    )
                    doc = Document(
                        uuid=doc_uuid,
                        path=dest_doc_dir,
                        label=info.get("label", doc_uuid),
                        tags=tags,
                        added=datetime.now(tz=UTC),
                        indexed=False,
                    )
                    typ_path = dest_doc_dir / "label.typ"
                    typ_text = (
                        typ_path.read_text(encoding="utf-8")
                        if typ_path.exists()
                        else ""
                    )
                    ok, msg = self._vec_service.index_document_isolated(
                        doc, typ_text, self._dest_set
                    )
                    if ok:
                        meta["indexed"] = True
                        from evid.core.evid_meta import write_meta

                        write_meta(dest_doc_dir, meta)
                        _log.info(
                            "Re-indexed %s into '%s'", doc_uuid, self._dest_set.slug
                        )
                    else:
                        _log.warning(
                            "Vec re-index for %s in '%s' skipped: %s",
                            doc_uuid,
                            self._dest_set.slug,
                            msg,
                        )
                except Exception:
                    _log.exception(
                        "Vec re-index failed for %s in '%s'",
                        doc_uuid,
                        self._dest_set.slug,
                    )

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
    """Run full-text (fuzzy/regex) body search in a background thread."""

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
