# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run tests
uv run pytest -v

# Run tests (headless/CI)
HEADLESS=1 QT_QPA_PLATFORM=offscreen CI=true uv run pytest -v

# Run a single test
uv run pytest tests/test_foo.py::test_bar -v

# Format + lint
ruff format
ruff check --fix

# Install in dev mode
uv pip install -e .[dev]
```

## Architecture

`evid` is a PDF evidence management tool for labeling and citing documents, primarily for legal/research workflows.

**Entry point**: `evid.cli.main` — uses `treeparse` for CLI. If invoked with no subcommand, launches the PySide6 GUI. The `--db` flag is parsed manually before treeparse takes over.

**Core pipeline**:
1. PDFs or text files are added (URL or local path)
2. Stored as `{db_dir}/{dataset}/{uuid}/` with YAML metadata (`info.yml`) and extracted text
3. A `label.typ` Typst file is generated from PDF text (via PyMuPDF/fitz)
4. User labels evidence in the Typst file using `#lab(key, text, note)` syntax
5. `typst query` (subprocess) extracts labels to `label.json`
6. JSON converts to `label.bib` (BibTeX) for citation management
7. A rebuttal document can be generated from collected evidence

**Key modules**:
- `evid.core.database` — YAML-based metadata store; `InfoModel` (Pydantic) validates each document's `info.yml`
- `evid.core.typst_generation` — PDF → Typst file conversion
- `evid.core.bibtex` / `bibtex_utils` — `typst query` orchestration and JSON↔BibTeX conversion
- `evid.core.label` — invokes editor (default: `code`), then triggers BibTeX generation post-edit
- `evid.core.prompt` — concatenates evidence into Markdown for LLM consumption
- `evid.core.rebut_doc` — generates rebuttal Typst documents from BibTeX
- `evid.gui.*` — PySide6 two-tab UI (Add Evidence, Browse Evidence)
- `evid.cli.callbacks` — wires CLI commands to core logic with interactive prompts

**Config**: `~/.evidrc` (YAML) — `default_dir`, `editor`, and other user preferences loaded in `evid/__init__.py`.

**External dependency**: The `typst` binary must be installed and on PATH for label extraction to work.

**Testing**: GUI tests use `QT_QPA_PLATFORM=offscreen` to run headless. Test markers: `slow`, `integration`.
