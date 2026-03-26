"""Qt worker threads for evidmgr — keeps the UI responsive during long operations."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

if TYPE_CHECKING:
    from evidmgr.models import EvidenceSet
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
        tags: list[str] | None = None,
        source_type: str = "other",
        source_url: str = "",
    ) -> None:
        super().__init__()
        self._ingester = ingester
        self._pdf_path = pdf_path
        self._evidence_set = evidence_set
        self._label = label
        self._tags = tags or []
        self._source_type = source_type
        self._source_url = source_url

    def run(self) -> None:
        def on_progress(step: int, total: int, msg: str) -> None:
            self.progress.emit(step, total, msg)

        self._ingester.progress = on_progress
        try:
            doc = self._ingester.ingest(
                pdf_path=self._pdf_path,
                evidence_set=self._evidence_set,
                label=self._label,
                tags=self._tags,
                source_type=self._source_type,
                source_url=self._source_url,
            )
            self.finished.emit(doc.uuid)
        except Exception as exc:
            self.error.emit(str(exc))


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
