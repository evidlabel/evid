"""Small curses building blocks for the evid TUI.

Kept deliberately thin: a colour theme, width-aware text helpers, a selectable
list, single-multi line editors and modal prompt dialogs. Everything here
assumes the calling code has already called ``curses.initscr()`` and set up
colour via :function:`init_theme`.
"""

from __future__ import annotations

import unicodedata

import curses
from typing import Callable, Generic, Iterable, Protocol, Sequence, TypeVar

_T = TypeVar("_T")

# ── theme ─────────────────────────────────────────────────────────────────────
# pairs (or falls back to monochrome attributes when the terminal has no
# colour), so the rest of the code only ever refers to these names.

DEFAULT = 0
DIM = 1
ACCENT = 2
TITLE = 3
OK = 4
ERR = 5
WARN = 6
HEAD = 7
DIMMED_SEL = 8

_PAIRS: dict[int, tuple[int, int, int]] = {
    # name: (fg, bg, extra_attrs)
    DIM: (curses.COLOR_BLACK, -1, curses.A_NORMAL),
    ACCENT: (curses.COLOR_CYAN, -1, curses.A_BOLD),
    TITLE: (curses.COLOR_WHITE, curses.COLOR_BLUE, curses.A_BOLD),
    OK: (curses.COLOR_GREEN, -1, curses.A_NORMAL),
    ERR: (curses.COLOR_RED, -1, curses.A_BOLD),
    WARN: (curses.COLOR_YELLOW, -1, curses.A_NORMAL),
    HEAD: (curses.COLOR_WHITE, -1, curses.A_BOLD),
    DIMMED_SEL: (curses.COLOR_BLACK, -1, curses.A_BOLD),
}

_MONO: dict[int, int] = {
    DIM: curses.A_DIM,
    ACCENT: curses.A_BOLD | curses.A_REVERSE,
    TITLE: curses.A_REVERSE,
    OK: curses.A_NORMAL,
    ERR: curses.A_BOLD,
    WARN: curses.A_BOLD,
    HEAD: curses.A_BOLD,
    DIMMED_SEL: curses.A_BOLD,
}


def init_theme() -> None:
    """Prepare colour pairs; safe to call once, idempotent."""
    if not curses.has_colors():
        return
    curses.start_color()
    curses.use_default_colors()
    for name, (fg, bg, attrs) in _PAIRS.items():
        if curses.color_pair(name):
            continue
        fg = curses.COLOR_WHITE if fg is None else fg
        try:
            curses.init_pair(name, fg, bg if bg is not None else -1)
        except curses.error:
            pass


def attr(name: int, *, selected: bool = False) -> int:
    """The curses attribute for a semantic *name*."""
    if curses.has_colors():
        base = curses.color_pair(name)
    else:
        base = _MONO.get(name, curses.A_NORMAL)
    if selected:
        base |= curses.A_REVERSE
    return base


# ── width helpers (handles CJK / wide glyphs) ─────────────────────────────────

def text_width(s: str) -> int:
    """Display width of *s* (East-Asian wide chars count as 2 cells)."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def clip(s: str, width: int) -> str:
    """Truncate *s* to *width* display cells, adding an ellipsis when cut."""
    if width <= 0:
        return ""
    if text_width(s) <= width:
        return s
    out: list[str] = []
    w = 0
    for c in s:
        cw = text_width(c)
        if w + cw > width - 1:
            break
        out.append(c)
        w += cw
    return "".join(out) + "…"


def pad_to(s: str, width: int) -> str:
    """Right-pad *s* to *width* display cells (no truncation)."""
    return s + " " * max(0, width - text_width(s))


# ── low-level drawing ─────────────────────────────────────────────────────────

class _Win(Protocol):
    """The tiny slice of a curses window this module relies on."""

    def getmaxyx(self) -> tuple[int, int]: ...

    def addstr(self, y: int, x: int, s: str, attr: int = 0) -> None: ...

    def addnstr(self, y: int, x: int, s: str, n: int, attr: int = 0) -> None: ...

    def move(self, y: int, x: int) -> None: ...

    def hline(self, y: int, x: int, ch: int, n: int) -> None: ...

    def chgat(self, y: int, x: int, num: int, attr: int = 0) -> None: ...

    def box(self) -> None: ...

    def draw(self, *a, **k): ...  # pragma: no cover  # window subclasses define this


def put(win: _Win, y: int, x: int, text: str, attrs: int = 0) -> None:
    """Write *text* at (y,x) with *attrs*, clipped to the window width.

    Uses robust cursor movement so wide/combining characters do not raise.
    """
    try:
        win.chgat(y, x, 0)
    except curses.error:
        return
    maxx = win.getmaxyx()[1]
    avail = max(0, maxx - x)
    if avail <= 0:
        return
    text = clip_to_width(text, avail)
    if not text:
        return
    try:
        win.move(y, x)
        win.addnstr(y, x, text, len(text), attrs)
    except curses.error:
        pass


def clip_to_width(s: str, width: int) -> str:
    return clip(s, width)


def hline(win: _Win, y: int, x: int, width: int, attrs: int = 0) -> None:
    try:
        win.hline(y, x, curses.ACS_HLINE, max(0, width))
        win.chgat(y, x, width, attrs)
    except curses.error:
        pass


def box(win: _Win, title: str = "", accent: bool = False) -> None:
    h, w = win.getmaxyx()
    if h < 2 or w < 2:
        return
    try:
        win.box()
    except curses.error:
        pass
    if title:
        tl = " " + clip(title, max(0, w - 2)) + " "
        try:
            win.addstr(0, 2, tl, attr(HEAD))
        except curses.error:
            pass


# ── List ──────────────────────────────────────────────────────────────────────

class List(Generic[_T]):
    """A vertical, cursor-navigable list over any items via *render*."""

    def __init__(self, items: Sequence[_T]):
        self.items = list(items)
        self.index = 0
        self.offset = 0
        self.filter: str = ""
        self.height = 0
        self.on_activate: Callable[[_T], None] | None = None

    def _visible(self) -> list[_T]:
        if not self.filter:
            return self.items
        f = self.filter.lower()
        return [i for i in self.items if f in _search_text(i).lower()]

    def view(self) -> list[_T]:
        return self._visible()

    def current(self) -> _T | None:
        v = self._visible()
        return v[self.index] if v else None

    def filtered(self) -> bool:
        return bool(self.filter)

    def clamp(self) -> None:
        n = len(self._visible())
        if n == 0:
            self.index = 0
            return
        self.index = max(0, min(self.index, n - 1))
        tall = self.height or n
        if self.index < self.offset:
            self.offset = self.index
        elif self.index >= self.offset + tall:
            self.offset = self.index - tall + 1

    def move(self, delta: int) -> None:
        v = self._visible()
        if not v:
            return
        self.index = max(0, min(self.index + delta, len(v) - 1))
        self.clamp()

    def goto(self, pct: int = 0) -> None:
        v = self._visible()
        if not v:
            return
        self.index = 0 if pct == 0 else len(v) - 1
        self.clamp()

    def activate(self) -> None:
        cur = self.current()
        if cur is not None and self.on_activate:
            self.on_activate(cur)

    def draw(self, win, y: int, x: int, h: int, w: int, render):
        self.height = h
        self.clamp()
        v = self._visible()
        for row in range(h):
            i = self.offset + row
            if i >= len(v):
                put(win, y + row, x, "", 0)
                continue
            item = v[i]
            label = render(item)
            attrs = attr(ACCENT, selected=True) if i == self.index else attr(DEFAULT)
            put(win, y + row, x, pad_to(clip(label, w), w), attrs)


def _search_text(item: object) -> str:
    if hasattr(item, "title"):
        return " ".join(
            str(getattr(item, f, "")) for f in ("title", "authors", "tags", "uuid")
        )
    return str(item)


# ── editors ───────────────────────────────────────────────────────────────────

class EditBuffer:
    """A single logical line of text edited inside a curses region."""

    def __init__(self, text: str = ""):
        self.text = text
        self.cursor = len(text)
        self.cursor_x = 0  # view offset of the cursor (in chars)
        self._phys_x = 0

    def insert(self, s: str) -> None:
        self.text = self.text[: self.cursor] + s + self.text[self.cursor :]
        self.cursor += len(s)

    def backspace(self) -> None:
        if self.cursor > 0:
            self.text = self.text[: self.cursor - 1] + self.text[self.cursor :]
            self.cursor -= 1

    def delete(self) -> None:
        if self.cursor < len(self.text):
            self.text = self.text[: self.cursor] + self.text[self.cursor + 1 :]

    def left(self) -> None:
        self.cursor = max(0, self.cursor - 1)

    def right(self) -> None:
        self.cursor = min(len(self.text), self.cursor + 1)

    def clear_line(self) -> None:
        self.text = ""
        self.cursor = 0

    def key(self, ch) -> str:
        """Process one input *ch* (str). Returns 'enter' or ''."""
        if ch in ("\n", "\r"):
            return "enter"
        if ch in ("\x7f", "\b"):  # BACKSPACE / DEL
            self.backspace()
        elif ch == "\x04":  # Ctrl-D
            self.delete()
        elif ch == "\x17":  # Ctrl-W → kill word before cursor
            self.kill_word()
        elif ch.isprintable():
            self.insert(ch)
        return ""

    def kill_word(self) -> None:
        head = self.text[: self.cursor].rstrip(" ")
        head = head.rstrip() if head != self.text[: self.cursor] else head
        # naive: remove the last whitespace-delimited word before the cursor
        t = self.text[: self.cursor]
        stripped = t.rstrip()
        if len(stripped) < len(t):
            kept = stripped
        else:
            idx = stripped.rfind(" ")
            kept = stripped[: idx + 1] if idx >= 0 else ""
        self.text = kept + self.text[self.cursor :]
        self.cursor = len(kept)

    def draw(self, win, y: int, x: int, w: int, attrs: int = 0) -> None:
        # show from the cursor enoward if the text is wider than the region
        prefix = self.text[: self.cursor]
        avail = max(0, w - 1)
        self.cursor_x = text_width(prefix)
        shown = self.text
        # shift left so the cursor is visible
        begin = 0
        while text_width(shown[: self.cursor - begin]) > avail and begin < self.cursor:
            begin += 1
        shown = clip(self.text[begin:], avail)
        put(win, y, x, pad_to(shown, avail), attrs)
        self._phys_x = x + (text_width(self.text[begin : self.cursor]) if begin <= self.cursor else 0)
        try:
            win.move(y, min(x + w - 1, x + text_width(self.text[begin : self.cursor])))
        except curses.error:
            pass


class MultilineBuffer:
    """A multi-line text area (used by the add dialog)."""

    def __init__(self, initial: str = ""):
        self.lines = initial.split("\n")
        self.row = 0
        self.col = 0
        self.scroll = 0

    def current(self) -> str:
        return self.lines[self.row] if self.lines else ""

    def insert_newline(self) -> None:
        cur = self.current()
        before, after = cur[: self.col], cur[self.col :]
        self.lines[self.row] = before + "\n" + after
        self.lines = _split_lines(self.lines)
        self.row += 1
        self.col = 0

    def type_char(self, ch: str) -> None:
        cur = self.current()
        self.lines[self.row] = cur[: self.col] + ch + cur[self.col :]
        self.col += 1

    def backspace(self) -> None:
        if self.col > 0:
            cur = self.current()
            self.lines[self.row] = cur[: self.col - 1] + cur[self.col :]
            self.col -= 1
        elif self.row > 0:
            prev_len = len(self.lines[self.row - 1])
            self.lines[self.row - 1] += self.current()
            del self.lines[self.row]
            self.row -= 1
            self.col = prev_len

    def text(self) -> str:
        return "\n".join(self.lines)

    def sources(self) -> list[str]:
        return [ln.strip() for ln in self.lines if ln.strip()]

    def draw(self, win, y: int, x: int, h: int, w: int) -> None:
        max_visible = h
        if self.row < self.scroll:
            self.scroll = self.row
        elif self.row >= self.scroll + max_visible:
            self.scroll = self.row - max_visible + 1
        for r in range(max_visible):
            li = self.scroll + r
            if li < len(self.lines):
                put(win, y + r, x, clip(self.lines[li], w - 1), attr(DEFAULT))
            else:
                put(win, y + r, x, "", 0)


def _split_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    for ln in lines:
        out.extend(ln.split("\n"))
        if ln.endswith("\n"):
            out.append("")
    return out


# ── modal dialogs ─────────────────────────────────────────────────────────────

def center_win(screen, h: int, w: int):
    my, mx = screen.getmaxyx()
    y = max(0, (my - h) // 2)
    x = max(0, (mx - w) // 2)
    return screen.subwin(h, w, y, x), y, x


def run_dialog(
    screen,
    title: str,
    body: Callable[[object], None],
    on_key: Callable[[object, object], bool | None],
    h: int,
    w: int,
) -> object | None:
    """Host a modal dialog window until *on_key* returns True (close).

    *on_key*(win, key) returns True to close (optionally setting a result via
    closure), False to keep, None for "handled, redraw".
    """
    win, _, _ = center_win(screen, h, w)
    result: dict = {"value": None}
    while True:
        win.erase()
        box(win, title)
        body(win)
        win.refresh()
        ch = _getch(screen)
        if ch is None:
            continue
        if ch == "\x1b":  # ESC closes
            break
        done = on_key(win, ch)
        if done is True:
            break
    win.erase()
    screen.touchwin()
    screen.refresh()
    return result["value"]


def _getch(screen) -> object:
    try:
        c = screen.get_wch()
    except (curses.error, KeyboardInterrupt):
        return None
    if isinstance(c, int):
        if c in (curses.KEY_RESIZE, curses.KEY_MOUSE):
            return None
        # control char
        if c < 32 and c not in (3,):
            return chr(c)
    return c


# ── Prompt ────────────────────────────────────────────────────────────────────

class Prompt:
    """A single-line value dialog; returns ``(value, committed)``."""

    def __init__(self, screen, title: str, initial: str = "", *, hint: str = ""):
        self.scr = screen
        self.title = title
        self.buf = EditBuffer(initial or "")
        self.hint = hint or "Enter = confirm · Esc = cancel"
        self.choices: list[str] = []
        self._choice_idx = 0

    def show(self, choices: list[str] | None = None) -> tuple[str, bool]:
        if choices:
            self.choices = choices
        h, w = 7, max(42, min(90, self.scr.getmaxyx()[1] - 4))
        win, _, _ = center_win(self.scr, h, w)
        result = {"value": "", "ok": False}
        while True:
            win.erase()
            box(win, self.title)
            iw = w - 4
            put(win, 2, 2, clip(self.hint, iw), attr(DIM))
            self.buf.draw(win, 3, 2, iw, attr(DEFAULT) | curses.A_NORMAL)
            put(win, 4, 2, clip("_" * max(0, iw), iw), attr(WARN))
            if self.choices:
                put(win, 5, 2, clip("Tab: " + ", ".join(self.choices[:4]), iw), attr(DIM))
            win.refresh()
            ch = _getch(self.scr)
            if ch is None:
                continue
            if ch == "\x1b":
                break
            if ch in ("\n", "\r"):
                result = {"value": self.buf.text, "ok": True}
                break
            if ch == "\t":
                if self.choices:
                    self._choice_idx = (self._choice_idx + 1) % len(self.choices)
                    self.buf.text = self.choices[self._choice_idx]
                    self.buf.cursor = len(self.buf.text)
                continue
            if isinstance(ch, str):
                self.buf.key(ch)
        win.erase()
        self.scr.touchwin()
        self.scr.refresh()
        return result["value"], result["ok"]


# ── Set picker ────────────────────────────────────────────────────────────────

class SetPicker:
    """Full-screen list of evidence sets (or a create prompt when empty)."""

    def __init__(self, screen, sets, directory, *, allow_create: bool = True, empty: bool = False):
        self.scr = screen
        self.sets = list(sets)
        self.directory = directory
        self.allow_create = allow_create
        self.empty = empty

    def show(self) -> str | None:
        if self.empty or (not self.sets and self.allow_create):
            return self._create()
        lst = List(self.sets)
        while True:
            my, mx = self.scr.getmaxyx()
            self.scr.erase()
            put(self.scr, 0, 0, clip("Select an evidence set", mx), attr(TITLE))
            rows = my - 2
            lst.draw(self.scr, 1, 0, rows, mx, lambda s: f"{s.slug}  ({s.set_type.value})  — {s.name}")
            put(self.scr, my - 1, 0, clip("j/k move · Enter open · c create · q quit", mx), attr(DIM))
            self.scr.refresh()
            ch = _getch(self.scr)
            if ch is None:
                continue
            if ch == "q" or ch == "\x1b":
                return None
    def _create(self) -> str | None:
        name, ok = Prompt(self.scr, "Create evidence set", hint="name → slug; anon sets get a second prompt").show()
        if not ok or not name.strip():
            return None
        set_type = "normal"
        t, tok = Prompt(self.scr, "Type (normal / anon)", "normal").show()
        if tok and t.strip() in ("anon", "normal"):
            set_type = t.strip()
        try:
            from evid.cli.dataset import create_dataset

            return create_dataset(self.directory, name.strip(), set_type)
        except SystemExit as e:
            put(self.scr, self.scr.getmaxyx()[0] - 1, 0, clip(str(e), self.scr.getmaxyx()[1] - 2), attr(ERR))
            self.scr.refresh()
            _getch(self.scr)
            return None

    @staticmethod
    def _navigate(lst, ch) -> None:
        if isinstance(ch, str):
            if ch == "j":
                lst.move(1)
            elif ch == "k":
                lst.move(-1)
        elif isinstance(ch, int):
            if ch == curses.KEY_DOWN:
                lst.move(1)
            elif ch == curses.KEY_UP:
                lst.move(-1)


# ── Add dialog ────────────────────────────────────────────────────────────────

class AddDialog:
    """Batch quick-add: paste sources, set toggles, stream per-doc results."""

    def __init__(self, screen, directory, slug):
        self.scr = screen
        self.directory = directory
        self.slug = slug
        self.buf = MultilineBuffer()
        self.autolabel = False
        self.no_index = False

    def show(self):
        from evid import extras

        do_index_default = extras.has_vec()
        self.autolabel = False
        self.no_index = not do_index_default

        while True:
            my, mx = self.scr.getmaxyx()
            h = max(12, my - 8)
            w = max(50, min(100, mx - 6))
            win, _, _ = center_win(self.scr, h, w)
            self._edit(win, h, w)
            if not self.buf.sources():
                return None
            return self._run()

    def _edit(self, win, h: int, w: int):
        result = {"abort": False}
        while not result["abort"]:
            win.erase()
            box(win, f"Add to {self.slug} — URLs / PDF paths / directories (one per line)")
            iy = 3
            iw = w - 4
            nh = h - 9
            self.buf.draw(win, iy, 2, nh, iw)
            put(win, iy + nh + 1, 2, clip(self._toggles(), iw), attr(WARN))
            put(win, h - 2, 2, clip("Enter = add  ·  l = autolabel  ·  i = index  ·  Esc = cancel", w - 4), attr(DIM))
            win.refresh()
            ch = _getch(self.scr)
            if ch is None:
                continue
            if ch == "\x1b":
                result["abort"] = True
                break
            if ch in ("\n", "\r"):
                break
            if ch == "l":
                self.autolabel = not self.autolabel
            elif ch == "i":
                self.no_index = not self.no_index
            elif ch == "\t":
                pass
            elif ch in ("\x7f", "\b"):
                self.buf.backspace()
            elif isinstance(ch, str):
                if ch == "\n":
                    self.buf.insert_newline()
                else:
                    self.buf.type_char(ch)
        win.erase()
        self.scr.touchwin()
        self.scr.refresh()
        # any-char path: leave the buffer full for editing in the same session
        return

    def _toggles(self) -> str:
        right = f"index: {'OFF' if self.no_index else 'ON'} (i)"
        lab = f"autolabel: {'on' if self.autolabel else 'off'} (l)"
        return f"{lab}    {right}"

    def _run(self):
        from evid.tui import data

        results: list = []
        my, mx = self.scr.getmaxyx()
        h = max(8, min(20, my - 6))
        w = max(50, mx - 6)
        win, _, _ = center_win(self.scr, h, w)

        def progress(res) -> None:
            results.append(res)
            self._draw_results(win, h, w, results)
            c = _getch(self.scr)  # let the user Ctrl+C / Esc out mid-batch
            if c == "\x1b":
                raise _Abort()

        try:
            data.run_add(
                self.directory,
                self.slug,
                self.buf.sources(),
                do_index=not self.no_index,
                autolabel=self.autolabel,
                on_progress=progress,
            )
        except _Abort:
            pass
        self._draw_results(win, h, w, results)
        put(win, h - 1, 2, clip("Press Enter to continue", w - 4), attr(DIM))
        win.refresh()
        while True:
            c = _getch(self.scr)
            if c in ("\n", "\r") or c == "\x1b":
                break
        win.erase()
        self.scr.touchwin()
        self.scr.refresh()
        return results

    def _draw_results(self, win, h: int, w: int, results) -> None:
        win.erase()
        box(win, f"Adding to {self.slug}")
        top = max(0, len(results) - (h - 4))
        for i, r in enumerate(results[top:], start=top):
            mark = " ✓" if r.ok else " ✗"
            a = attr(OK) if r.ok else attr(ERR)
            put(win, 2 + (i - top), 2, clip(mark + " " + r.source, w - 6), a)
            if not r.ok and r.message:
                put(win, 2 + (i - top), 6, clip(r.message, max(0, w - 12)), attr(DIM))
        win.refresh()


class _Abort(Exception):
    """Raised when a user interrupts a batch add (clean unwind)."""


# ── help ──────────────────────────────────────────────────────────────────────

_HELP = [
    ("a", "Add documents (paste URLs / PDF paths)"),
    ("/", "Filter the document list"),
    ("j/k · ↓/↑", "Move through the list"),
    ("g / G", "Top / bottom of the list"),
    ("t / T", "Tag / untag the selected document"),
    ("n", "Set / edit the document's note"),
    ("m", "Edit title / authors / dates / url"),
    ("o · Enter", "Open the document's folder"),
    ("Tab", "Move focus between list and details"),
    ("s", "Switch evidence set"),
    ("r", "Refresh from disk"),
    ("? / q", "This help / quit"),
]

def help_overlay(screen) -> None:
    rows = len(_HELP) + 3
    h = max(rows + 2, 14)
    w = min(76, screen.getmaxyx()[1] - 4)
    win, _, _ = center_win(screen, h, w)
    while True:
        win.erase()
        box(win, "evid TUI — keys")
        for i, (k, desc) in enumerate(_HELP):
            put(win, 2 + i, 3, pad_to(clip(k, 14), 14), attr(ACCENT))
            put(win, 2 + i, 18, clip(desc, w - 22), attr(DEFAULT))
        put(win, h - 2, 3, clip("Esc to close", w - 6), attr(DIM))
        win.refresh()
        ch = _getch(screen)
        if ch is not None and (ch == "\x1b" or (isinstance(ch, str) and ch in ("q", "\n", "\r"))):
            break
    win.erase()
    screen.touchwin()
    screen.refresh()
