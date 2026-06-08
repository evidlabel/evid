---
name: evid
description: Use when user installs, sets up, or works with the `evid` evidence-management CLI/GUI — ingest PDFs/URLs into evidence sets, label citable snippets, tag, search (vector or meta), gather BibTeX/Hayagriva/Markdown exports, or author an argument/memo/brief/report from a set. Triggers on "install evid", "add this PDF to my evid set", "label documents with evid", "search my case files", "gather bib from evid", "evid dataset for this matter", "evid label", "make an argument from my evid set", "write a memo/brief/notat from these sources", "author a document citing my labelled evidence", or managing legal/research document collections with evid.
---

# evid

(Caveman speak below = token-saving. Terse, telegraphic. Commands/flags/keys exact.)

evid = CLI + GUI. Ingest PDF/URL → searchable sets. Label citable spans in Typst (`#lab`). Export BibTeX/Hayagriva/Markdown/JSON/YAML.

**Pipeline no stop at `gather`.** User want argument/memo/brief/report from set → deliverable = citable Typst doc built with `labquote` (via **notat** skill). Quotes pulled from `refs.yml` by key, rendered verbatim. Never hand-write Markdown essay. Read **Authoring** below before writing prose.

## Citing discipline

`#lab(...)` spans = authoritative. `set gather` exports them unchanged. Gathered YAML may carry `# generated-by: evid v…` watermark — keep watermarks, no hand-edit entries.

## Get code

Source: https://github.com/evidlabel/evid (Python ≥ 3.11).

```bash
uv tool install "evid @ git+https://github.com/evidlabel/evid.git"
```

Dev: clone, `uv run evid …`. **Need:** `typst` on `$PATH` (label/gather); PySide6 (GUI).

## First setup

```bash
evid config update   # writes ~/.evidrc (editor + CLI prefs)
evid config show
```

**Data dir** (holds sets + `tags.yml`): default `~/.local/share/evid`. Old `~/.local/share/evidmgr` auto-detected. Override with `-d`/`--db`, or set `data_dir` in `~/.local/share/evid/evid.yml` (GUI). Legacy *evidmgr* = old paths only.

**Self-contained job → project-local db.** Authoring brief/notat, smoke test, anything portable/versioned: point EVERY command at db inside project with `-d ./evid`. Db + `refs.yml` + `main.typ` travel together:

```
my-brief/
  evid/sets/<slug>/docs/<uuid>/…   # LOCAL db (every command uses -d ./evid)
  brief/main.typ  refs.yml  main.pdf
```

Global default = standing personal collection only. Deliverable → no dump docs in global. Make local first (`evid -d ./evid set create -s <slug>`), pass `-d ./evid` on add/quote/gather/search. Authored doc but no `./evid` beside it = wrong db.

## Storage layout

Under `{data_dir}/`:

```
sets/<slug>/set.yml
sets/<slug>/docs/<uuid>/
  info.yml          # title, authors, tags (comma-separated), url, …
  evid_meta.yml     # notes, indexed, anon_pending (reads legacy evidmgr_meta.yml)
  original.pdf      # or original filename from CLI ingest
  label.typ → label.json, label.bib   # manual #lab labelling pipeline
  text.txt          # cached flat plain text (machine quoting; stable char offsets)
  machine.hayagriva # verbatim machine quotes (evid doc quote); merged by gather
tags.yml            # cross-set tag registry (TagService)
```

**Tag** writes both `info.yml` + `tags.yml` (CLI `tag assign` / GUI). Keep in sync, no edit one store only.

## Core

- **Set** = collection per case/matter. `evid set list` — refer by name or number.
- **GUI** (`evid`, no args): sidebar = sets; **Docs** + **Search** tabs load selected set on start + on selection change.

## Set management

```bash
evid set list
evid set create my-case
evid set track my-case          # git-init the set directory
```

## Add files

```bash
evid doc add /path/to/judgment.pdf --dataset my-case
evid doc add https://example.com/report.pdf -s my-case -l -a
```

`-l` = open labeler after add. `-a` = pre-wrap paragraphs `#lab("labN", text, "")`. List: `evid doc list -s my-case --format md` or `evid -j doc list -s my-case`.

## Labelling

1. `evid doc label -s my-case --uuid <uuid>` (or `--filename …`) → makes `label.typ`, opens editor.
2. Wrap passages: `#lab("stable_key", "exact verbatim text", "optional note")`.
3. Save + close → `typst query` writes `label.json` + `label.bib` (GUI watcher same after edit).
4. Keys stable + unique within set.

Editor (CLI): `evid config update`, set `editor` in `~/.evidrc` (default `code` = VS Code). GUI uses `editor` in `{data_dir}/evid.yml`.

### Editor setup (VS Code + Typst)

Full copy-paste steps in **[`README.md` — Labelling](README.md#labelling)**. User wants editor labelling → walk through:

1. Install **Typst** support in VS Code (ext id `mgt19937.typst-syntax` or current Typst ext) so `editorLangId == 'typst'` matches.
2. Add shortcut wrapping selection in `#lab(...)` — select text in `label.typ`, press binding, fill key + note tab stops:

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

Put in **Keyboard Shortcuts (JSON)** (`Preferences: Open Keyboard Shortcuts (JSON)`). Change `"key"` if `ctrl+l` conflicts (e.g. `"ctrl+shift+l"`).

3. Optional: same snippet under **User Snippets → typst.json**:

```json
{
  "evid lab": {
    "prefix": "lab",
    "body": "#lab(\"$1\", \"${TM_SELECTED_TEXT}\", \"$2\")",
    "description": "evid evidence label"
  }
}
```

4. Open label file: `evid doc label -s my-case --uuid <uuid>` or GUI **Label** / **Open in editor** on `label.typ`.

**Other editors:** set `editor` to executable (`nvim`, `emacsclient`, …), wrap manually `#lab("key", "verbatim text", "note")` or own snippet/macro. Syntax + post-save bib gen editor-agnostic; only the binding is VS Code-specific.

## Precise / machine quoting

Agent need **verbatim** quote from doc already in set (paraphrase unacceptable — legal/academic) → never retype. `rapidfuzz` matcher locates.

**Find what to quote.** Pick one:

- **One shot (uses vector index):**
  ```bash
  evid doc quote -s my-case -u <uuid> --from-search "share of male vs female victims" -n 4
  ```
  Vector search over set, top-`n` chunks of that doc = candidates, fuzzy-locate clean verbatim sentence each. Needs doc indexed (added *without* `--no-index`).
- **Explicit candidates:** discover first — `evid -j search vec "<topic>" -s my-case` or `grep` doc `text.txt` (written by `doc quote`) — then paraphrase into throwaway **`quotes.json`** (JSON, *deliberately not* Hayagriva/YAML, so paraphrase never loadable/citable):
  ```json
  { "quotes": [
      { "candidate": "approximate quote you want made verbatim" },
      { "candidate": "another loose quote", "min_ratio": 0.85 }
  ] }
  ```
  ```bash
  evid doc quote -s my-case -u <uuid> --from quotes.json
  ```

Either way: extracts doc plain text (cached `text.txt`), fuzzy-matches each, appends **verbatim** span to `machine.hayagriva` keyed `{uuid[:4]}:qN` (labquote-native: quote in `title:`, with `page-range` + `serial-number`, plus one `{uuid[:4]}:main`). Prints **keys only** — never quote text. Cite `@{uuid[:4]}:qN`; `evid set gather` merges `machine.hayagriva` (full `serial-number` in `.yaml`; `.bib`/`.md`/`.json` lossy).

**Re-quote.** `machine.hayagriva` append-only, `qN` by order. Change quote set: keep one `quotes.json` per doc, `rm <doc>/machine.hayagriva`, re-run `doc quote` — keys stay stable + reproducible.

**Discipline.** Paraphrase input = JSON *because not citable*. Only verbatim rapidfuzz `machine.hayagriva` = Hayagriva + citable. Never paraphrase source. Never paste quote text in answer — emit keys only. Machine entries carry `# verbatim, rapidfuzz-verified`. Below `--min-ratio` (default 0.78) = skipped, not invented.

> **Hyphen caveat.** Text de-hyphenated (`mar-\nkant` → `markant`). Real hard-hyphen compound wrapping at hyphen (`eks-partner`) may merge wrong — eyeball odd spans.

## Gathering

```bash
evid set gather my-case -o exports/refs.yml
evid set gather my-case -o exports/refs.bib
evid set gather my-case -o exports/refs.md --include-keys
evid set gather my-case -o exports/refs.json
```

`--no-regen` skips typst query when labels current. Machine quotes merged auto.

Outputs = **interchange/citation db, NOT finished document.** `refs.yml` = authoring input; `.bib`/`.json` feed other tools; `.md` (`--include-keys`) = key-check dump, NOT shippable argument. No stop at `gather` + hand-write prose around it.

## Authoring a document from a set (the deliverable)

Task = **make argument / memo / brief / report / notat** from set → output = **compiled Typst doc**, every quote verbatim from `refs.yml` via `labquote` (`#blockq` / `#cite-ref`), never retyped/paraphrased to Markdown. This is point of labelling+gathering. No hand-write `.md` essay + call done (defeats verbatim-citation guarantee).

**REQUIRED SKILL: notat** = authoring layer over `labquote` (read **labquote** first: `setup`/`q`/`blockq`/`cite-ref`/`bibliography-custom` + namespaced-key contract). notat owns writing discipline, subset-`refs.yml` rule, preamble template, compile/verify loop.

Chain. **Every `evid` command uses `-d ./evid`** (project-local db, see *Data dir*):

0. **Make local db** — `evid -d ./evid set create -s <slug>`. Db in project, beside doc. No touch global.
1. **Ingest** each source — `evid -d ./evid doc add <src> -s <slug>` (URL, local PDF, or copy `<uuid>` dir from another set into `./evid/sets/<slug>/docs/` to keep its manual labels).
2. **Make citable** — manual `#lab` (`evid -d ./evid doc label`) and/or machine quotes (`evid -d ./evid doc quote`, see *Precise / machine quoting*).
3. **Gather** → `evid -d ./evid set gather <slug> -o brief/refs.yml` (labquote-native Hayagriva; source of truth for quote text).
4. **Author** `main.typ` with `labquote` via **notat** — prose = keys only; quotes pull from `refs.yml`. Build **subset** `refs.yml` (cited keys + each cited doc `:main`) so `bibliography-custom()` stays focused.
5. **Compile + verify** — `typst compile main.typ` → PDF. Bad slice anchor or missing key = compile error. Eyeball rendered quotes + grouped back-page.
6. **Version** — `git init` project root, db + brief = one reproducible unit. Commit brief source + db evidence (original PDFs, `label.typ`/`label.json`, `machine.hayagriva`). `.gitignore` regenerable bits:

   ```gitignore
   **/vecdb/        # chroma index — rebuilt from label.typ
   brief/*.pdf      # compiled output
   brief/page-*.png
   ```

   (`evid set track` = evid-native shortcut, git-init set/db dir only.)

Quote not yet in `refs.yml`? No type it. Label (`evid`) or machine-quote (`evid doc quote`), re-gather, cite key.

## Tag & search

```bash
evid tag assign <uuid> "priority-review" -s my-case   # updates info.yml + tags.yml
evid tag list
evid tag show priority-review -s my-case
evid search vec "query" -s my-case --n 15
evid search meta "pattern" -s my-case --format json
```

Qualified tag default `{set_slug}.{name}` when name has no dot.

## GUI (Docs / Search)

| Action | How |
|--------|-----|
| Open GUI | `evid` or `evid gui` |
| Select set | Sidebar list (keyboard selection works) |
| Multi-select docs | Drag across rows in Docs table; Ctrl+click toggle; Shift+click extend |
| Copy doc to another set | **Alt+drag** a row onto a sidebar set |
| Tag from Search results | Context menu — writes both stores |
| Main tabs | Ctrl+PageUp / Ctrl+PageDown |

Anonymize UI under Docs → **Anonymize** (no top-level tab). Log pane bottom = DEBUG+.

## Other commands

`doc bibtex`, `doc rebut`. Built on **treeparse** — rich `--help`. Top-level `evid -j <subcommand> …` = clean JSON (`jq`). Global: `-d`/`--db`, `-j`, `--help`.

## Common options

| Flag / Pattern | Meaning |
|----------------|---------|
| `-s, --dataset` | Set by slug/name or number |
| `-d, --db` | Evidence data directory (`sets/`, `tags.yml`) |
| `--format table\|md\|json` | List/show/search/gather |
| `-j` | Top-level JSON (prefer for agents) |
| `set gather --no-regen` | Skip typst query |

## Common mistakes

- **Dump deliverable docs in global db, not project-local `-d ./evid`.** Authoring/smoke/portable job = own local db beside `main.typ`. No `./evid` folder left = wrong db. Pass `-d ./evid` every command.
- **Self-contained job left un-versioned.** `git init` project root (db + brief) = reproducible + portable. `.gitignore` only regenerable (`**/vecdb/`, compiled `*.pdf`/`page-*.png`). No commit vecdb, no skip git.
- **Hand-write argument as Markdown memo, not citable Typst doc** (`labquote` via **notat**). Gathered `.md` = key-check export, not deliverable. Stop at `gather` + hand-write = discards verbatim-citation guarantee.
- No `typst` installed.
- Hand-edit `label.bib`/`label.json` instead of `label.typ`.
- Hand-edit `machine.hayagriva` or paste verbatim quote in answer — run `evid doc quote`, cite key.
- Candidate quotes in YAML/Hayagriva not `quotes.json` (input = JSON precisely so not citable).
- Change label keys after citing them in a document.
- Tag only `info.yml` or only `tags.yml` outside normal CLI/GUI paths.
- `gather` huge sets without `--no-regen` every time.
- HTML landing pages instead of PDF judgments.
- Skip `set track` when set itself needs versioning.
- Expect plain left-drag on doc row to copy to sidebar (use **Alt+drag**).

## Quick start

Standing personal collection (global db):

```bash
evid set create echr-2024-001
evid doc add ~/cases/doc.pdf -s echr-2024-001 -l -a
evid set gather echr-2024-001 -o exports/refs.yml
evid -j search vec "separation" -s echr-2024-001
```

Self-contained deliverable (project-local db — preferred for authoring/smoke):

```bash
evid -d ./evid set create -s mybrief
evid -d ./evid doc add ~/cases/doc.pdf -s mybrief
evid -d ./evid set gather mybrief -o brief/refs.yml
# → author brief/main.typ with labquote (notat skill), then `typst compile`
```

Run `evid <subcommand> --help` or `evid -j … --help` for current flags. `evid` alone opens the GUI.
