"""Qt worker threads for evidmgr — keeps the UI responsive during long operations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

if TYPE_CHECKING:
    from evidmgr.models import Document, EvidenceSet
    from evidmgr.services.doc_ingester import DocIngester


class IngestWorker(QThread):
    """Runs DocIngester.ingest() in a background thread."""

    progress = Signal(int, int, str)   # step, total, message
    finished = Signal(str)             # doc_uuid
    error = Signal(str)                # error message

    def __init__(
        self,
        ingester: "DocIngester",
        pdf_path: Path,
        evidence_set: "EvidenceSet",
        label: str = "",
        title: str = "",
        authors: str = "",
        dates: str = "",
        tags: list[str] | None = None,
        source_url: str = "",
        temp_dir: object = None,
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
            )
            self.finished.emit(doc.uuid)
        except Exception as exc:
            self.error.emit(str(exc))


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
        self.temp_dir: object = None  # tempfile.TemporaryDirectory, kept alive by caller

    def run(self) -> None:
        import logging  # noqa: PLC0415
        import tempfile  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415
        from urllib.parse import urlparse  # noqa: PLC0415

        _log = logging.getLogger(__name__)

        try:
            import requests  # noqa: PLC0415
            from evid.core.typst_generation import _BROWSER_HEADERS, web_to_pdf  # noqa: PLC0415

            _log.info("Fetching URL: %s", self._url)
            response = requests.get(self._url, timeout=15, headers=_BROWSER_HEADERS)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            _log.debug("Content-Type: %s  size: %d bytes", content_type, len(response.content))

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
                    from bs4 import BeautifulSoup  # noqa: PLC0415
                    soup = BeautifulSoup(response.text, "html.parser")
                    meta_author = soup.find("meta", attrs={"name": "author"})
                    authors = (
                        (meta_author.get("content", "") if meta_author else "")
                        or urlparse(self._url).netloc
                    )
                except Exception:
                    authors = urlparse(self._url).netloc

                pdf_path, page_title = web_to_pdf(self._url, Path(tmp.name), html=response.text)
                _log.info("web_to_pdf produced: %s (title=%r)", pdf_path, page_title)

            _log.info("URL fetch complete — opening metadata dialog")
            self.ready.emit(str(pdf_path), page_title or "", authors, self._url)
        except Exception as exc:
            self.error.emit(str(exc))


class IndexWorker(QThread):
    """Index a list of already-imported documents into the vector store."""

    progress = Signal(int, int, str)  # done, total, message
    finished = Signal()
    error = Signal(str)

    def __init__(
        self,
        ingester: "DocIngester",
        docs: "list[Document]",
        evidence_set: "EvidenceSet",
    ) -> None:
        super().__init__()
        self._ingester = ingester
        self._docs = docs
        self._evidence_set = evidence_set

    def run(self) -> None:
        import logging  # noqa: PLC0415
        _log = logging.getLogger(__name__)
        total = len(self._docs)
        _log.info("IndexWorker: %d document(s) to index", total)
        for done, doc in enumerate(self._docs, 1):
            self.progress.emit(done, total, f"Indexing {doc.label[:60]}…")
            _log.debug("[%d/%d] Indexing %s (%s)", done, total, doc.label, doc.uuid)
            try:
                self._ingester.index_existing(doc.path, self._evidence_set)
            except Exception as exc:
                self.error.emit(f"{doc.uuid}: {exc}")
                return
        _log.info("IndexWorker: finished indexing %d document(s)", total)
        self.finished.emit()


class AnonExtractWorker(QThread):
    """Runs AnonService.run_extract() in a background thread."""

    finished = Signal(str)  # yaml_path as str
    error = Signal(str)

    def __init__(self, anon_service, evidence_set, doc_uuids, language=None):
        super().__init__()
        self._svc = anon_service
        self._evidence_set = evidence_set
        self._doc_uuids = doc_uuids
        self._language = language

    def run(self) -> None:
        try:
            path = self._svc.run_extract(self._evidence_set, self._doc_uuids, self._language)
            self.finished.emit(str(path))
        except Exception as exc:
            self.error.emit(str(exc))
