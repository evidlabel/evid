"""evid tui — design notes.

Scope
-----
`evid tui` is a curses front-end whose *primary* workflow is quick addition:
paste a handful of URLs / PDF paths / directories into a set, then immediately
curate the new documents. It deliberately stays a front-end — every write goes
through the existing service layer, so nothing a user does in the TUI has a
behaviour different from the equivalent `evid` command.

Why curses (stdlib) instead of textual/prompt_toolkit
------------------------------------------------------
evid keeps its dependency surface small (the GUI is a stdlib web server; the
GUI extra is empty). Adding Textual would pull in rich+markdown-it+nested
deps for what is a small, focused app. curses handles the terminal work with
zero install cost and is already required on the platforms evid targets.

Layout (workspace)
------------------
    ┌ evid · <set name> (slug) · N docs ─ a add · t tag · n note · m meta · ? help ┐
    │ / <filter box>                                  [focus: list]              │
    │ ▸ Title of doc                      #court #dan 2026-11-01   │ title  ….   │
    │   …                                                           │ authors …. │
    │   …                                                           │ dates   …. │
    │   …                                                           │ …          │
    └────────────────────────────────────────────────────────────────────────────┘
     j/k move · / filter · a add · t tag · n note · m meta · o open · q quit

Panes
- Left: the set's documents, newest first, filterable by substring; each row
  shows selection cursor, title, tag chips, added date.
- Right: detail of the selected document — the editable info.yml fields, its
  tags, its note and its on-disk path.

Screens
- Set picker (`s`): choose / create the active set (skipped when -s given).
- Workspace: list + detail above.
- Add dialog (`a`): multi-line text area for sources; optional auto-applied
  tag and toggles for indexing and paragraph labels; streams per-document
  ✓/✗ results, then returns to the workspace with the batch at the top.
- Prompt: a single-line value dialog shared by tag / note / metadata edits.
- Help overlay (`?`).

Keymap (workspace)
------------------
    a          add documents (batch dialog)
    /          filter the document list by substring
    j/k · ↓/↑  move through the list
    g · G      top / bottom of the list
    t          assign a tag to the selected document
    T          remove a tag from the selected document
    n          set / edit the document's note (whole-document annotation)
    m          edit metadata (title / authors / dates / url)
    o · Enter  open the source (folder or viewer through open_external)
    Tab        move focus between the list and the detail
    s          switch evidence set
    r          refresh the list from disk
    ?          keymap help
    q · Ctrl+C quit

Decision notes
--------------
- Data is loaded fresh from info.yml on every refresh; the TUI keeps no cache,
  so it is always consistent with the CLI / GUI running on the same directory.
- Indexing follows the CLI: on by default but silently skipped when
  ``evid[vec]`` is not installed (extras.has_vec()), or when toggled off in the
  add dialog.
- Unsaved state never exists: tag / note / metadata actions write immediately
  (and report failures), so quitting is always safe and q is a hard exit.
"""
