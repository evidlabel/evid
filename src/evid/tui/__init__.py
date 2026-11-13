"""evid TUI — a keyboard-driven terminal workspace.

The spine of the app is the *quick-addition workflow*: get documents into an
evidence set (paste URLs / PDF paths / directories), then immediately curate
them — tag, annotate, fix metadata, open — all without leaving the terminal.

Everything the TUI does is a thin front-end over the same service layer the
CLI uses (SetManager, DocIngester, update_doc, assign_tag), so behaviour and
data formats match `evid doc …` exactly. curses is used directly (stdlib), so
`evid tui` adds no runtime dependency.
"""

from evid.tui.app import run  # noqa: F401

__all__ = ["run"]
