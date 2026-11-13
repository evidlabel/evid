"""Headless tests of the Textual TUI via Textual's own Pilot harness.

Boots the real ``TUIApp`` (no terminal, no network) and drives it with the
keyboard: the list renders, row highlight updates the detail pane, the add
modal opens/cancels, and a tag is written through the prompt modal. Uses the
same temp-dir fixture pattern as :mod:`tests.test_tui_data` (a real generated
PDF).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from evid.tui import data
from evid.tui.app import TUIApp


@pytest.fixture
def directory(tmp_path: Path) -> Path:
    return tmp_path / "db"


@pytest.fixture
def slug(directory: Path) -> str:
    from evid.services.set_manager import SetManager

    return SetManager(directory).create_set("Case Alpha", "normal").slug


def _pdf(path: Path, text: str = "Textual evidence doc.") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=11)
    doc.save(str(path))
    doc.close()
    return path


def _one_doc(directory: Path, slug: str) -> str:
    pdf = _pdf(directory / "in" / "doc.pdf", "Textual evidence doc.")
    return data.run_add(directory, slug, [str(pdf)])[0].uuid


def _drive(app: TUIApp, scenario):
    """Drive *app* through its Pilot within one asyncio run; return the value."""

    async def go():
        async with app.run_test(size=(110, 32)) as pilot:
            return await scenario(pilot)

    return asyncio.run(go())


def _screen(pilot) -> str:
    return pilot.app.screen.__class__.__name__


async def _wait_screen(pilot, name: str, tries: int = 50) -> None:
    for _ in range(tries):
        await pilot.pause(0.02)
        if _screen(pilot) == name:
            return
    raise AssertionError(f"never reached {name}; screen is {_screen(pilot)!r}")


def _rows(pilot) -> int:
    from textual.widgets import DataTable

    return len(pilot.app.screen.query_one("#docs", DataTable).rows)


# ── scenarios ────────────────────────────────────────────────────────────────

def test_boot_to_main_lists_doc(directory: Path, slug: str):
    _one_doc(directory, slug)

    async def sc(pilot):
        await _wait_screen(pilot, "MainScreen")
        assert _rows(pilot) == 1

    # boot straight into the workspace when a set slug is given
    _drive(TUIApp(directory, slug), sc)


def test_row_highlight_updates_detail(directory: Path, slug: str):
    _one_doc(directory, slug)

    async def sc(pilot):
        await _wait_screen(pilot, "MainScreen")
        pane = pilot.app.screen.query_one("#detail")
        chunks = []
        for w in pane.children:
            c = getattr(w, "_Static__content", None)
            chunks.append(str(c) if c is not None else "")
        text = "".join(chunks)
        assert "uuid" in text.lower() and "case-alpha" in text.lower()

    _drive(TUIApp(directory, slug), sc)


def test_add_modal_opens_and_cancels(directory: Path, slug: str):
    _one_doc(directory, slug)

    async def sc(pilot):
        await _wait_screen(pilot, "MainScreen")
        assert _rows(pilot) == 1
        await pilot.press("a")
        await _wait_screen(pilot, "AddModal")
        await pilot.press("escape")
        await _wait_screen(pilot, "MainScreen")
        assert _rows(pilot) == 1

    _drive(TUIApp(directory, slug), sc)


def test_tag_written_through_prompt_modal(directory: Path, slug: str):
    _one_doc(directory, slug)

    async def sc(pilot):
        await _wait_screen(pilot, "MainScreen")
        await pilot.press("t")
        await _wait_screen(pilot, "PromptModal")
        for ch in "court":
            await pilot.press(ch)
        await pilot.press("enter")
        await _wait_screen(pilot, "MainScreen")
        tags = data.list_docs(directory, slug)[0].tags
        assert any(t.endswith(".court") for t in tags)

    _drive(TUIApp(directory, slug), sc)
    # confirm the write landed on disk
    assert any(t.endswith(".court") for t in data.list_docs(directory, slug)[0].tags)


def test_picker_selects_to_main(directory: Path, slug: str):
    _one_doc(directory, slug)

    async def sc(pilot):
        await _wait_screen(pilot, "SetPicker")
        await pilot.press("enter")
        await _wait_screen(pilot, "MainScreen")
        assert pilot.app.screen.slug == slug
        assert _rows(pilot) == 1

    _drive(TUIApp(directory, None), sc)


def test_run_refuses_non_tty(monkeypatch):
    import evid.tui.app as app_mod

    monkeypatch.setattr(app_mod, "_is_tty", lambda: False)
    assert app_mod.run(db=str(Path("/tmp/evid-non-tty"))) == 1
