---
name: evid
description: Use when the user wants to install, set up, or work with the `evid` evidence management CLI or GUI to ingest PDFs/URLs as case files into evidence sets, label citable snippets, tag, search (vector or meta), and gather BibTeX/Hayagriva/Markdown exports. Triggers on "install evid", "add this PDF to my evid set", "label documents with evid", "search my case files", "gather bib from evid", "evid dataset for this matter", "evid label", or managing legal/research document collections with evid.
---

# evid

`evid` (CLI + GUI) ingests PDFs/URLs into searchable evidence sets, labels citable spans in Typst (`#lab`), and exports BibTeX/Hayagriva/Markdown/JSON/YAML.

## Citing discipline

When exporting or citing labelled sets, treat `#lab(...)` spans as authoritative: `set gather` exports them unchanged; gathered YAML may include `# generated-by: evid v…` — preserve watermarks and do not hand-edit entries.

## Where to get the code

Source: https://github.com/evidlabel/evid (Python ≥ 3.11).

```bash
uv tool install "evid @ git+https://github.com/evidlabel/evid.git"
```

Clone locally and `uv run evid …` for dev. **Hard requirements:** `typst` on `$PATH` (for `label` / `gather`); PySide6 for GUI.

## First-time setup

```bash
evid config update   # writes ~/.evidrc (editor and related CLI prefs)
evid config show
```

**Data directory** (where sets and `tags.yml` live): defaults to `~/.local/share/evid`. Existing installs under `~/.local/share/evidmgr` are detected automatically. Override per invocation with `-d` / `--db` or set `data_dir` in `~/.local/share/evid/evid.yml` (GUI). Legacy name *evidmgr* still works for old paths only.

## Storage layout

Under `{data_dir}/`:

```
sets/<slug>/set.yml
sets/<slug>/docs/<uuid>/
  info.yml          # title, authors, tags (comma-separated), url, …
  evid_meta.yml     # notes, indexed, anon_pending (reads legacy evidmgr_meta.yml)
  original.pdf      # or original filename from CLI ingest
  label.typ → label.json, label.bib
tags.yml            # cross-set tag registry (TagService)
```

**Tagging** updates both `info.yml` and `tags.yml` (CLI `tag assign` / GUI Docs and Search) — keep them in sync; do not edit only one store.

## Core concepts

- **Evidence set**: named collection per case/matter. `evid set list` — refer by name or number.
- **GUI** (`evid` with no args): sidebar lists sets; **Docs** and **Search** tabs load the selected set on startup and when the selection changes.

## Evidence set management

```bash
evid set list
evid set create my-case
evid set track my-case          # git-init the set directory
```

## Adding case files

```bash
evid doc add /path/to/judgment.pdf --dataset my-case
evid doc add https://example.com/report.pdf -s my-case -l -a
```

`-l` opens labeler after ingest; `-a` pre-wraps paragraphs with `#lab("labN", text, "")`. List docs: `evid doc list -s my-case --format md` or `evid -j doc list -s my-case`.

## Labelling workflow

1. `evid doc label -s my-case --uuid <uuid>` (or `--filename …`) — generates `label.typ` and opens it in your configured editor.
2. Wrap passages: `#lab("stable_key", "exact verbatim text", "optional note")`.
3. Save and close the editor → `typst query` writes `label.json` + `label.bib` (GUI watcher does the same after edit).
4. Use stable, unique keys within the set.

Set the editor (CLI): `evid config update` then edit `editor` in `~/.evidrc` (default `code` = VS Code). GUI uses `editor` in `{data_dir}/evid.yml`.

### Editor setup (recommended: VS Code + Typst)

Full copy-paste instructions are in **[`README.md` — Labelling](README.md#labelling)**. When the user asks to set up labelling in an editor, walk them through this:

1. Install the **Typst** language support in VS Code (extension id `mgt19937.typst-syntax` or current marketplace Typst extension) so `editorLangId == 'typst'` matches.
2. Add a **keyboard shortcut** that wraps the selection in `#lab(...)` — select text in `label.typ`, press the binding, fill key and note tab stops:

```json
{
  "key": "ctrl+l",
  "command": "editor.action.insertSnippet",
  "when": "editorTextFocus && editorLangId == 'typst'",
  "args": {
    "snippet": "#lab(\"$1\",\"${TM_SELECTED_TEXT}\",\"$2\")"
  }
}
```

Put that in **Keyboard Shortcuts (JSON)** (`Preferences: Open Keyboard Shortcuts (JSON)`). Change `"key"` if `ctrl+l` conflicts (e.g. `"ctrl+shift+l"`).

3. Optional: add the same snippet under **User Snippets → typst.json**:

```json
{
  "evid lab": {
    "prefix": "lab",
    "body": "#lab(\"$1\", \"${TM_SELECTED_TEXT}\", \"$2\")",
    "description": "evid evidence label"
  }
}
```

4. Open a label file: `evid doc label -s my-case --uuid <uuid>` or GUI **Label** / **Open in editor** on `label.typ`.

**Other editors:** set `editor` in config to the executable (`nvim`, `emacsclient`, etc.) and wrap selections manually with `#lab("key", "verbatim text", "note")`, or define an equivalent snippet/macro. The syntax and post-save bib generation are editor-agnostic; only the convenience binding is VS Code–documented in the README.

## Gathering

```bash
evid set gather my-case -o exports/refs.yml
evid set gather my-case -o exports/refs.bib
evid set gather my-case -o exports/refs.md --include-keys
evid set gather my-case -o exports/refs.json
```

`--no-regen` skips typst query when labels are current.

## Tagging & search

```bash
evid tag assign <uuid> "priority-review" -s my-case   # updates info.yml + tags.yml
evid tag list
evid tag show priority-review -s my-case
evid search vec "query" -s my-case --n 15
evid search meta "pattern" -s my-case --format json
```

Qualified tag names default to `{set_slug}.{name}` when the tag has no dot.

## GUI (Docs / Search)

| Action | How |
|--------|-----|
| Open GUI | `evid` or `evid gui` |
| Select set | Sidebar list (keyboard selection works) |
| Multi-select docs | Drag across rows in Docs table; Ctrl+click toggle; Shift+click extend |
| Copy doc to another set | **Alt+drag** a row onto a sidebar set |
| Tag from Search results | Context menu — writes both stores |
| Main tabs | Ctrl+PageUp / Ctrl+PageDown |

Anonymization UI lives under Docs → **Anonymize** (not a top-level tab). Log pane at the bottom shows DEBUG+ messages.

## Other commands

`doc bibtex`, `doc rebut`, `prompt export`. Built on **treeparse** — rich `--help`; use top-level **`evid -j <subcommand> …`** for clean JSON (`jq`). Global: `-d`/`--db`, `-j`, `--help`.

## Common options

| Flag / Pattern | Meaning |
|----------------|---------|
| `-s, --dataset` | Set by slug/name or number |
| `-d, --db` | Evidence data directory (`sets/`, `tags.yml`) |
| `--format table\|md\|json` | List/show/search/gather |
| `-j` | Top-level JSON (prefer for agents) |
| `set gather --no-regen` | Skip typst query |

## Common mistakes

- No `typst` installed.
- Hand-editing `label.bib`/`label.json` instead of `label.typ`.
- Changing label keys after citing them in a document.
- Tagging only `info.yml` or only `tags.yml` outside the normal CLI/GUI paths.
- `gather` on huge sets without `--no-regen` every time.
- HTML landing pages instead of PDF judgments.
- Skipping `set track` when the set itself needs versioning.
- Expecting plain left-drag on a doc row to copy to sidebar (use **Alt+drag**).

## Quick start

```bash
evid set create echr-2024-001
evid doc add ~/cases/doc.pdf -s echr-2024-001 -l -a
evid set gather echr-2024-001 -o exports/refs.yml
evid -j search vec "separation" -s echr-2024-001
```

Run `evid <subcommand> --help` or `evid -j … --help` for current flags. `evid` alone opens the GUI.
