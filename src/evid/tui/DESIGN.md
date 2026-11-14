# evid TUI

The workflow is ingest → label → copy labels → exit.

- A compact set selector and source input sit above two panes: documents and
  paragraphs. The paragraph reader gets most of the available width and scrolls
  independently so long passages remain readable.
- Paste a URL, PDF path or folder and press Enter or Ingest. A fresh library
  uses inbox; an explicit `-s` is retained and created on ingestion. Directories
  expand to PDFs. Ingestion never starts vector indexing or automatic labelling.
- After ingest, select a paragraph and press Ctrl+L, matching the Tauri app.
  Alt+↑ / Alt+↓ selects the previous / next document and keeps labeller focus;
  at the first or last document it stays put. Enter and l remain label aliases.
  The suggested key can
  be edited; saving writes immediately through core.labels and preserves the
  paragraph cursor. L removes a label to correct mistakes.
- Copy labels (c) exports all persisted labels in the active set, including
  labels from earlier sessions, through core.prompt.labels_to_yaml. It includes
  document references and quote text. Empty exports leave the clipboard alone.
  Clipboard transport uses Textual's OSC 52 support; the terminal must allow it.
- Exit (q, Ctrl+W or Ctrl+Q) needs no save step. Escape returns to the documents
  pane. Ctrl+W / Ctrl+Q also work in text fields, matching Tauri.

The TUI has no tagging, notes, metadata editor, external opener, document filter,
separate batch dialog, indexing toggles or command palette. These belong to the
CLI and GUI. A folder handles batch ingestion without a second ingest UI.

Slow ingest, paragraph extraction and export run in workers. Busy ingest/export
prevents duplicate submissions, set changes and exit until completion. Errors
are logged and shown in the persistent status area. Failed sources remain in
place for retry. Paragraph results carry a generation number so old workers
cannot replace the current document or a newer label refresh.

Headless Pilot tests exercise real PDF ingestion, label persistence, YAML
clipboard content, exit, cursor retention, set changes and failure recovery.
