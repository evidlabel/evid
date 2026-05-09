"""LabelController — single owner of the label-editing workflow.

Both DocsTab and SearchTab delegate all labelling to this object so the
logic lives in exactly one place.

Workflow
--------
1. ``label_doc(doc_dir, uuid)`` is called by the tab.
2. If a ``label.typ`` already exists it is opened in the configured editor
   and watched for file-system changes.
3. If no ``.typ`` exists the source PDF/txt is located and
   ``TypGenWorker`` generates it; on completion the file is opened and
   watched.
4. Every time the watched file is saved, ``LabelWorker`` runs
   ``generate_bib_from_typ`` in a background thread.
5. ``label_updated(uuid)`` is emitted on success; ``label_error(msg)``
   on failure.  Tabs connect to these signals to do tab-specific
   post-processing (refresh tables, show status bar, etc.).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QProgressDialog, QWidget

logger = logging.getLogger(__name__)


class LabelController(QObject):
    """Manages the full label-editing lifecycle for a single evidence set."""

    label_updated = Signal(str)  # doc_uuid — bib regenerated successfully
    label_error = Signal(str)  # human-readable error message

    def __init__(
        self, get_editor: Callable[[], str], parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._get_editor = get_editor
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._watched: dict[str, str] = {}  # typ_path_str → uuid
        self._workers: list = []
        self._typgen_dlg: QProgressDialog | None = None
        self._typgen_uuid: str = ""
        self._typgen_typ: Path | None = None

    # ── public API ────────────────────────────────────────────────────────

    def label_doc(self, doc_dir: Path, uuid: str) -> None:
        """Open the label file for *uuid*, generating it first if needed."""
        typ_path = doc_dir / "label.typ"
        if not typ_path.exists():
            existing = list(doc_dir.glob("*.typ"))
            typ_path = existing[0] if existing else doc_dir / "label.typ"

        if typ_path.exists():
            self._open_and_watch(uuid, typ_path)
            return

        source = self._find_source(doc_dir)
        if source is None:
            self.label_error.emit("No PDF or text file found to generate labels from.")
            return

        self._start_typgen(uuid, source, typ_path)

    # ── internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _find_source(doc_dir: Path) -> Path | None:
        for name in ("original.pdf",):
            p = doc_dir / name
            if p.exists():
                return p
        for pattern in ("*.pdf", "*.txt"):
            candidates = list(doc_dir.glob(pattern))
            if candidates:
                return candidates[0]
        return None

    def _open_and_watch(self, uuid: str, typ_path: Path) -> None:
        typ_str = str(typ_path)
        self._open_file(typ_str)
        if typ_str not in self._watcher.files():
            self._watcher.addPath(typ_str)
        self._watched[typ_str] = uuid

    def _open_file(self, path_str: str) -> None:
        editor = self._get_editor()
        if shutil.which(editor):
            try:
                subprocess.Popen([editor, path_str])
            except Exception as exc:
                logger.warning("Could not open editor %r: %s", editor, exc)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path_str))

    def _start_typgen(self, uuid: str, source: Path, typ_path: Path) -> None:
        from evid.gui.workers import TypGenWorker

        parent_widget = self.parent() if isinstance(self.parent(), QWidget) else None
        dlg = QProgressDialog("Generating label.typ…", None, 0, 0, parent_widget)
        dlg.setWindowTitle("Generating")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.show()
        self._typgen_dlg = dlg
        self._typgen_uuid = uuid
        self._typgen_typ = typ_path

        worker = TypGenWorker(source, typ_path)
        worker.finished.connect(self._on_typgen_done)
        worker.error.connect(self._on_typgen_error)
        self._workers.append(worker)
        worker.start()

    # ── slots ─────────────────────────────────────────────────────────────

    def _on_typgen_done(self, typ_path_str: str) -> None:
        try:
            if self._typgen_dlg:
                self._typgen_dlg.close()
                self._typgen_dlg = None
            self._open_and_watch(self._typgen_uuid, Path(typ_path_str))
        except Exception:
            logger.exception("Error after typ generation")

    def _on_typgen_error(self, msg: str) -> None:
        try:
            if self._typgen_dlg:
                self._typgen_dlg.close()
                self._typgen_dlg = None
            self.label_error.emit(msg)
        except Exception:
            logger.exception("Error handling typ generation failure: %s", msg)

    def _on_file_changed(self, path: str) -> None:
        typ_path = Path(path)
        if not typ_path.exists():
            return
        # Re-add: write+rename editors change the inode so the watcher drops it.
        self._watcher.addPath(path)
        uuid = self._watched.get(path)
        if not uuid:
            return

        from evid.gui.workers import LabelWorker

        worker = LabelWorker(typ_path, uuid)
        worker.finished.connect(self.label_updated)
        worker.error.connect(self.label_error)
        self._workers.append(worker)
        worker.start()
