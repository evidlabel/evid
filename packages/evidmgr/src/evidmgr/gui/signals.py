"""Centralised Qt signals for evidmgr — avoids circular imports between panels."""

from PySide6.QtCore import QObject, Signal


class AppSignals(QObject):
    """Singleton-like signals hub. Instantiate once and pass to all components."""

    set_selected = Signal(str)          # slug of newly selected set
    doc_ingested = Signal(str, str)     # set_slug, doc_uuid
    doc_indexed = Signal(str, str)      # set_slug, doc_uuid
    anon_yaml_created = Signal(str)     # set_slug
    add_to_prompt = Signal(str, str)    # set_slug, doc_uuid
    anon_mode_changed = Signal(str)     # AnonMode value string
    ingestion_error = Signal(str)       # error message
