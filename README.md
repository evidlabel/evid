![CI](https://github.com/evidlabel/evid/actions/workflows/ci.yml/badge.svg)![Version](https://img.shields.io/github/v/release/evidlabel/evid)![License](https://img.shields.io/badge/license-MIT-blue.svg)

# evid

**Aim.** Human and agent collaboration on document sets for legal work: find, quote, and cite from the same store, without either side inventing wording.

**Use.** Ingest PDFs and URLs into an evidence set. Search (semantic, metadata, full text). Make spans citable — by hand in Typst (`#lab`) or by machine (`evid doc quote`). Gather BibTeX / Hayagriva / Markdown / JSON. Author the brief elsewhere (Typst / notat), keys only.

**Features.**
- CLI + GUI over one on-disk layout (`sets/<slug>/docs/<uuid>/`)
- Manual labelling in `label.typ`; machine quoting into `machine.hayagriva` (verbatim match, never paraphrase)
- Vector, metadata, and body search; tags; gather for interchange
- MCP server (`evid mcp <set>`) for a warm agent query session

License: [MIT](LICENSE). CLI: `evid -h`. Agents: [`SKILL.md`](SKILL.md).

## Install

Python 3.12+, [uv](https://docs.astral.sh/uv/), [`typst`](https://typst.app) on PATH.

```bash
uv tool install "evid @ git+https://github.com/evidlabel/evid.git"
```

Data dir defaults to `~/.local/share/evid`. For a deliverable, pass `-d ./evid` on every command.

```bash
evid gui
evid -d ./evid set create my-case
evid -d ./evid doc add paper.pdf -s my-case
```

## Development

```bash
uv sync
HEADLESS=1 uv run pytest -v
```
