"""Centralised Qt signals for evidmgr — avoids circular imports between panels."""

from PySide6.QtCore import QObject, Signal


class AppSignals(QObject):
    """Per-window signals hub. Instantiate once per window and pass to that window's widgets."""

    set_selected = Signal(str)  # slug of newly selected set
    doc_ingested = Signal(str, str)  # set_slug, doc_uuid
    doc_indexed = Signal(str, str)  # set_slug, doc_uuid
    ingestion_error = Signal(str)  # error message
    labels_updated = Signal(str, str)  # set_slug, doc_uuid
    copy_doc_to_set = Signal(str, str, str)  # src_slug, doc_uuid, dest_slug
    doc_navigate = Signal(str)  # doc UUID — switch to Docs tab and select it
