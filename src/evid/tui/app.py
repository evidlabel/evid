"""The evid TUI — a keyboard-driven terminal workspace, built on Textual.

The spine of the app is the *quick-addition workflow*: get documents into an
evidence set (paste URLs / PDF paths / directories), then immediately curate
them — tag, annotate, fix metadata, open — all without leaving the terminal.

This module is the Textual front-end only. All data loading and mutation lives
in :mod:`evid.tui.data` (curses- and TUI-free, reused by the tests); the TUI
never keeps a write path of its own, so behaviour matches the CLI exactly.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Static,
    TextArea,
)

from evid import open_external
from evid.models import EvidenceSet
from evid.tui import data


def _tags(doc: data.DocRow) -> str:
    return "  ".join(f"#{t}" for t in doc.tags)


# ── modal: simple value prompt ────────────────────────────────────────────────

class PromptModal(ModalScreen):
    """Single-line text prompt; ``dismiss(value)`` or ``dismiss(None)``."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "submit", "OK"),
        Binding("tab", "pick", "pick", show=False),
    ]

    def __init__(
        self,
        title: str,
        initial: str = "",
        hint: str = "",
        choices: Sequence[str] = (),
    ) -> None:
        super().__init__()
        self._title = title
        self._initial = initial
        self._hint = hint
        self._choices = list(choices)
        self._choice_idx = 0

    def compose(self) -> ComposeResult:
        yield Label(self._title, classes="prompt-title")
        yield Input(value=self._initial, placeholder=self._hint, classes="prompt-input")
        if self._choices:
            yield Label("Tab: " + ", ".join(self._choices[:4]), classes="prompt-hint")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_submit()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        self.dismiss(self.query_one(Input).value)

    def action_pick(self) -> None:
        if self._choices:
            self._choice_idx = (self._choice_idx + 1) % len(self._choices)
            self.query_one(Input).value = self._choices[self._choice_idx]


# ── modal: metadata editor ────────────────────────────────────────────────────

class MetaModal(ModalScreen):
    """Edit title / authors / dates / url for one document."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    def __init__(self, doc: data.DocRow) -> None:
        super().__init__()
        self._doc = doc
        self._fields = (("title", doc.title), ("authors", doc.authors), ("dates", doc.dates), ("url", doc.url))

    def compose(self) -> ComposeResult:
        yield Label(f"Metadata — {self._doc.uuid[:8]}", classes="prompt-title")
        for name, value in self._fields:
            yield Label(name, classes="prompt-hint")
            yield Input(value=str(value), id=f"meta-{name}", classes="prompt-input")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "meta-save":
            self.action_save()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        out: dict[str, str] = {}
        for name, _orig in self._fields:
            val = self.query_one(f"#meta-{name}", Input).value.strip()
            if val:
                out[name] = val
        self.dismiss(out)


# ── modal: quick add ──────────────────────────────────────────────────────────

class AddModal(ModalScreen):
    """Batch quick-add: paste sources, set toggles, stream results."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "go", "Add"),
        Binding("l", "toggle_label", "label", show=False),
        Binding("i", "toggle_index", "index", show=False),
    ]

    def __init__(self, directory: Path, slug: str) -> None:
        super().__init__()
        self.directory = directory
        self.slug = slug
        self.autolabel = False
        self.do_index = data.index_default()

    def compose(self) -> ComposeResult:
        yield Label(f"Add to {self.slug} — paste URLs / PDF paths (one per line)", classes="prompt-title")
        yield TextArea("", classes="add-text")
        yield Static("", id="add-toggles", classes="prompt-hint")
        yield RichLog(id="add-log", highlight=True, markup=True, wrap=True)
        with Horizontal(classes="add-buttons"):
            yield Button("Add", variant="primary", id="add-go")
            yield Button("Cancel", variant="default", id="add-cancel")

    def on_mount(self) -> None:
        self.query_one(TextArea).focus()
        self._draw_toggles()

    def _draw_toggles(self) -> None:
        label = "on" if self.autolabel else "off"
        index = "ON" if self.do_index else "OFF"
        self.query_one("#add-toggles", Static).update(
            f"index: {index}  (i)   ·   autolabel: {label}  (l)    —  Enter = add · Esc = cancel"
        )

    def action_toggle_label(self) -> None:
        self.autolabel = not self.autolabel
        self._draw_toggles()

    def action_toggle_index(self) -> None:
        self.do_index = not self.do_index
        self._draw_toggles()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-cancel":
            self.action_cancel()
        elif event.button.id == "add-go":
            self.action_go()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_go(self) -> None:
        sources = [s.strip() for s in self.query_one(TextArea).text.splitlines() if s.strip()]
        if not sources:
            self.dismiss(None)
            return
        self.query_one("#add-go", Button).disabled = True
        self.query_one(RichLog).write("[dim]Adding…[/dim]")
        self.add_worker(sources)

    @work(thread=True, group="add", exclusive=True)
    def add_worker(self, sources: list[str]) -> None:
        def on_progress(res: data.AddResult) -> None:
            self.call_from_thread(self._post, res)

        try:
            results = data.run_add(
                self.directory,
                self.slug,
                sources,
                do_index=self.do_index,
                autolabel=self.autolabel,
                on_progress=on_progress,
            )
        except Exception as exc:  # pragma: no cover - defensive
            self.call_from_thread(self._fail, str(exc))
            return
        self.call_from_thread(self._finish, results)

    def _post(self, res: data.AddResult) -> None:
        mark = "[green]✓[/green]" if res.ok else "[red]✗[/red]"
        line = f"{mark} {res.source}"
        if not res.ok and res.message:
            line += f"  [dim]{res.message}[/dim]"
        self.query_one(RichLog).write(line)

    def _fail(self, message: str) -> None:
        self.query_one(RichLog).write(f"[red]Failed: {message}[/red]")
        self.query_one("#add-go", Button).disabled = False

    def _finish(self, results: list[data.AddResult]) -> None:
        ok = sum(1 for r in results if r.ok)
        self.query_one(RichLog).write(f"[b]Added {ok} / {len(results)}[/b]")
        self.dismiss(results)


# ── modal: set picker ─────────────────────────────────────────────────────────

class SetPicker(ModalScreen):
    """Choose (or create) the active evidence set; ``dismiss(slug)``."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("c", "create", "create", show=False),
    ]

    def __init__(self, sets: Sequence[EvidenceSet], directory: Path) -> None:
        super().__init__()
        self._sets = list(sets)
        self.directory = directory

    def compose(self) -> ComposeResult:
        yield Label("Select an evidence set — [dim]enter open · c create · esc back[/dim]", classes="prompt-title")
        yield DataTable(id="set-table")

    def on_mount(self) -> None:
        table = self.query_one("#set-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Slug", "Type", "Name")
        for s in self._sets:
            table.add_row(s.slug, s.set_type.value, s.name or "", key=s.slug)
        if self._sets:
            table.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_create(self) -> None:
        def _name(val) -> None:
            if not val:
                return
            try:
                from evid.cli.dataset import create_dataset

                slug = create_dataset(self.directory, str(val).strip(), "normal")
            except SystemExit as e:
                self.notify(str(e), severity="error")
                return
            self.dismiss(slug)

        self.push_screen(PromptModal("New set name", hint="name → slug"), _name)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.dismiss(str(event.row_key.value))


# ── modal: help ───────────────────────────────────────────────────────────────

class HelpScreen(ModalScreen):
    BINDINGS = [Binding("escape,enter,space,q", "close", "Close")]

    def __init__(self, keys: Sequence[tuple[str, str]]) -> None:
        super().__init__()
        self._keys = list(keys)

    def compose(self) -> ComposeResult:
        yield Label("evid TUI — keys", classes="prompt-title")
        for k, desc in self._keys:
            yield Label(f"[b]{k}[/b]  {desc}", markup=True)
        yield Label("press any key to close", classes="prompt-hint")

    def action_close(self) -> None:
        self.dismiss(None)


# ── main workspace screen ─────────────────────────────────────────────────────

class MainScreen(Screen):
    """Document list + detail pane; quick-add and curation actions."""

    BINDINGS = [
        Binding("a", "add", "add"),
        Binding("slash", "filter", "filter", show=False),
        Binding("t", "tag", "tag"),
        Binding("T", "untag", "untag"),
        Binding("n", "note", "note"),
        Binding("m", "meta", "meta"),
        Binding("o", "open", "open"),
        Binding("s", "switch", "switch set"),
        Binding("r", "refresh", "refresh", show=False),
        Binding("?", "help", "help", show=False),
        Binding("j", "down", "down", show=False),
        Binding("k", "up", "up", show=False),
        Binding("q", "quit", "quit"),
        Binding("ctrl+c", "quit", "quit", show=False),
    ]

    def __init__(self, directory: Path, slug: str) -> None:
        super().__init__()
        self.directory = directory
        self.slug = slug
        self._current_uuid: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Input(placeholder="filter (/) …", id="filter")
        with Horizontal():
            yield DataTable(id="docs")
            yield VerticalScroll(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#docs", DataTable)
        table.cursor_type = "row"
        table.add_columns("Title", "Tags", "Added")
        self.refresh_docs()
        table.focus()

    # ── data / list ───────────────────────────────────────────────────
    def _table(self) -> DataTable:
        return self.query_one("#docs", DataTable)

    def refresh_docs(self) -> None:
        docs = data.list_docs(self.directory, self.slug)
        wanted = len(docs)
        table = self._table()
        table.clear()
        filt = self.query_one("#filter", Input).value.strip().lower()
        shown = 0
        for d in docs:
            if filt and filt not in f"{d.title} {_tags(d)} {d.authors}".lower():
                continue
            table.add_row(d.title or d.uuid[:8], _tags(d), d.time_added[:10], key=d.uuid)
            shown += 1
        self.sub_title = f"{self.slug} · {shown}/{wanted} doc(s)"
        if shown:
            table.move_cursor(row=0)
        else:
            self._current_uuid = None
            self._draw_detail(None)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self.refresh_docs()

    def _current_doc(self) -> data.DocRow | None:
        if not self._current_uuid:
            return None
        for d in data.list_docs(self.directory, self.slug):
            if d.uuid == self._current_uuid:
                return d
        return None

    # ── detail ─────────────────────────────────────────────────────────
    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None:
            self._current_uuid = str(event.row_key.value)
        self._draw_detail(self._current_uuid)

    def _draw_detail(self, uuid: str | None) -> None:
        pane = self.query_one("#detail", VerticalScroll)
        pane.remove_children()
        if uuid is None:
            pane.mount(Label("(no document selected)", classes="prompt-hint"))
            return
        for d in data.list_docs(self.directory, self.slug):
            if d.uuid == uuid:
                self._mount_detail(pane, d)
                return
        pane.mount(Label("(document moved or removed)", classes="prompt-hint"))

    def _mount_detail(self, pane: VerticalScroll, d: data.DocRow) -> None:
        def field(name: str, value: str) -> str:
            if not value:
                return f"[dim]{name}: —[/dim]"
            return f"[b]{name}[/b]: {value.replace(chr(10), ' ')}"

        lines = [
            f"[bold]{d.title or d.uuid[:8]}[/bold]",
            field("authors", d.authors),
            field("dates", d.dates),
            field("url", d.url),
            field("added", d.time_added),
        ]
        if d.tags:
            lines.append("[b]tags[/b]: " + " ".join(f"#{t}" for t in d.tags))
        lines.append(f"[b]uuid[/b]: {d.uuid}")
        lines.append(f"[dim]{d.dir}[/dim]")
        if d.note:
            lines.append("[b]note[/b]: " + d.note.replace(chr(10), " "))
        pane.mount(Static("\n".join(lines), markup=True))

    # ── navigation ─────────────────────────────────────────────────────
    def action_up(self) -> None:
        self._table().action_cursor_up()

    def action_down(self) -> None:
        self._table().action_cursor_down()

    def action_filter(self) -> None:
        self.query_one("#filter").focus()

    # ── curation ───────────────────────────────────────────────────────
    def _push_prompt(self, title: str, initial: str, hint: str, choices=(), cb=None):
        self.app.push_screen(PromptModal(title, initial, hint, choices), cb)

    def action_tag(self) -> None:
        doc = self._current_doc()
        if not doc:
            return
        known = data.known_tags(self.directory, self.slug) if self.slug else []
        self._push_prompt(
            f"Tag {doc.uuid[:8]}", "", "tag name (Tab: last-used)", known,
            lambda v: self._apply_tag(doc.uuid, v),
        )

    def _apply_tag(self, uuid: str, tag) -> None:
        if not tag:
            return
        _ok, msg = data.assign_tag(self.directory, uuid, str(tag))
        self.notify(msg)
        self.refresh_docs()

    def action_untag(self) -> None:
        doc = self._current_doc()
        if not doc:
            return
        if not doc.tags:
            self.notify("This document has no tags.", severity="warning")
            return
        self._push_prompt(
            f"Untag {doc.uuid[:8]}", "", "tag to remove", doc.tags,
            lambda v: self._apply_untag(doc.uuid, v),
        )

    def _apply_untag(self, uuid: str, tag) -> None:
        if not tag:
            return
        _ok, msg = data.remove_tag(self.directory, uuid, str(tag))
        self.notify(msg)
        self.refresh_docs()

    def action_note(self) -> None:
        doc = self._current_doc()
        if not doc:
            return
        self._push_prompt(
            f"Note {doc.uuid[:8]}", doc.note, "note (empty clears; Esc cancels)",
            cb=lambda v: self._apply_note(doc.uuid, v),
        )

    def _apply_note(self, uuid: str, text) -> None:
        if text is None:
            return
        _ok, msg = data.set_note(self.directory, uuid, str(text))
        self.notify(msg)
        self.refresh_docs()

    def action_meta(self) -> None:
        doc = self._current_doc()
        if not doc:
            return
        def _apply(fields) -> None:
            if not fields:
                return
            for name, val in fields.items():
                data.update_metadata(self.directory, doc.uuid, {name: val})
            self.notify("Metadata updated.")
            self.refresh_docs()

        self.app.push_screen(MetaModal(doc), _apply)

    def action_open(self) -> None:
        doc = self._current_doc()
        if not doc:
            return
        err = open_external.open_local_path(doc.dir)
        self.notify(err or f"Opened {doc.uuid[:8]}", severity="error" if err else "information")

    def action_add(self) -> None:
        def _done(results) -> None:
            if results:
                self.notify(f"Added {sum(r.ok for r in results)} / {len(results)} document(s).")
                self.refresh_docs()

        self.app.push_screen(AddModal(self.directory, self.slug), _done)

    def action_switch(self) -> None:
        def _picked(slug) -> None:
            if slug:
                self.slug = slug
                self._current_uuid = None
                self.refresh_docs()

        self.app.push_screen(SetPicker(data.list_sets(self.directory), self.directory), _picked)

    def action_refresh(self) -> None:
        self.refresh_docs()

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen([
            ("a", "add documents (paste URLs / PDF paths)"),
            ("/", "filter the list"),
            ("t / T", "tag / untag the selected document"),
            ("n", "set / edit note"),
            ("m", "edit title / authors / dates / url"),
            ("o / enter", "open the document folder"),
            ("s", "switch evidence set"),
            ("r", "refresh from disk"),
            ("?", "this help"),
            ("q / ctrl+c", "quit"),
        ]))

    def action_quit(self) -> None:
        self.app.exit()


# ── the app ───────────────────────────────────────────────────────────────────

class TUIApp(App):
    """The evid terminal workspace."""

    TITLE = "evid"
    CSS = """
    #filter { dock: top; margin: 0 2 1 2; }
    Horizontal { height: 1fr; }
    #docs { width: 62%; border-right: solid $border; }
    #detail { width: 38%; padding: 1 2; }
    .prompt-title { text-style: bold; padding: 1 2; }
    .prompt-hint { color: $text-muted; padding: 0 2; }
    .prompt-input { margin: 0 2 1 2; }
    .add-text { height: 40%; margin: 0 2; }
    #add-log { height: 30%; margin: 0 2; border: round $border; }
    .add-buttons { margin: 1 2; }
    """

    def __init__(self, directory: Path, set_slug: str | None) -> None:
        super().__init__()
        self.directory = directory
        self.set_slug = set_slug

    async def on_mount(self) -> None:
        if self.set_slug is None:
            await self._start_picker()
        else:
            self._ensure_set(self.set_slug)
            await self.push_screen(MainScreen(self.directory, self.set_slug))

    def _ensure_set(self, slug: str) -> None:
        if slug not in {s.slug for s in data.list_sets(self.directory)}:
            try:
                from evid.cli.dataset import create_dataset

                create_dataset(self.directory, slug)
            except SystemExit:
                pass

    async def _start_picker(self) -> None:
        async def _picked(slug) -> None:
            if slug:
                self.set_slug = slug
                await self.push_screen(MainScreen(self.directory, self.set_slug))
            else:
                self.exit()

        await self.push_screen(SetPicker(data.list_sets(self.directory), self.directory), _picked)


# ── entry point ──────────────────────────────────────────────────────────────

def run(db: str | None = None, dataset: str | None = None) -> int:
    """Launch the TUI. *db* is the data directory; *dataset* an optional slug."""
    if not _is_tty():
        print("evid tui needs an interactive terminal.", file=sys.stderr)
        return 1
    directory = data.resolve_directory(db)
    app = TUIApp(directory, dataset)
    app.run()
    return 0


def _is_tty() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(run())
