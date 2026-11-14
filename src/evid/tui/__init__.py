"""Terminal workflow: ingest documents, label passages, copy labels, exit.

Uses the same ingestion, label storage and YAML export as the CLI and GUI.
"""

from evid.tui.app import run

__all__ = ["run"]
