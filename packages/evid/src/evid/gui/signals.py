"""Centralised Qt signals for evidmgr — avoids circular imports between panels."""

from PySide6.QtCore import QObject, Signal


class AppSignals(QObject):
    """Singleton-like signals hub. Instantiate once and pass to all components."""

    set_selected = Signal(str)  # slug of newly selected set
    doc_ingested = Signal(str, str)  # set_slug, doc_uuid
    doc_indexed = Signal(str, str)  # set_slug, doc_uuid
    anon_yaml_created = Signal(str)  # set_slug
    anon_mode_changed = Signal(str)  # AnonMode value string
    ingestion_error = Signal(str)  # error message
    labels_updated = Signal(str, str)  # set_slug, doc_uuid
    copy_doc_to_set = Signal(str, str, str)  # src_slug, doc_uuid, dest_slug
    doc_navigate = Signal(str)  # doc UUID — switch to Docs tab and select it
