"""Headless tests of the Textual TUI via Textual's own Pilot harness.

Boots the real ``TUIApp`` (no terminal, no network) and drives it with the
keyboard: ingest, label paragraphs, copy saved labels, and exit. Uses the
same temp-dir fixture pattern as :mod:`tests.test_tui_data` (a real generated
PDF).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from textual.widgets import Button, DataTable, Input, Select

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
    return data.run_add(directory, slug, [str(pdf)], do_index=False)[0].uuid


def _drive(app: TUIApp, scenario):
    """Drive *app* through its Pilot within one asyncio run; return the value."""

    async def go():
        async with app.run_test(size=(110, 32)) as pilot:
            result = await scenario(pilot)
            await app.workers.wait_for_complete()
            return result

    return asyncio.run(go())


def _screen(pilot) -> str:
    return pilot.app.screen.__class__.__name__


async def _wait_screen(pilot, name: str, tries: int = 50) -> None:
    for _ in range(tries):
        await pilot.pause(0.02)
        if _screen(pilot) == name:
            return
    raise AssertionError(f"never reached {name}; screen is {_screen(pilot)!r}")


def _rows(pilot, selector: str = "#docs") -> int:
    from textual.widgets import DataTable

    return len(pilot.app.screen.query_one(selector, DataTable).rows)


async def _wait_rows(pilot, selector: str, expected: int, tries: int = 100) -> None:
    for _ in range(tries):
        await pilot.pause(0.02)
        if _rows(pilot, selector) == expected:
            return
    raise AssertionError(
        f"{selector} never reached {expected} rows (has {_rows(pilot, selector)})"
    )


# ── scenarios ────────────────────────────────────────────────────────────────


def test_boot_to_main_lists_doc(directory: Path, slug: str):
    _one_doc(directory, slug)

    async def sc(pilot):
        await _wait_screen(pilot, "MainScreen")
        assert _rows(pilot) == 1

    # boot straight into the workspace when a set slug is given
    _drive(TUIApp(directory, slug), sc)


def test_row_highlight_fills_labeller(directory: Path, slug: str):
    _one_doc(directory, slug)

    async def sc(pilot):
        await _wait_screen(pilot, "MainScreen")
        # the document info block sits above the paragraph list
        info = pilot.app.screen.query_one("#docinfo")
        text = str(getattr(info, "_Static__content", ""))
        assert text
        # the labeller reads the document's text and lists its paragraphs
        await _wait_rows(pilot, "#paras", 1)
        reader = str(
            getattr(pilot.app.screen.query_one("#paratext"), "_Static__content", "")
        )
        assert "Textual evidence doc." in reader

    _drive(TUIApp(directory, slug), sc)


def test_ingest_shortcut_and_escape(directory: Path, slug: str):
    _one_doc(directory, slug)

    async def sc(pilot):
        await _wait_screen(pilot, "MainScreen")
        await pilot.press("a")
        assert pilot.app.screen.focused.id == "add"
        await pilot.press("escape")
        assert pilot.app.screen.focused.id == "docs"

    _drive(TUIApp(directory, slug), sc)


def test_boot_without_slug_uses_first_set(directory: Path, slug: str):
    """No -s: the workspace opens on the first set; datasets sit in the left pane."""
    _one_doc(directory, slug)

    async def sc(pilot):
        await _wait_screen(pilot, "MainScreen")
        assert pilot.app.screen.slug == slug
        assert pilot.app.screen.query_one("#sets", Select).value == slug
        assert _rows(pilot) == 1

    _drive(TUIApp(directory, None), sc)


def test_add_bar_ingests_one_source(directory: Path, slug: str):
    """The top bar adds the pasted source straight into the active set."""
    pdf = _pdf(directory / "in" / "one.pdf", "Added from the add bar.")

    async def sc(pilot):
        await _wait_screen(pilot, "MainScreen")
        assert _rows(pilot) == 0
        box = pilot.app.screen.query_one("#add", Input)
        box.focus()
        box.value = str(pdf)
        await pilot.press("enter")
        await _wait_rows(pilot, "#docs", 1, tries=400)

    _drive(TUIApp(directory, slug), sc)
    assert len(data.list_docs(directory, slug)) == 1


@pytest.mark.parametrize("shortcut", ["ctrl+l", "l"])
def test_label_paragraph_from_labeller(directory: Path, slug: str, shortcut: str):
    """Tauri's Ctrl+L and the short alias both persist the selected paragraph."""
    _one_doc(directory, slug)

    async def sc(pilot):
        await _wait_screen(pilot, "MainScreen")
        await _wait_rows(pilot, "#paras", 1)
        await pilot.press(shortcut)
        await _wait_screen(pilot, "PromptModal")
        await pilot.press("enter")  # accept the suggested key
        await _wait_screen(pilot, "MainScreen")
        await _wait_rows(pilot, "#paras", 1)
        doc_dir = data.list_docs(directory, slug)[0].dir
        info = data.list_paragraphs(doc_dir)
        assert info and info[0].keys

    _drive(TUIApp(directory, slug), sc)
    from evid.core.labels import read

    doc_dir = data.list_docs(directory, slug)[0].dir
    assert read(doc_dir)["labels"]


def test_unlabel_paragraph_from_labeller(directory: Path, slug: str):
    """`L` removes the label the prompt is pre-filled with."""
    from evid.core.labels import read

    _one_doc(directory, slug)
    doc_dir = data.list_docs(directory, slug)[0].dir
    para = data.list_paragraphs(doc_dir)[0]
    ok, _ = data.label_paragraph(doc_dir, para.start, para.end, "first")
    assert ok

    async def sc(pilot):
        await _wait_screen(pilot, "MainScreen")
        await _wait_rows(pilot, "#paras", 1)
        await pilot.press("L")
        await _wait_screen(pilot, "PromptModal")
        await pilot.press("enter")  # remove the pre-filled key
        await _wait_screen(pilot, "MainScreen")
        for _ in range(100):
            await pilot.pause(0.02)
            if not read(doc_dir)["labels"]:
                return
        raise AssertionError("label was not removed")

    _drive(TUIApp(directory, slug), sc)


def test_cli_callback_uses_resolved_directory(monkeypatch, tmp_path: Path):
    """`evid tui` must open the data dir main() resolved, not the flag default.

    Regression: the callback used treeparse's ``db`` (always the display
    default ``~/.local/share/evid``), so a config/legacy data dir or ``-d``
    opened an empty workspace.
    """
    import evid.tui.app as app_mod
    from evid.cli import callbacks

    seen: dict[str, object] = {}

    def fake_run(db=None, dataset=None):
        seen.update(db=db, dataset=dataset)
        return 0

    monkeypatch.setattr(app_mod, "run", fake_run)
    monkeypatch.setattr(callbacks, "DIRECTORY", tmp_path)
    with pytest.raises(SystemExit):
        callbacks.tui_callback(db="~/.local/share/evid", dataset="case-alpha")
    assert seen == {"db": str(tmp_path), "dataset": "case-alpha"}


def test_main_routes_dash_d_into_tui(monkeypatch, tmp_path: Path):
    """End to end: `evid -d DIR tui` hands DIR to the TUI."""
    import evid.tui.app as app_mod
    from evid.cli import main as m

    seen: dict[str, object] = {}
    monkeypatch.setattr(
        app_mod,
        "run",
        lambda db=None, dataset=None: seen.update(db=db, dataset=dataset) or 0,
    )
    monkeypatch.setattr(sys, "argv", ["evid", "-d", str(tmp_path), "tui"])
    with pytest.raises(SystemExit):
        m.main()
    assert seen["db"] == str(tmp_path)


def test_run_refuses_non_tty(monkeypatch):
    import evid.tui.app as app_mod

    monkeypatch.setattr(app_mod, "_is_tty", lambda: False)
    assert app_mod.run(db=str(Path("/tmp/evid-non-tty"))) == 1


async def _wait_idle(pilot):
    for _ in range(400):
        await pilot.pause(0.02)
        if not pilot.app.screen._busy:
            return
    raise AssertionError("operation never finished")


def _status(pilot):
    return str(pilot.app.screen.query_one("#status").content)


def test_ingest_label_copy_exit_from_empty_database(directory: Path):
    """Exercise the full workflow, including inbox creation and actual YAML."""
    import yaml

    pdf = _pdf(directory / "in" / "new.pdf", "A passage worth citing.")
    app = TUIApp(directory, None)

    async def sc(pilot):
        await _wait_screen(pilot, "MainScreen")
        assert pilot.app.screen.focused.id == "add"
        pilot.app.screen.query_one("#add", Input).value = str(pdf)
        await pilot.press("enter")
        await _wait_idle(pilot)
        await _wait_rows(pilot, "#paras", 1)
        assert pilot.app.screen.focused.id == "paras"
        await pilot.press("enter")
        await _wait_screen(pilot, "PromptModal")
        pilot.app.screen.query_one(Input).value = "evidence"
        await pilot.press("enter")
        await _wait_screen(pilot, "MainScreen")
        await pilot.press("c")
        await _wait_idle(pilot)
        payload = yaml.safe_load(app.clipboard)
        assert payload["uuid"] == data.list_docs(directory, "inbox")[0].uuid
        assert payload["labels"]["evidence"]["text"] == "A passage worth citing."
        assert "Press q to exit" in _status(pilot)
        await pilot.press("q")
        assert not app.is_running

    _drive(app, sc)


def test_label_keeps_selected_paragraph(directory: Path, slug: str):
    _one_doc(directory, slug)
    doc = data.list_docs(directory, slug)[0]
    # Use canonical text to make a deterministic multi-paragraph document.
    data.list_paragraphs(doc.dir)
    (doc.dir / "label" / "text.txt").write_text(
        "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    )

    async def sc(pilot):
        await _wait_rows(pilot, "#paras", 3)
        table = pilot.app.screen.query_one("#paras", DataTable)
        table.focus()
        await pilot.press("down", "enter")
        await _wait_screen(pilot, "PromptModal")
        pilot.app.screen.query_one(Input).value = "second"
        await pilot.press("enter")
        await _wait_screen(pilot, "MainScreen")
        for _ in range(100):
            await pilot.pause(0.02)
            if pilot.app.screen._paras[1].keys:
                break
        assert table.cursor_row == 1
        assert pilot.app.screen._paras[1].keys == ["second"]
        assert "Second paragraph." in str(
            pilot.app.screen.query_one("#paratext").content
        )

    _drive(TUIApp(directory, slug), sc)


def test_failed_ingest_preserves_source_for_retry(directory: Path, slug: str):
    async def sc(pilot):
        await _wait_screen(pilot, "MainScreen")
        box = pilot.app.screen.query_one("#add", Input)
        box.value = str(directory / "missing.pdf")
        await pilot.press("enter")
        await _wait_idle(pilot)
        assert box.value.endswith("missing.pdf")
        assert not box.disabled
        assert not pilot.app.screen.query_one("#ingest-go", Button).disabled
        assert "missing.pdf" in _status(pilot)
        assert _rows(pilot) == 0

    _drive(TUIApp(directory, slug), sc)


def test_copy_empty_keeps_clipboard_and_failed_export_recovers(
    directory: Path, slug: str, monkeypatch
):
    _one_doc(directory, slug)
    app = TUIApp(directory, slug)

    async def sc(pilot):
        await _wait_screen(pilot, "MainScreen")
        app.copy_to_clipboard("keep me")
        await pilot.press("c")
        await _wait_idle(pilot)
        assert app.clipboard == "keep me"
        assert "No saved labels" in _status(pilot)

        def fail(*args):
            raise OSError("export unavailable")

        monkeypatch.setattr(data, "export_labels", fail)
        await pilot.press("c")
        await _wait_idle(pilot)
        assert app.clipboard == "keep me"
        assert "export unavailable" in _status(pilot)
        assert not pilot.app.screen.query_one("#copy-labels", Button).disabled

    _drive(app, sc)


def test_ingest_disables_duplicate_submissions(directory: Path, slug: str, monkeypatch):
    import threading

    started, release = threading.Event(), threading.Event()
    calls = []

    def slow_add(*args, **kwargs):
        calls.append(kwargs)
        started.set()
        assert release.wait(5)
        return [data.AddResult("test.pdf", False, "test failure")]

    monkeypatch.setattr(data, "run_add", slow_add)

    async def sc(pilot):
        await _wait_screen(pilot, "MainScreen")
        screen = pilot.app.screen
        screen.query_one("#add", Input).value = "test.pdf"
        await pilot.press("enter")
        try:
            assert started.is_set()
            screen._ingest()
            screen.action_quit()
            assert pilot.app.is_running
            assert screen.query_one("#sets", Select).disabled
            assert len(calls) == 1
            assert calls[0]["do_index"] is False
        finally:
            release.set()
        await _wait_idle(pilot)
        assert not screen.query_one("#sets", Select).disabled

    _drive(TUIApp(directory, slug), sc)


def test_set_switch_clears_paragraphs_and_copy_uses_active_set(
    directory: Path, slug: str
):
    import yaml

    from evid.services.set_manager import SetManager

    _one_doc(directory, slug)
    doc = data.list_docs(directory, slug)[0]
    para = data.list_paragraphs(doc.dir)[0]
    data.label_paragraph(doc.dir, para.start, para.end, "alpha")
    other = SetManager(directory).create_set("Other", "normal").slug
    app = TUIApp(directory, slug)

    async def sc(pilot):
        await _wait_rows(pilot, "#paras", 1)
        await pilot.press("c")
        await _wait_idle(pilot)
        assert "alpha" in yaml.safe_load(app.clipboard)["labels"]
        pilot.app.screen.query_one("#sets", Select).value = other
        await pilot.pause()
        assert _rows(pilot) == 0
        assert _rows(pilot, "#paras") == 0
        assert pilot.app.screen.query_one("#label", Button).disabled
        app.copy_to_clipboard("unchanged")
        await pilot.press("c")
        await _wait_idle(pilot)
        assert app.clipboard == "unchanged"
        assert "No saved labels" in _status(pilot)

    _drive(app, sc)


def test_actions_fit_standard_terminal(directory: Path, slug: str):
    _one_doc(directory, slug)
    app = TUIApp(directory, slug)

    async def go():
        async with app.run_test(size=(80, 24)) as pilot:
            await _wait_rows(pilot, "#paras", 1)
            await pilot.pause()
            for selector in (
                "#sets",
                "#add",
                "#ingest-go",
                "#paras",
                "#reader",
                "#label",
                "#unlabel",
                "#copy-labels",
                "#exit",
            ):
                region = app.screen.query_one(selector).region
                assert region.width > 0 and region.height > 0, selector
                assert 0 <= region.x < region.right <= 80, (selector, region)
                assert 0 <= region.y < region.bottom <= 24, (selector, region)
            await pilot.click("#label")
            await _wait_screen(pilot, "PromptModal")
            await pilot.press("escape")
            await _wait_screen(pilot, "MainScreen")
            await app.workers.wait_for_complete()

    asyncio.run(go())


def test_partial_ingest_selects_success_and_reports_failure(
    directory: Path, slug: str, monkeypatch
):
    old_uuid = _one_doc(directory, slug)
    pdf = _pdf(directory / "in" / "different.pdf", "A different document.")
    new_uuid = data.run_add(directory, slug, [str(pdf)], do_index=False)[0].uuid

    def partial_add(*args, **kwargs):
        return [
            data.AddResult("missing.pdf", False, "File not found"),
            data.AddResult("different.pdf", True, "Added", new_uuid),
        ]

    monkeypatch.setattr(data, "run_add", partial_add)

    async def sc(pilot):
        await _wait_screen(pilot, "MainScreen")
        pilot.app.screen._select_doc(old_uuid)
        box = pilot.app.screen.query_one("#add", Input)
        box.focus()
        box.value = "folder"
        await pilot.press("enter")
        await _wait_idle(pilot)
        await _wait_rows(pilot, "#paras", 1)
        assert pilot.app.screen._current_uuid == new_uuid
        assert "missing.pdf: File not found" in _status(pilot)
        assert "Ingested 1/2" in _status(pilot)
        assert box.value == "folder"
        assert pilot.app.screen.focused.id == "paras"

    _drive(TUIApp(directory, slug), sc)


def test_export_includes_all_labelled_docs_only_in_active_set(
    directory: Path, slug: str
):
    import yaml

    from evid.services.set_manager import SetManager

    other = SetManager(directory).create_set("Other", "normal").slug
    for index, target in enumerate((slug, slug, other)):
        pdf = _pdf(directory / "in" / f"{index}.pdf", f"Passage number {index}.")
        result = data.run_add(directory, target, [str(pdf)], do_index=False)[0]
        doc = next(
            d for d in data.list_docs(directory, target) if d.uuid == result.uuid
        )
        para = data.list_paragraphs(doc.dir)[0]
        assert data.label_paragraph(doc.dir, para.start, para.end, f"label-{index}")[0]
    exported = yaml.safe_load(data.export_labels(directory, slug))
    assert len(exported) == 2
    assert {key for doc in exported for key in doc["labels"]} == {"label-0", "label-1"}


def test_tauri_document_shortcuts_keep_labeller_focus(directory: Path, slug: str):
    _one_doc(directory, slug)
    pdf = _pdf(directory / "in" / "next.pdf", "Next document to label.")
    data.run_add(directory, slug, [str(pdf)], do_index=False)

    async def sc(pilot):
        await _wait_rows(pilot, "#paras", 1)
        screen = pilot.app.screen
        order = [doc.uuid for doc in screen._docs]
        screen.query_one("#paras", DataTable).focus()
        for key, row in (
            ("alt+up", 0),
            ("alt+down", 1),
            ("alt+down", 1),
            ("alt+up", 0),
        ):
            await pilot.press(key)
            await _wait_rows(pilot, "#paras", 1)
            assert screen._current_uuid == order[row]
            assert screen.query_one("#docs", DataTable).cursor_row == row
            assert screen.focused.id == "paras"
        await pilot.press("ctrl+l")
        await _wait_screen(pilot, "PromptModal")
        await pilot.press("alt+down")
        assert screen._current_uuid == order[0]  # a modal owns its keyboard
        pilot.app.screen.query_one(Input).value = "tauri-key"
        await pilot.press("enter")
        await _wait_screen(pilot, "MainScreen")
        doc = screen._current_doc()
        assert data.list_paragraphs(doc.dir)[0].keys == ["tauri-key"]
        other = next(d for d in screen._docs if d.uuid != doc.uuid)
        assert not data.list_paragraphs(other.dir)[0].keys

    _drive(TUIApp(directory, slug), sc)


@pytest.mark.parametrize("shortcut", ["ctrl+w", "ctrl+q"])
def test_tauri_exit_shortcuts_work_from_input(
    directory: Path, slug: str, shortcut: str
):
    app = TUIApp(directory, slug)

    async def sc(pilot):
        await _wait_screen(pilot, "MainScreen")
        box = app.screen.query_one("#add", Input)
        box.focus()
        box.value = "some document.pdf"
        await pilot.press(shortcut)
        assert not app.is_running

    _drive(app, sc)
