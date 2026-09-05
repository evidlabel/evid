---
name: evid
description: Use when installing or using evid — ingest PDFs/URLs into evidence sets, run analysis passes on a doc, label citable snippets, tag, search, gather exports, or author a memo/brief/notat from a set.
---

# evid

CLI + GUI: ingest → searchable sets → analysis pass / `#lab` → gather → author (Typst via **labquote**, keys only).

Discover flags from the installed CLI: `evid -h`, `evid <path> -h`, `evid -j`. After install or upgrade, rediscover — invoke from that output.

## Invariants

- Deliverables: `-d ./evid` on every command. Global db is the standing collection only.
- Citable = verbatim `#lab` or `evid doc quote`. Never retype. Print keys only.
- `set gather` is interchange, not the document. Author with **labquote**. Styles: memo, notat, rebut, walkthrough.
- Tag writes both `info.yml` and `tags.yml`.

## Analysis passes

A **pass** is a named job on one doc. They accumulate under `machine/` beside the document — the standing analysis of that doc, not a chat byproduct. `doc passes` lists the ledger; `doc quote` records the next pass. Hayagriva holds the verbatim cites; the pass is the job history (not citable). Read existing passes before running another.

`doc quote --from` is candidates from **that** uuid's own text — one JSON file per doc. `--from-search` seeds from the set. `matched: false` → new candidate from that doc, quote again. Hayagriva is tool output.

## Loop

`doc add` → `doc passes` → `search text` / `search vec` → `doc quote` / `#lab` → `set gather` → labquote.

Install: `uv tool install "evid @ git+https://github.com/evidlabel/evid.git"` (CLI+MCP; Python ≥ 3.12, `typst` on PATH). Extras: `evid[gui]`, `evid[vec]`, `evid[all]`.
