"""A focused ingest → label → copy labels → exit workflow."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Input, Label, Select, Static

from evid.tui import data

logger = logging.getLogger(__name__)


def _cell(text: str, style: str = "") -> Text:
    return Text(text, style=style, no_wrap=True, overflow="ellipsis")


def _doc_cell(doc: data.DocRow, width: int) -> Text:
    """Keep the author brief, reserving most of the row for the title."""
    title = " ".join(doc.title.split()) or doc.uuid[:8]
    author = " ".join(doc.authors.split())
    if not author:
        return _cell(title)
    prefix = _cell(author, style="dim")
    prefix.truncate(min(12, max(1, (width - 3) // 3)), overflow="ellipsis")
    prefix.append(" — ", style="dim")
    prefix.append(title, style="none")
    return prefix


class PromptModal(ModalScreen):
    """Name a label, or choose a label to remove."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, initial: str, hint: str) -> None:
        super().__init__()
        self._title, self._initial, self._hint = title, initial, hint

    def compose(self) -> ComposeResult:
        with Vertical(id="prompt"):
            yield Label(self._title, classes="prompt-title")
            yield Input(value=self._initial, id="label-key")
            yield Static(self._hint, classes="prompt-hint")
            with Horizontal(classes="buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.dismiss(self.query_one(Input).value.strip())
        else:
            self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(None)


class MainScreen(Screen):
    BINDINGS = [
        Binding("a", "add", "Ingest"),
        Binding("ctrl+l", "label", "Label", priority=True),
        Binding("l", "label", "Label", show=False),
        Binding("alt+up", "step_doc(-1)", "Previous document", show=False),
        Binding("alt+down", "step_doc(1)", "Next document", show=False),
        Binding("c", "copy_labels", "Copy labels"),
        Binding("q", "quit", "Exit"),
        Binding("ctrl+q", "quit", "Exit", show=False, priority=True),
        Binding("ctrl+w", "quit", "Exit", show=False, priority=True),
        Binding("ctrl+c", "quit", "Exit", show=False, priority=True),
        Binding("L", "unlabel", "Remove label", show=False),
        Binding("escape", "focus_docs", "Documents", show=False),
    ]

    def __init__(self, directory: Path, slug: str | None) -> None:
        super().__init__()
        self.directory = directory
        slugs = [s.slug for s in data.list_sets(directory)]
        self.slug = slug or (slugs[0] if slugs else "inbox")
        self._slugs = list(dict.fromkeys([self.slug, *slugs]))
        self._docs: list[data.DocRow] = []
        self._paras: list[data.ParaRow] = []
        self._current_uuid: str | None = None
        self._generation = 0
        self._busy = False
        self._ready = False

    def compose(self) -> ComposeResult:
        yield Static(
            "evid   1 Ingest  →  2 Label  →  3 Copy labels  →  4 Exit", id="steps"
        )
        with Horizontal(id="ingest"):
            yield Select(
                [(s, s) for s in self._slugs],
                value=self.slug,
                allow_blank=False,
                id="sets",
                tooltip="Evidence set",
            )
            yield Input(placeholder="URL, PDF path or folder", id="add")
            yield Button("Ingest", id="ingest-go", variant="primary")
        with Horizontal(id="body"):
            with Vertical(id="docs-pane", classes="pane"):
                yield Static("Documents", id="docs-title", classes="pane-title")
                yield DataTable(id="docs")
            with Vertical(id="label-pane", classes="pane"):
                yield Static("Select a document", id="docinfo", classes="pane-title")
                yield Static("", id="label-title")
                yield DataTable(id="paras")
                with VerticalScroll(id="reader"):
                    yield Static("Ingest a document to start labelling.", id="paratext")
        with Horizontal(id="actions", classes="buttons"):
            yield Button("Label (Ctrl+L)", id="label", variant="primary", disabled=True)
            yield Button("Remove (L)", id="unlabel", disabled=True)
            yield Button("Copy labels (c)", id="copy-labels")
            yield Button("Exit (q)", id="exit")
        yield Static("", id="status", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        docs = self.query_one("#docs", DataTable)
        docs.cursor_type = "row"
        docs.add_column("Document")
        paras = self.query_one("#paras", DataTable)
        paras.cursor_type = "row"
        paras.add_column("¶", width=4)
        paras.add_column("Labels", width=16)
        paras.add_column("Passage")
        self._ready = True
        self.refresh_docs()
        self._status(
            f"Paste a source to ingest. Copy labels exports all saved labels in {self.slug} as YAML."
        )
        if self._docs:
            docs.focus()
        else:
            self.action_add()

    def _status(self, text: str, *, error: bool = False) -> None:
        self.query_one("#status", Static).update(text)
        if error:
            logger.error("%s", text)
            self.notify(text, severity="error", timeout=10)

    def on_resize(self, _event: events.Resize) -> None:
        self._fit_columns()

    def _fit_columns(self) -> None:
        for selector, fixed in (("#docs", ()), ("#paras", (4, 16))):
            table = self.query_one(selector, DataTable)
            columns = table.ordered_columns
            if not columns:
                continue
            rest = max(
                1,
                table.size.width
                - table.cell_padding * 2 * len(columns)
                - sum(fixed)
                - 2,
            )
            for column, width in zip(columns, (*fixed, rest), strict=True):
                column.width, column.auto_width = width, False
            if selector == "#docs":
                for doc in self._docs:
                    cell = _doc_cell(doc, rest)
                    if table.get_cell(doc.uuid, columns[0].key) != cell:
                        table.update_cell(doc.uuid, columns[0].key, cell)
            table.refresh(layout=True)

    def on_select_changed(self, event: Select.Changed) -> None:
        if not self._ready or event.value == self.slug or event.value is Select.BLANK:
            return
        self.slug = str(event.value)
        self.refresh_docs()
        self._status(f"Copy labels exports all saved labels in {self.slug} as YAML.")

    def refresh_docs(self, selected: str | None = None) -> None:
        self._docs = data.list_docs(self.directory, self.slug)
        table = self.query_one("#docs", DataTable)
        with table.prevent(DataTable.RowHighlighted):
            table.clear()
            for doc in self._docs:
                table.add_row(_doc_cell(doc, table.size.width - 4), key=doc.uuid)
            uuids = [doc.uuid for doc in self._docs]
            chosen = selected or self._current_uuid
            row = uuids.index(chosen) if chosen in uuids else 0
            if uuids:
                table.move_cursor(row=row)
        self.query_one("#docs-title", Static).update(f"Documents · {len(self._docs)}")
        self._select_doc(uuids[row] if uuids else "")
        self.call_after_refresh(self._fit_columns)

    def _current_doc(self) -> data.DocRow | None:
        return next((d for d in self._docs if d.uuid == self._current_uuid), None)

    def _select_doc(self, uuid: str) -> None:
        self._current_uuid = uuid or None
        self._generation += 1
        self._paras = []
        self.query_one("#paras", DataTable).clear()
        doc = self._current_doc()
        self.query_one("#docinfo", Static).update(
            _cell(doc.title if doc else "No documents yet")
        )
        self.query_one("#label-title", Static).update("Reading text…" if doc else "")
        self.query_one("#paratext", Static).update(
            "Reading text…"
            if doc
            else "Paste a URL, PDF path or folder above, then press Enter."
        )
        self._update_actions()
        if doc:
            self._load_paras(doc.dir, self._generation, None)

    @work(thread=True, group="paras", exclusive=True)
    def _load_paras(self, doc_dir: Path, generation: int, start: int | None) -> None:
        try:
            rows = data.list_paragraphs(doc_dir)
        except Exception as exc:
            logger.exception("Could not read paragraphs")
            self.app.call_from_thread(self._show_paras, generation, [], start, str(exc))
            return
        self.app.call_from_thread(self._show_paras, generation, rows, start, "")

    def _show_paras(
        self, generation: int, rows: list[data.ParaRow], start: int | None, error: str
    ) -> None:
        if generation != self._generation:
            return
        self._paras = rows
        table = self.query_one("#paras", DataTable)
        with table.prevent(DataTable.RowHighlighted):
            table.clear()
            for para in rows:
                table.add_row(
                    _cell(str(para.number)),
                    _cell(", ".join(para.keys), "bold"),
                    _cell(" ".join(para.text.split())),
                    key=str(para.start),
                )
            if rows:
                row = next((i for i, p in enumerate(rows) if p.start == start), 0)
                table.move_cursor(row=row)
        labelled = sum(bool(p.keys) for p in rows)
        self.query_one("#label-title", Static).update(
            f"{len(rows)} paragraphs · {labelled} labelled · Ctrl+L to label"
            if rows
            else "No readable paragraphs"
        )
        self._draw_para_text()
        self.call_after_refresh(self._fit_columns)
        if error:
            self._status(f"Could not read document: {error}", error=True)

    def _current_para(self) -> data.ParaRow | None:
        row = self.query_one("#paras", DataTable).cursor_row
        return self._paras[row] if 0 <= row < len(self._paras) else None

    def _draw_para_text(self) -> None:
        para = self._current_para()
        text = Text("No readable text. Choose another document or ingest a text PDF.")
        if para:
            head = f"¶{para.number}"
            if para.page is not None:
                head += f" · page {para.page}"
            if para.keys:
                head += " · " + ", ".join(para.keys)
            text = Text(head + "\n", style="bold")
            text.append(para.text, style="none")
        self.query_one("#paratext", Static).update(text)
        self.query_one("#reader", VerticalScroll).scroll_home(animate=False)
        self._update_actions()

    def _update_actions(self) -> None:
        para = self._current_para()
        self.query_one("#label", Button).disabled = self._busy or para is None
        self.query_one("#unlabel", Button).disabled = self._busy or not (
            para and para.keys
        )
        self.query_one("#copy-labels", Button).disabled = self._busy or not self._docs

    def action_label(self) -> None:
        doc, para = self._current_doc(), self._current_para()
        if self._busy or doc is None or para is None:
            return
        self.app.push_screen(
            PromptModal(
                f"Label paragraph {para.number}",
                data.suggest_key(doc.dir, para.text),
                "Enter saves immediately · Esc cancels",
            ),
            lambda key: self._save_label(doc, para, key),
        )

    def _save_label(
        self,
        doc: data.DocRow,
        para: data.ParaRow,
        key: str | None,
        *,
        remove: bool = False,
    ) -> None:
        if not key:
            return
        try:
            ok, msg = (
                data.unlabel(doc.dir, key)
                if remove
                else data.label_paragraph(doc.dir, para.start, para.end, key)
            )
        except Exception as exc:
            self._status(f"Could not save label: {exc}", error=True)
            return
        self._status(
            msg
            if not ok
            else f"{msg} Continue labelling, or press c to copy labels from {self.slug}.",
            error=not ok,
        )
        if ok:
            self._generation += 1
            self._load_paras(doc.dir, self._generation, para.start)
            self.query_one("#paras", DataTable).focus()

    def action_unlabel(self) -> None:
        doc, para = self._current_doc(), self._current_para()
        if self._busy or doc is None or para is None or not para.keys:
            return
        self.app.push_screen(
            PromptModal(
                "Remove label",
                para.keys[0],
                "Keys on this paragraph: " + ", ".join(para.keys),
            ),
            lambda key: self._save_label(doc, para, key, remove=True),
        )

    def action_add(self) -> None:
        if not self._busy:
            self.query_one("#add", Input).focus()

    def action_focus_docs(self) -> None:
        self.query_one("#docs", DataTable).focus()

    def action_step_doc(self, direction: int) -> None:
        """Match Tauri's Alt+arrows: clamp at the ends and retain focus."""
        if self._busy or not self._docs:
            return
        index = next(
            (i for i, doc in enumerate(self._docs) if doc.uuid == self._current_uuid),
            -1,
        )
        row = max(0, min(len(self._docs) - 1, index + direction))
        uuid = self._docs[row].uuid
        if uuid == self._current_uuid:
            return
        self.query_one("#docs", DataTable).move_cursor(row=row)
        self._select_doc(uuid)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if not self._ready:
            return
        if (
            event.data_table.id == "docs"
            and str(event.row_key.value) != self._current_uuid
        ):
            self._select_doc(str(event.row_key.value))
        elif event.data_table.id == "paras":
            self._draw_para_text()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "docs":
            self.query_one("#paras", DataTable).focus()
        elif event.data_table.id == "paras":
            self.action_label()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "ingest-go": self._ingest,
            "label": self.action_label,
            "unlabel": self.action_unlabel,
            "copy-labels": self.action_copy_labels,
            "exit": self.action_quit,
        }
        action = actions.get(event.button.id)
        if action:
            action()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "add":
            self._ingest()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.query_one("#add", Input).disabled = busy
        self.query_one("#ingest-go", Button).disabled = busy
        self.query_one("#sets", Select).disabled = busy
        self._update_actions()

    def _ingest(self) -> None:
        source = self.query_one("#add", Input).value.strip()
        if self._busy or not source:
            return
        self._set_busy(True)
        self._status(f"Ingesting into {self.slug}…")
        self._ingest_worker(source, self.slug)

    @work(thread=True, group="ingest")
    def _ingest_worker(self, source: str, slug: str) -> None:
        try:
            results = data.run_add(self.directory, slug, [source], do_index=False)
        except Exception as exc:
            logger.exception("Ingest failed")
            results = [data.AddResult(source, False, str(exc))]
        self.app.call_from_thread(self._ingested, results)

    def _ingested(self, results: list[data.AddResult]) -> None:
        self._set_busy(False)
        added = [r for r in results if r.ok]
        errors = [f"{r.source}: {r.message}" for r in results if not r.ok]
        self.refresh_docs(added[0].uuid if added else None)
        if added:
            self.query_one("#paras", DataTable).focus()
        else:
            self.action_add()
        if errors:
            self._status(
                f"Ingested {len(added)}/{len(results)}. " + "\n".join(errors),
                error=True,
            )
        elif added:
            self.query_one("#add", Input).value = ""
            self._status(
                f"Ready to label · {len(added)} document(s). Choose a paragraph and press Ctrl+L."
            )
        else:
            self._status(
                "No documents found. Try a PDF path, URL or folder.", error=True
            )

    def action_copy_labels(self) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._status(f"Preparing labels from {self.slug}…")
        self._copy_worker(self.slug)

    @work(thread=True, group="copy")
    def _copy_worker(self, slug: str) -> None:
        try:
            text = data.export_labels(self.directory, slug)
        except Exception as exc:
            logger.exception("Could not export labels")
            self.app.call_from_thread(self._copied, "", str(exc))
            return
        self.app.call_from_thread(self._copied, text, "")

    def _copied(self, text: str, error: str) -> None:
        self._set_busy(False)
        if error:
            self._status(f"Could not copy labels: {error}", error=True)
        elif not text:
            self._status(
                "No saved labels yet. Select a paragraph and press Ctrl+L to label it."
            )
        else:
            self.app.copy_to_clipboard(text)
            self._status(
                f"Labels from {self.slug} sent to the terminal clipboard as YAML. Press q to exit."
            )
        self.query_one("#paras", DataTable).focus()

    def action_quit(self) -> None:
        if self._busy:
            self._status("Please wait for the current operation to finish, then exit.")
            return
        self.app.exit()


class TUIApp(App):
    TITLE = "evid"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    #steps { height: 1; padding: 0 1; text-style: bold; background: $boost; }
    #ingest { height: 3; margin: 0 1; }
    #sets { width: 22; margin-right: 1; }
    #add { width: 1fr; }
    #ingest-go { margin-left: 1; min-width: 10; }
    #body { height: 1fr; }
    .pane { border: round $border; }
    #docs-pane { width: 28%; min-width: 18; margin-left: 1; }
    #label-pane { width: 1fr; margin: 0 1; }
    .pane-title { height: 1; padding: 0 1; text-style: bold; background: $boost; }
    #label-title { height: 1; padding: 0 1; color: $text-muted; }
    #docs { height: 1fr; }
    #paras { height: 1fr; min-height: 3; }
    DataTable { overflow-x: hidden; }
    #reader { height: 1fr; min-height: 3; border-top: solid $border; padding: 0 1; }
    #paratext { height: auto; }
    .buttons { height: 3; }
    #actions { margin: 0 1; }
    .buttons Button { margin-right: 1; min-width: 10; }
    #status { height: auto; max-height: 3; overflow-y: auto; padding: 0 1; color: $text-muted; }
    PromptModal { align: center middle; background: $background 70%; }
    #prompt { width: 64; max-width: 95%; height: auto; padding: 1 2; border: round $accent; background: $surface; }
    .prompt-title { text-style: bold; margin-bottom: 1; }
    .prompt-hint { color: $text-muted; margin: 1 0; }
    """

    def __init__(self, directory: Path, set_slug: str | None) -> None:
        super().__init__()
        self.directory, self.set_slug = directory, set_slug

    async def on_mount(self) -> None:
        await self.push_screen(MainScreen(self.directory, self.set_slug))


def run(db: str | None = None, dataset: str | None = None) -> int:
    """Launch the TUI with the CLI's resolved data directory and optional set."""
    if not _is_tty():
        print("evid tui needs an interactive terminal.", file=sys.stderr)
        return 1
    TUIApp(data.resolve_directory(db), dataset).run()
    return 0


def _is_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


if __name__ == "__main__":
    sys.exit(run())
