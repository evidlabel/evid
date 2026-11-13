""""evid tui — design notes.

Scope
-----
`evid tui` is a Textual front-end whose *primary* workflow is quick addition:
paste a handful of URLs / PDF paths / directories into a set, then immediately
curate the new documents. It deliberately stays a front-end — every write goes
through the existing service layer, so nothing a user does in the TUI has a
behaviour different from the equivalent `evid` command.

Why Textual instead of hand-rolled curses
-----------------------------------------
curses (stdlib) was the first cut, but Textual was the better base for the
long term: widgets + layout + focus + CSS and a headless testing harness
(Pilot) for free, plus `textual-serve` if we ever want the same UI in a
browser. The added dependency is accepted — this is a maintained, active
library (textual is the modern Python TUI framework in the FastAPI/Rich
ecosystem), and the TUI is core, not an optional extra. The data layer stays
in `data.py`, which remains curses- and TUI-free and is reused by the tests.

Layout (workspace)
------------------
Header ── filter ── list (62%) | detail (38%) ── footer
List rows: title · tag chips · added date. Detail: the editable info.yml
fields, tags, note and on-disk path for the highlighted row.

Screens
- Set picker (ModalScreen): choose / create the active set (skipped when `-s`
  is given).
- Workspace (MainScreen): list + detail above.
- Add dialog (`a`, ModalScreen): multi-line TextArea for sources, toggles for
  indexing and paragraph labels, streams per-document ✓/✗ results through a
  worker (non-blocking), then returns the batch.
- Prompt: single-line value dialog shared by tag / note / metadata edits.
- Metadata editor: four labelled inputs (title / authors / dates / url).
- Help overlay.

Keymap (workspace)
------------------
    a          add documents (batch dialog)
    / · j/k    filter · move through the list
    t / T      tag / untag the selected document
    n          set / edit the document's note
    m          edit metadata
    o · enter  open the source (folder or viewer through open_external)
    s          switch evidence set
    r          refresh the list from disk
    ?          keymap help
    q · ctrl+c quit

Decision notes
--------------
- Data is loaded fresh from info.yml on every refresh; the TUI keeps no cache,
  so it is always consistent with the CLI / GUI running on the same directory.
- Indexing follows the CLI: on by default but silently skipped when
  ``evid[vec]`` is not installed (extras.has_vec()), or when toggled off in the
  add dialog.
- Unsaved state never exists: tag / note / metadata actions write immediately
  (and report failures), so quitting is always safe and q is a hard exit.
- UI work happens on the Textual thread; the add batch runs in a thread worker
  and posts progress back with `call_from_thread`, so ingestion never blocks
  the interface. Tests drive the app headlessly with `app.run_test()` + Pilot.
"""

