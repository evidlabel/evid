"""The evid TUI application: screens, event loop, keyboard dispatch.

This is the only module that opens a curses screen. Run it with
``evid tui`` or ``python -m evid.tui`` — everything else in the package is
import-safe and headlessly testable.
"""

from __future__ import annotations

import curses
import locale
import os
import sys
from pathlib import Path

from evid import open_external
from evid.tui import data
from evid.tui import ui


# ── screen layout constants ───────────────────────────────────────────────────

def _run_curses(db: str | None, dataset: str | None) -> int:
    locale.setlocale(locale.LC_ALL, "")
    try:
        return curses.wrapper(_main, db, dataset)
    except KeyboardInterrupt:
        return 0


def _main(screen, db: str | None, dataset: str | None) -> int:
    app = App(screen, db, dataset)
    return app.run()


# ── the application ───────────────────────────────────────────────────────────

class App:
    def __init__(self, screen, db: str | None, dataset: str | None):
        self.scr = screen
        self.db = db
        self.directory = data.resolve_directory(db)
        self.set_slug = dataset
        self.sets = data.list_sets(self.directory)
        self.docs: list[data.DocRow] = []
        self.filter = ""
        self.focus = "list"  # 'list' | 'detail'
        self.detail_scroll = 0
        self.detail_lines: list[tuple[str, int]] = []  # (text, attr)
        self.status = "evid TUI · type ? for help"
        self.sel_uuid: str | None = None
        self.pending: list[data.AddResult] = []

    # ── lifecycle ────────────────────────────────────────────────────────
    def run(self) -> int:
        ui.init_theme()
        curses.curs_set(2)  # visible block cursor in input fields
        try:
            if not self.sets:
                self._create_first_set()
            if self.set_slug is None:
                chosen = self._pick_set()
                if chosen is None:
                    return 0
                self.set_slug = chosen
            use_slug = self.set_slug

            # re-check: the set may not exist in this directory
            if use_slug not in {s.slug for s in self.sets}:
                self.status = f"Set '{use_slug}' not found — creating it."
                try:
                    from evid.cli.dataset import create_dataset

                    create_dataset(self.directory, use_slug)
                    self.sets = data.list_sets(self.directory)
                    self.set_slug = use_slug
                except SystemExit as e:
                    self.status = f"Could not create set: {e}"
                    return 1

            self._refresh()
            return self._loop()
        finally:
            # curses.wrapper owns endwin/cleanup; keep this module's side
            # effects to a single clear exit so wrapper does not re-call it.
            pass

    def _loop(self) -> int:
        while True:
            self._draw()
            key = ui._getch(self.scr)
            if key is None:
                continue
            if key in ("q",) or (isinstance(key, str) and key == "\x03"):
                return 0
            self._handle(key)

    # ── data refresh ─────────────────────────────────────────────────────
    def _refresh(self) -> None:
        self._link_list()
        if self.set_slug:
            self.docs = data.list_docs(self.directory, self.set_slug)
            self.list.items = self.docs
            if self.pending:
                first = self.pending[-1].uuid or None
                if first:
                    idx = next(
                        (i for i, d in enumerate(self.docs) if d.uuid.startswith(first[:8])),
                        self.list.index,
                    )
                    self.list.index = idx
        else:
            self.docs = []
            self.list.items = []

    def _link_list(self) -> None:
        self.list = ui.List(self.docs if hasattr(self, "docs") else [])
        self.list.filter = self.filter
        self.list.on_activate = lambda item: self._open_doc(item)

    # ── drawing ──────────────────────────────────────────────────────────
    def _draw(self) -> None:
        my, mx = self.scr.getmaxyx()
        h = my - 2  # title + status bar
        if h < 4 or mx < 40:
            msg = "Terminal too small — resize (need ~40x8)."
            self.scr.erase()
            ui.put(self.scr, 0, 0, msg, ui.attr(ui.WARN))
            self.scr.refresh()
            return

        self._draw_title(mx)
        self._draw_body(h, mx)
        self._draw_statusbar(h + 1, mx)

    def _draw_title(self, mx: int) -> None:
        name = self.set_slug or "—"
        left = f"evid · {name} › {len(self.docs)} doc(s)"
        right = "a add · t tag · n note · m meta · o open · ? help"
        line = left + " " * max(1, mx - len(left) - len(right) - 2) + right
        ui.put(self.scr, 0, 0, ui.clip(line, mx), ui.attr(ui.TITLE))

    def _draw_body(self, h: int, mx: int) -> None:
        list_w = max(24, int(mx * 0.58))
        detail_w = mx - list_w - 1

        # filter line
        if self.filter:
            fl = "/ " + self.filter
            ui.put(self.scr, 1, 0, ui.clip(fl, list_w), ui.attr(ui.ACCENT))
        else:
            ui.put(self.scr, 1, 0, ui.clip("filter: /", list_w), ui.attr(ui.DIM))
        ui.put(self.scr, 1, list_w, ui.pad_to("", detail_w), 0)

        body_top = 2
        list_rows = h - body_top

        # left: document list
        self.list.draw(self.scr, body_top, 0, list_rows, list_w, render=self._row)

        # right: detail
        dx = list_w + 1
        cur = self.list.current()
        self._draw_detail(cur, body_top, list_rows, detail_w, dx)

    def _row(self, item: data.DocRow) -> str:
        marker = "▪" if item.uuid == self.sel_uuid else ("▸" if item is self.list.current() else " ")
        title = ui.clip(item.title or item.uuid[:8], 34)
        tags = " ".join("#" + t for t in item.tags[:3])
        tags = ui.clip(tags, 16)
        date = ui.clip(item.time_added[:10], 10)
        return f"{marker} {ui.pad_to(title, 34)} {ui.pad_to(tags, 18)} {date}"

    def _draw_detail(self, doc: data.DocRow | None, top: int, rows: int, w: int, x: int) -> None:
        # recompute text for a fresh view (respects scroll)
        lines: list[tuple[str, int]] = []
        if doc is None:
            lines = [("(no document selected)", ui.attr(ui.DIM))]
        else:
            lines = self._detail_lines(doc, w)
        total = len(lines)
        view = lines[self.detail_scroll : self.detail_scroll + rows]
        for i, (text, attrs) in enumerate(view):
            ui.put(self.scr, top + i, x, ui.clip(text, w), attrs)
        # pad the rest
        for i in range(len(view), rows):
            ui.put(self.scr, top + i, x, "", 0)

    def _detail_lines(self, doc: data.DocRow, w: int) -> list[tuple[str, int]]:
        dim = ui.attr(ui.DIM)
        ok = ui.attr(ui.OK)
        hl = ui.attr(ui.HEAD)
        lines: list[tuple[str, int]] = [("Details", hl)]
        for label, val in (
            ("title", doc.title),
            ("authors", doc.authors),
            ("dates", doc.dates),
            ("url", doc.url),
            ("added", doc.time_added),
        ):
            lines += self._kv(label, val, w, dim, ok)
        if doc.tags:
            lines.append(("tags", dim))
            lines.extend((f"  #{t}", ok) for t in doc.tags)
        if doc.note:
            lines.append(("note", dim))
            lines.extend((f"  {z}", ui.attr(ui.DEFAULT)) for z in _wrap(doc.note, w - 4))
        lines.append(("path", dim))
        lines.append(("  " + str(doc.dir), ui.attr(ui.DEFAULT)))
        return lines

    def _kv(self, label: str, value: str, w: int, dim: int, ok: int) -> list[tuple[str, int]]:
        if value:
            return [(label, dim), *(("  " + z, ok) for z in _wrap(value, w - 4))]
        return [(label, dim), ("  —", ui.attr(ui.DIM))]

    def _draw_statusbar(self, y: int, mx: int) -> None:
        left = ui.clip(self.status or "", mx - 30)
        right = "focus: " + self.focus
        line = left + " " * max(1, mx - len(left) - len(right) - 2) + right
        ui.put(self.scr, y, 0, ui.clip(line, mx), ui.attr(ui.DIM))

    # ── key handling ─────────────────────────────────────────────────────
    def _handle(self, key) -> None:
        if isinstance(key, int):
            self._handle_special(key)
            return
        c = str(key)
        if c == "\t":
            self.focus = "detail" if self.focus == "list" else "list"
            return
        self.status = ""
        cmd = self._bindings().get(c)
        if cmd:
            cmd()
            return
        if self.filter:
            self._edit_filter(c)

    def _handle_special(self, k: int) -> None:
        if k == curses.KEY_RESIZE:
            self.scr.erase()
            return
        if k in (curses.KEY_DOWN, 258):
            self._move(1)
        elif k in (curses.KEY_UP, 259):
            self._move(-1)
        elif k in (curses.KEY_NPAGE, 338):
            self._move(10)
        elif k in (curses.KEY_PPAGE, 339):
            self._move(-10)
        elif k in (curses.KEY_HOME, 262):
            self._move(-(10**6))
        elif k in (curses.KEY_END, 360):
            self._move(10**6)
        elif k in (curses.KEY_RIGHT, 261):
            if self.focus == "list":
                self._open_doc(self.list.current())
        elif k in (curses.KEY_LEFT, 260):
            pass

    def _bindings(self) -> dict:
        return {
            "a": self.add_dialog,
            "/": self.start_filter,
            "g": lambda: (self.focus == "list" and self._move(-(10**6))),
            "G": lambda: (self.focus == "list" and self._move(10**6)),
            "j": lambda: self._move(1),
            "k": lambda: self._move(-1),
            "t": self.tag_dialog,
            "T": self.untag_dialog,
            "n": self.note_dialog,
            "m": self.meta_dialog,
            "o": lambda: self._open_doc(self.list.current()),
            "\n": lambda: self._open_doc(self.list.current()),
            "\r": lambda: self._open_doc(self.list.current()),
            "s": self.switch_set,
            "r": self._refresh,
            "?": self.help,
            "q": lambda: None,
        }

    def _move(self, delta: int) -> None:
        if self.focus != "list" or not hasattr(self, "list"):
            if delta in (1, -1):
                self._scroll_detail(delta)
            return
        self.list.move(delta)
        cur = self.list.current()
        if cur is not None:
            self.sel_uuid = cur.uuid

    def _scroll_detail(self, delta: int) -> None:
        self.detail_scroll = max(0, self.detail_scroll + delta * 5)

    def _edit_filter(self, c: str) -> None:
        self.filter += c
        self.list.filter = self.filter
        if not self.list._visible():
            self.list.move(0)

    def start_filter(self) -> None:
        prompt = ui.Prompt(self.scr, "Filter", self.filter or "", hint="substring to match titles/tags/authors")
        value, ok = prompt.show()
        if not ok:
            self.filter = ""
        else:
            self.filter = value
        if hasattr(self, "list"):
            self.list.filter = self.filter

    # ── actions ──────────────────────────────────────────────────────────

    def _open_doc(self, doc: data.DocRow | None) -> None:
        if doc is None:
            return
        err = open_external.open_local_path(doc.dir)
        self.status = err or f"Opened {doc.uuid[:8]}"

    def tag_dialog(self) -> None:
        doc = self.list.current()
        if doc is None:
            self.status = "Select a document first."
            return
        known = data.known_tags(self.directory, self.set_slug) if self.set_slug else []
        prompt = ui.Prompt(
            self.scr,
            f"Tag {doc.uuid[:8]}",
            "",
            hint="tag name (Tab: insert last-used)",
        )
        tag, ok = prompt.show(choices=known)
        if not ok or not tag:
            return
        found, msg = data.assign_tag(self.directory, doc.uuid, tag)
        self.status = msg
        self._refresh()

    def untag_dialog(self) -> None:
        doc = self.list.current()
        if doc is None:
            return
        if not doc.tags:
            self.status = "This document has no tags."
            return
        prompt = ui.Prompt(
            self.scr, f"Untag {doc.uuid[:8]}", "",
            hint="tag to remove (Tab: pick from this doc)",
        )
        tag, ok = prompt.show(choices=doc.tags)
        if not ok or not tag:
            return
        found, msg = data.remove_tag(self.directory, doc.uuid, tag)
        self.status = msg
        self._refresh()

    def note_dialog(self) -> None:
        doc = self.list.current()
        if doc is None:
            return
        initial = doc.note
        prompt = ui.Prompt(self.scr, f"Note {doc.uuid[:8]}", initial)
        text, ok = prompt.show()
        if not ok:
            return
        found, msg = data.set_note(self.directory, doc.uuid, text)
        self.status = msg
        self._refresh()

    def meta_dialog(self) -> None:
        doc = self.list.current()
        if doc is None:
            return
        fields = [
            ("title", doc.title),
            ("authors", doc.authors),
            ("dates", doc.dates),
            ("url", doc.url),
        ]
        title, ok = ui.Prompt(
            self.scr, f"Metadata {doc.uuid[:8]} — title (Enter=next, Esc=skip)", doc.title
        ).show()
        if not ok:
            return
        data.update_metadata(self.directory, doc.uuid, {"title": title})
        for name, current in fields[1:]:
            val, ok = ui.Prompt(self.scr, f"{name} (blank to keep, Esc=stop)", current).show()
            if not ok:
                break
            if val != current:
                data.update_metadata(self.directory, doc.uuid, {name: val})
        self.status = "Metadata updated"
        self._refresh()

    def add_dialog(self) -> None:
        dialog = ui.AddDialog(self.scr, self.directory, self.set_slug or "")
        results = dialog.show()
        if not results:
            return
        self.pending = results
        self.status = f"Added {sum(r.ok for r in results)} / {len(results)}"
        self._refresh()

    def switch_set(self) -> None:
        choice = self._pick_set(allow_create=False)
        if choice:
            self.set_slug = choice
            self.sel_uuid = None
            self.pending = []
            self._refresh()

    def help(self) -> None:
        ui.help_overlay(self.scr)

    # ── set picker ───────────────────────────────────────────────────────
    def _pick_set(self, allow_create: bool = True) -> str | None:
        sets = self.sets or data.list_sets(self.directory)
        if not sets and allow_create:
            return self._create_first_set()
        pick = ui.SetPicker(self.scr, sets, self.directory, allow_create=allow_create)
        return pick.show()

    def _create_first_set(self) -> str | None:
        pick = ui.SetPicker(self.scr, [], self.directory, allow_create=True, empty=True)
        return pick.show()


# ── text wrapping ────────────────────────────────────────────────────────────

def _wrap(text: str, width: int) -> list[str]:
    """Greedy word-wrap to *width* cells, preserving long tokens."""
    if width <= 1:
        return [text]
    out: list[str] = []
    cur = ""
    for word in text.split():
        if ui.text_width(cur) + 1 + ui.text_width(word) <= width:
            cur = (cur + " " + word).strip()
        else:
            if cur:
                out.append(cur)
            # hard-break overlong single tokens
            while ui.text_width(word) > width:
                out.append(ui.clip(word[:-1], width - 1))
                word = word[ui.text_width(word) - width + 1 :]
            cur = word
    if cur:
        out.append(cur)
    return out


# ── entry point ──────────────────────────────────────────────────────────────

def run(db: str | None = None, dataset: str | None = None) -> int:
    """Launch the TUI. *db* is the data directory; *dataset* an optional slug."""
    if not sys.stdin or not _is_tty():
        print("evid tui needs an interactive terminal.", file=sys.stderr)
        return 1
    return _run_curses(db, dataset)


def _is_tty() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


if __name__ == "__main__":
    sys.exit(run())
