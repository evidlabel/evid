---
name: evid
description: Use when installing or using evid — ingest PDFs/URLs into evidence sets, label citable snippets, tag, search, gather exports, or author a memo/brief/notat from a set.
---

# evid

CLI + GUI: ingest → searchable sets → `#lab` / pass → gather → author (Typst via **notat**, keys only).

Discover flags from the installed CLI: `evid -h`, `evid <path> -h`, `evid -j`. After install or upgrade, rediscover — invoke from that output.

## Invariants

- Deliverables: `-d ./evid` on every command. Global db is the standing collection only.
- Citable = verbatim `#lab` or `evid doc quote`. Never retype. Print keys only.
- `set gather` is interchange, not the document. Author with notat.
- Tag writes both `info.yml` and `tags.yml`.

## Loop

`doc add` (keep the index) → `search vec` → `#lab` / quote → `set gather` → notat.

Install: `uv tool install "evid @ git+https://github.com/evidlabel/evid.git"` (Python ≥ 3.12, `typst` on PATH).
