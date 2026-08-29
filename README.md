# evid

Evidence manager: ingest PDFs/URLs, label `#lab` spans, search, gather BibTeX / Hayagriva.

CLI: `evid -h`. Agent usage: [`SKILL.md`](SKILL.md).

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
