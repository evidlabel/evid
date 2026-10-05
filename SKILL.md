---
name: evid
description: Use when installing or using evid — create a case's evidence set, ingest PDFs/URLs, run analysis passes on a doc, label citable snippets, tag, search, or gather Hayagriva exports.
---

# evid

Evidence sets on disk: ingest → searchable set → analysis pass / `#lab` → gather to Hayagriva.

## Discover

The CLI documents itself. Load only the slice you need:

- `evid --db evid -h` — command tree
- `evid --db evid <path> -h` — one command (e.g. `evid --db evid doc quote -h`)
- `evid -j` — machine-readable schema

Rediscover after install or upgrade, and invoke from that output.

## Rules

- Every command is `evid --db evid …`, run from the case root. Bare `evid` writes to `~/.local/share/evid`; that set never joins the case.
- First call: `evid --db evid set create --dataset <slug>`. Without `--dataset` it prompts for a name and hangs. Confirm `evid/sets/<slug>/` exists before reporting the set created.
- Track the case in Git. Commit `evid/` with each milestone. Keep credentials and identity maps out; add them to `.gitignore` before the first commit.
- Citable = verbatim `#lab` or `evid --db evid doc quote`. Never retype. Print keys only.
- `set gather` output is interchange, not the authored document.
- Tagging writes both `info.yml` and `tags.yml`.

## Analysis passes

A **pass** is a named job on one doc. Passes accumulate under `machine/` beside the document — the standing analysis of that doc, not a chat byproduct. `doc passes` lists the ledger; `doc quote` records the next pass. Hayagriva holds the verbatim cites; the pass is the job history (not citable). Read existing passes before running another.

`doc quote --from` takes candidates from **that** uuid's own text. Write the candidate JSON in that doc's `machine/` as a **new file each pass**: `machine/from-<YYYY-MM-DDTHH-MM-SSZ>-<slug>.json`. Never `/tmp`. Never reuse `quotes.json`. evid records the pass as `machine/<YYYY-MM-DDTHH-MM-SSZ>_<hex>.json`. Replay with `--from machine/<pass>.json`. `--from-search` seeds from the set. `matched: false` → new candidate from that doc, quote again. Hayagriva is tool output.

A candidate is one span on one page of that uuid's text. A folio (standalone page number) in the matched `title:` means the span crossed a page break: `matched` is not enough. Pass again with a page-local span.

## Install

`uv tool install "evid @ git+https://github.com/evidlabel/evid.git"` (CLI + MCP; Python ≥ 3.12; `typst` on PATH for label and gather). Extra: `evid[vec]` (vector search). `evid gui` opens the GUI (evid-app window, else the browser).

## Done

- `evid/sets/<slug>/` exists in the case root.
- Every command in the run carried `--db evid`.
- Changes committed; credentials and identity maps not in Git.
