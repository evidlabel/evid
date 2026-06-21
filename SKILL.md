---
name: evid
description: Use when user installs, sets up, or works with the `evid` evidence-management CLI/GUI — ingest PDFs/URLs into evidence sets, label citable snippets, tag, search (vector or meta), gather BibTeX/Hayagriva/Markdown exports, or author an argument/memo/brief/report from a set. Triggers on "install evid", "add this PDF to my evid set", "label documents with evid", "search my case files", "gather bib from evid", "evid dataset for this matter", "evid label", "make an argument from my evid set", "write a memo/brief/notat from these sources", "author a document citing my labelled evidence", or managing legal/research document collections with evid.
---

# evid

`evid` is a CLI and GUI for ingesting PDFs and URLs into searchable evidence sets, labelling citable spans in Typst (`#lab`), and exporting BibTeX, Hayagriva, Markdown, JSON, or YAML.

**The pipeline does not end at `gather`.** When the user wants an argument, memo, brief, or report from a set, the deliverable is a citable Typst document built with `labquote` (via the **notat** skill). Quotes are pulled from `refs.yml` by key and rendered verbatim. Do not hand-write a Markdown essay. Read **Authoring** below before writing prose.

## Workflow at a glance — search first, then quote

Ingest → **search** → make citable → gather → author. Discovery is **search-first**, and quoting is **verbatim** — these two steps are the heart of evid:

1. **Ingest** sources — `evid doc add` (keep the vector index; do not pass `--no-index`).
2. **Find passages with vector search** — `evid search vec "<topic>" -s <set>` (agents: `evid -j search vec …`) is the **primary way to locate citable text**. It is *semantic*: query by meaning, not exact wording, and run a few targeted queries rather than dumping `text.txt` or reading whole PDFs. Cost is honest — the first query in a fresh process pays a ~0.5–2 s model load (each CLI invocation is its own process); later queries in the same run are fast. `gather`/flat-Markdown export is for **assembling** evidence you already found, *not* for discovery.
3. **Make passages citable — verbatim.** Machine-quote with **`evid doc quote`** (the verbatim `rapidfuzz` path — see *Precise / machine quoting*) and/or manual `#lab` labelling. Never retype a legal/academic quote.
4. **Gather** (`evid set gather`) → **author** a citable Typst document with `labquote`/notat.

Steps 2–3 (vector search → machine quote) are the default loop for "find me a quote about X" and for sourcing every claim in a deliverable.

## Citing discipline

`#lab(...)` spans are authoritative. `set gather` exports them unchanged. Gathered YAML may carry a `# generated-by: evid v…` watermark — keep watermarks; do not hand-edit entries.

## Get code

Source: https://github.com/evidlabel/evid (Python ≥ 3.11).

```bash
uv tool install "evid @ git+https://github.com/evidlabel/evid.git"
```

For development: clone the repo and run `uv run evid …`. **Requirements:** `typst` on `$PATH` (for label/gather); PySide6 (for the GUI).

## First setup

```bash
evid config update   # writes ~/.evidrc (editor + CLI prefs)
evid config show
```

**Data directory** (holds sets and `tags.yml`): default `~/.local/share/evid`. The legacy path `~/.local/share/evidmgr` is auto-detected. Override with `-d`/`--db`, or set `data_dir` in `~/.local/share/evid/evid.yml` (GUI). *evidmgr* refers to old paths only.

**Self-contained jobs use a project-local database.** For authoring a brief/notat, smoke tests, or anything portable and versioned, point every command at a database inside the project with `-d ./evid`. The database, `refs.yml`, and `main.typ` travel together:

```
my-brief/
  evid/sets/<slug>/docs/<uuid>/…   # LOCAL db (every command uses -d ./evid)
  brief/main.typ  refs.yml  main.pdf
```

Use the global default only for a standing personal collection. For deliverables, do not dump documents into the global database. Create a local database first (`evid -d ./evid set create -s <slug>`), then pass `-d ./evid` on add, quote, gather, and search. If you authored a document but there is no `./evid` folder beside it, you used the wrong database.

## Storage layout

Under `{data_dir}/`:

```
sets/<slug>/set.yml
sets/<slug>/docs/<uuid>/
  info.yml          # title, authors, tags (comma-separated), url, …
  evid_meta.yml     # notes, indexed (reads legacy evidmgr_meta.yml)
  original.pdf      # or original filename from CLI ingest
  label.typ → label.json, label.bib   # manual #lab labelling pipeline
  text.txt          # cached flat plain text (machine quoting; stable char offsets)
  machine.hayagriva # verbatim machine quotes (evid doc quote); merged by gather
tags.yml            # cross-set tag registry (TagService)
```

Tagging writes both `info.yml` and `tags.yml` (CLI `tag assign` or GUI). Keep them in sync — do not edit one store only.

## Core

- **Set** — a collection per case or matter. List with `evid set list`; refer by name or number.
- **GUI** (`evid gui`): sidebar lists sets; **Docs** and **Search** tabs load the selected set on start and when selection changes.

## Set management

```bash
evid set list
evid set create my-case
evid set track my-case          # git-init the set directory
evid set reindex -s my-case     # rebuild the vector index for every doc in the set
```

Use `set reindex` to refresh an existing set's vector index after upgrading evid (e.g. a chunking or embedding-model change) — it re-chunks each `label.typ` and replaces the old vecdb entries.

**Embedding model.** Vector search uses a sentence-transformers model, configurable via `embedding_model` in `{data_dir}/evid.yml` or the `EVID_EMBEDDING_MODEL` env var (env wins). Default: **`intfloat/multilingual-e5-small`** — multilingual (strong on Danish legal text), 384-dim, MIT. Changing the model invalidates existing indexes (embeddings from two models aren't comparable), so **run `evid set reindex` on each set after changing it** — a query against a stale index logs a warning. e5 models apply `query:`/`passage:` prefixes automatically; other models use none.

## Add files

```bash
evid doc add /path/to/judgment.pdf --dataset my-case
evid doc add https://example.com/report.pdf -s my-case -l -a
```

`-l` opens the labeler after add. `-a` pre-wraps paragraphs as `#lab("labN", text, "")`. List documents with `evid doc list -s my-case --format md` or `evid -j doc list -s my-case`.

## Labelling

1. `evid doc label -s my-case --uuid <uuid>` (or `--filename …`) — creates `label.typ` and opens the editor.
2. Wrap passages: `#lab("stable_key", "exact verbatim text", "optional note")`.
3. Save and close — `typst query` writes `label.json` and `label.bib` (the GUI watcher does the same after edit).
4. Keys must be stable and unique within the set.

Editor (CLI): run `evid config update` and set `editor` in `~/.evidrc` (default `code` = VS Code). The GUI uses `editor` in `{data_dir}/evid.yml`.

### Editor setup (VS Code + Typst)

Full copy-paste steps are in **[`README.md` — Labelling](README.md#labelling)**. When the user wants editor labelling, walk through:

1. Install **Typst** support in VS Code (extension id `mgt19937.typst-syntax` or the current Typst extension) so `editorLangId == 'typst'` matches.
2. Add a shortcut that wraps the selection in `#lab(...)` — select text in `label.typ`, press the binding, and fill key and note tab stops:

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

Add this in **Keyboard Shortcuts (JSON)** (`Preferences: Open Keyboard Shortcuts (JSON)`). Change `"key"` if `ctrl+l` conflicts (e.g. `"ctrl+shift+l"`).

3. Optional: the same snippet under **User Snippets → typst.json**:

```json
{
  "evid lab": {
    "prefix": "lab",
    "body": "#lab(\"$1\", \"${TM_SELECTED_TEXT}\", \"$2\")",
    "description": "evid evidence label"
  }
}
```

4. Open a label file with `evid doc label -s my-case --uuid <uuid>` or via the GUI **Label** / **Open in editor** on `label.typ`.

**Other editors:** set `editor` to your executable (`nvim`, `emacsclient`, …), then wrap manually with `#lab("key", "verbatim text", "note")` or your own snippet/macro. Syntax and post-save bib generation are editor-agnostic; only the binding above is VS Code-specific.

## Precise / machine quoting

This is the **verbatim quoting workflow** — the core of evid for sourcing claims. When an agent needs a **verbatim** quote from a document already in the set (paraphrase is unacceptable for legal or academic work), never retype the text. The `rapidfuzz` matcher locates it.

**Find what to quote — search first.** Vector search is the primary discovery tool; pick one approach:

- **One shot (uses the vector index):**
  ```bash
  evid doc quote -s my-case -u <uuid> --from-search "share of male vs female victims" -n 4
  ```
  Vector search over the set returns the top-`n` chunks of that document as candidates; each is fuzzy-located to a clean verbatim sentence. The document must be indexed (added *without* `--no-index`).
- **Explicit candidates:** discover first — `evid -j search vec "<topic>" -s my-case` or `grep` the document's `text.txt` (written by `doc quote`) — then paraphrase into a throwaway **`quotes.json`** (JSON, *deliberately not* Hayagriva/YAML, so paraphrased input is never loadable or citable):
  ```json
  { "quotes": [
      { "candidate": "approximate quote you want made verbatim" },
      { "candidate": "another loose quote", "min_ratio": 0.85 }
  ] }
  ```
  ```bash
  evid doc quote -s my-case -u <uuid> --from quotes.json
  ```

Either way: extracts the document's plain text (cached as `text.txt`), fuzzy-matches each candidate, and appends the **verbatim** span to `machine.hayagriva` keyed `{uuid[:4]}:qN` (labquote-native: quote in `title:`, with `page-range` and `serial-number`, plus one `{uuid[:4]}:main`). Prints **keys only** — never the quote text. Cite `@{uuid[:4]}:qN`; `evid set gather` merges `machine.hayagriva` (full `serial-number` in `.yaml`; `.bib`/`.md`/`.json` are lossy).

**Re-quoting.** `machine.hayagriva` is append-only; `qN` follows order. To change the quote set: keep one `quotes.json` per document, `rm <doc>/machine.hayagriva`, and re-run `doc quote` — keys stay stable and reproducible.

**Discipline.** Paraphrased input goes in JSON *because it is not citable*. Only verbatim rapidfuzz output in `machine.hayagriva` is Hayagriva and citable. Never paraphrase the source. Never paste quote text in the answer — emit keys only. Machine entries carry `# verbatim, rapidfuzz-verified`. Matches below `--min-ratio` (default 0.78) are skipped, not invented.

> **Hyphen caveat.** Text is de-hyphenated (`mar-\nkant` → `markant`). A real hard-hyphen compound wrapping at the hyphen (`eks-partner`) may merge incorrectly — eyeball odd spans.

## Gathering

```bash
evid set gather my-case -o exports/refs.yml
evid set gather my-case -o exports/refs.bib
evid set gather my-case -o exports/refs.md --include-keys
evid set gather my-case -o exports/refs.json
```

`--no-regen` skips `typst query` when labels are current. Machine quotes are merged automatically.

Outputs are an **interchange/citation database, not a finished document.** `refs.yml` is authoring input; `.bib` and `.json` feed other tools; `.md` (with `--include-keys`) is a key-check dump, not a shippable argument. Do not stop at `gather` and hand-write prose around it.

## Authoring a document from a set (the deliverable)

When the task is to **make an argument, memo, brief, report, or notat** from a set, the output is a **compiled Typst document** where every quote is verbatim from `refs.yml` via `labquote` (`#blockq` / `#cite-ref`), never retyped or paraphrased into Markdown. This is the point of labelling and gathering. Do not hand-write a `.md` essay and call it done — that defeats the verbatim-citation guarantee.

**Required skill: notat** — the authoring layer over `labquote` (read **labquote** first: `setup`/`q`/`blockq`/`cite-ref`/`bibliography-custom` and the namespaced-key contract). notat owns writing discipline, the subset-`refs.yml` rule, the preamble template, and the compile/verify loop.

Workflow. **Every `evid` command uses `-d ./evid`** (project-local database; see *Data dir*):

0. **Create a local database** — `evid -d ./evid set create -s <slug>`. The database lives in the project, beside the document. Do not use the global database.
1. **Ingest** each source — `evid -d ./evid doc add <src> -s <slug>` (URL, local PDF, or copy a `<uuid>` directory from another set into `./evid/sets/<slug>/docs/` to keep its manual labels).
2. **Make sources citable** — manual `#lab` (`evid -d ./evid doc label`) and/or machine quotes (`evid -d ./evid doc quote`; see *Precise / machine quoting*).
3. **Gather** — `evid -d ./evid set gather <slug> -o brief/refs.yml` (labquote-native Hayagriva; source of truth for quote text).
4. **Author** `main.typ` with `labquote` via **notat** — prose uses keys only; quotes pull from `refs.yml`. Build a **subset** `refs.yml` (cited keys plus each cited document's `:main`) so `bibliography-custom()` stays focused.
5. **Compile and verify** — `typst compile main.typ` → PDF. A bad slice anchor or missing key causes a compile error. Eyeball rendered quotes and the grouped back-page.
6. **Version** — `git init` at the project root; the database and brief form one reproducible unit. Commit brief source and database evidence (original PDFs, `label.typ`/`label.json`, `machine.hayagriva`). `.gitignore` regenerable artifacts:

   ```gitignore
   **/vecdb/        # chroma index — rebuilt from label.typ
   brief/*.pdf      # compiled output
   brief/page-*.png
   ```

   (`evid set track` is an evid-native shortcut that git-inits the set/database directory only.)

If a quote is not yet in `refs.yml`, do not type it. Label it (`evid`) or machine-quote it (`evid doc quote`), re-gather, then cite the key.

## Tag & search

```bash
evid tag assign <uuid> "priority-review" -s my-case   # updates info.yml + tags.yml
evid tag list
evid tag show priority-review -s my-case
evid search vec "query" -s my-case --n 15            # semantic (vector)
evid search meta "pattern" -s my-case --format json  # regex over info.yml metadata
evid search text "phrase" -s my-case                 # full-text body, fuzzy (rapidfuzz)
evid search text "Section \d+" -s my-case --regex    # full-text body, regex
```

Three search axes: **`vec`** (semantic meaning), **`meta`** (regex over `info.yml`
fields), and **`text`** (the document *body*). `search text` extracts each doc's
plain text (PDF/txt → cached `text.txt`) and matches it: fuzzy `rapidfuzz`
ranking by default (tolerant of typos/paraphrase, one hit per doc), or every
`--regex` match. Each hit reports the page and a snippet. Useful when you know a
phrase is *in* a document but it isn't labelled or semantically distinctive.
Options: `--n`, `--min-ratio` (fuzzy threshold), `--context` (regex snippet
width), `--refresh` (re-extract text.txt).

Qualified tags default to `{set_slug}.{name}` when the name has no dot.

## MCP server — warm query session for agents (research loops)

Each `evid search vec` CLI call is a fresh process that re-imports torch and reloads the embedding model (**~10 s cold start**), so running a *sequence* of queries from the CLI is slow. For agent-driven research over a set, run the **MCP server** instead — it loads the model **once** and keeps Chroma warm, so every call after startup is sub-second:

```bash
evid -d ./evid mcp my-case     # stdio MCP server, scoped to ONE set (dataset is positional)
```

**The server is scoped to a single dataset** (the `<dataset>` argument is required). Every tool operates only on that set — there is no `list_sets` and no `dataset` argument — so an attached agent cannot discover or reach other (private) sets in the same database. Register that command as a stdio MCP server in your agent/client. Tools:

- `search_vec(query, n=10, tag="")` — **primary discovery**; top-n chunks as JSON (score, label, uuid, chunk_idx, char_start, preview). Warm across calls.
- `search_text(query, regex=False, n=10)` — full-text body search (fuzzy or regex); JSON with uuid, label, page, char_start, score, snippet.
- `search_meta(pattern)` — regex over `info.yml`.
- `list_docs()` — uuid/label/tags for this set.
- `doc_quotes(uuid)` — a doc's labelled citations as Markdown.

Use the server for the *discovery* loop (many `search_vec`/`search_text` calls); fall back to one-off `evid search …` on the CLI for a single query. Machine-quoting and gathering still go through the CLI (`evid doc quote`, `evid set gather`).

## GUI (Docs / Search)

| Action | How |
|--------|-----|
| Open GUI | `evid gui` (bare `evid` prints CLI help) |
| Select set | Sidebar list (keyboard selection works) |
| Multi-select docs | Drag across rows in Docs table; Ctrl+click toggle; Shift+click extend |
| Copy doc to another set | **Alt+drag** a row onto a sidebar set |
| Tag from Search results | Context menu — writes both stores |
| Main tabs | Ctrl+PageUp / Ctrl+PageDown |

The log pane at the bottom shows DEBUG and above.

## Other commands

`doc bibtex`, `doc rebut`. Built on **treeparse** — rich `--help`. Top-level `evid -j <subcommand> …` returns clean JSON (`jq`). Global flags: `-d`/`--db`, `-j`, `--help`.

## Common options

| Flag / Pattern | Meaning |
|----------------|---------|
| `-s, --dataset` | Set by slug/name or number |
| `-d, --db` | Evidence data directory (`sets/`, `tags.yml`) |
| `--format table\|md\|json` | List/show/search/gather |
| `-j` | Top-level JSON (prefer for agents) |
| `set gather --no-regen` | Skip typst query |

## Common mistakes

- **Dumping deliverable documents in the global database instead of a project-local `-d ./evid`.** Authoring, smoke tests, and portable jobs need their own local database beside `main.typ`. No `./evid` folder left behind means the wrong database was used. Pass `-d ./evid` on every command.
- **Leaving a self-contained job un-versioned.** `git init` at the project root (database + brief) makes the work reproducible and portable. `.gitignore` only regenerable artifacts (`**/vecdb/`, compiled `*.pdf`/`page-*.png`). Do not commit vecdb; do not skip git.
- **Hand-writing an argument as a Markdown memo instead of a citable Typst document** (`labquote` via **notat**). Gathered `.md` is a key-check export, not a deliverable. Stopping at `gather` and hand-writing prose discards the verbatim-citation guarantee.
- `typst` not installed.
- Hand-editing `label.bib`/`label.json` instead of `label.typ`.
- Hand-editing `machine.hayagriva` or pasting verbatim quote text in the answer — run `evid doc quote` and cite the key.
- Putting candidate quotes in YAML/Hayagriva instead of `quotes.json` (input is JSON precisely so it is not citable).
- Changing label keys after citing them in a document.
- Tagging only `info.yml` or only `tags.yml` outside normal CLI/GUI paths.
- Running `gather` on huge sets without `--no-regen` every time.
- Ingesting HTML landing pages instead of PDF judgments.
- Skipping `set track` when the set itself needs versioning.
- Expecting plain left-drag on a doc row to copy to the sidebar (use **Alt+drag**).

## Quick start

Standing personal collection (global database):

```bash
evid set create echr-2024-001
evid doc add ~/cases/doc.pdf -s echr-2024-001 -l -a
evid set gather echr-2024-001 -o exports/refs.yml
evid -j search vec "separation" -s echr-2024-001
```

Self-contained deliverable (project-local database — preferred for authoring and smoke tests):

```bash
evid -d ./evid set create -s mybrief
evid -d ./evid doc add ~/cases/doc.pdf -s mybrief
evid -d ./evid set gather mybrief -o brief/refs.yml
# → author brief/main.typ with labquote (notat skill), then `typst compile`
```

Run `evid <subcommand> --help` or `evid -j … --help` for current flags. Bare `evid` prints CLI help; `evid gui` opens the GUI.
