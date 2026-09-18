"""Tests for GUI local-path opening: helper, Label, Open dir."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import yaml

if TYPE_CHECKING:
    from pathlib import Path

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt

pytestmark = pytest.mark.skipif(
    os.environ.get("CI") != "true" and os.environ.get("HEADLESS") != "1",
    reason="GUI tests require headless/CI env (set HEADLESS=1)",
)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


def _make_tab(tmp_path, qapp):
    from PySide6.QtWidgets import QMainWindow

    from evid.gui.signals import AppSignals
    from evid.gui.tabs.docs_tab import DocsTab
    from evid.services.doc_ingester import DocIngester
    from evid.services.tag_service import TagService

    signals = AppSignals()
    tag_svc = TagService(tmp_path / "tags.yml")
    ingester = DocIngester(vec_service=None)
    tab = DocsTab(ingester, None, signals, tag_svc)
    mw = QMainWindow()
    mw.setCentralWidget(tab)
    tab._mw = mw
    return tab, signals


def _make_doc_dir(es_path: Path, doc_uuid: str, *, with_typ: bool = True) -> Path:
    doc_dir = es_path / "docs" / doc_uuid
    doc_dir.mkdir(parents=True)
    with (doc_dir / "info.yml").open("w") as f:
        yaml.safe_dump(
            {
                "label": "Test doc",
                "tags": "",
                "title": "Test Title",
                "authors": "Author A",
                "dates": "2024",
                "url": "",
            },
            f,
        )
    with (doc_dir / "evidmgr_meta.yml").open("w") as f:
        yaml.safe_dump({"notes": "", "indexed": False}, f)
    if with_typ:
        (doc_dir / "label.typ").write_text("#show: doc => doc\n")
    return doc_dir


def _select_doc(tab, doc_dir: Path, doc_uuid: str):
    from evid.models import Document

    doc = Document(
        uuid=doc_uuid,
        path=doc_dir,
        label="Test doc",
        tags=[],
        added=datetime.now(tz=UTC),
    )
    tab._docs = [doc]
    tab._refresh_table([doc])
    tab._table.selectRow(0)
    return doc


# ── open_local_path ───────────────────────────────────────────────────────────


def test_open_local_path_missing(qapp, tmp_path):
    from evid.gui.open_external import open_local_path

    err = open_local_path(tmp_path / "nope")
    assert err is not None
    assert "does not exist" in err


def test_open_local_path_editor_start_detached(qapp, tmp_path):
    from evid.gui.open_external import open_local_path

    target = tmp_path / "file.typ"
    target.write_text("")
    with (
        patch("evid.gui.open_external.shutil.which", return_value="/usr/bin/code"),
        patch("PySide6.QtCore.QProcess.startDetached", return_value=True) as started,
    ):
        err = open_local_path(target, editor="code")
    assert err is None
    started.assert_called_once()
    assert started.call_args[0][0] == "/usr/bin/code"
    assert started.call_args[0][1] == [str(target.resolve())]


def test_open_local_path_falls_back_when_editor_missing(qapp, tmp_path):
    from evid.gui.open_external import open_local_path

    target = tmp_path / "folder"
    target.mkdir()

    def which(name):
        return "/usr/bin/xdg-open" if name == "xdg-open" else None

    with (
        patch("evid.gui.open_external.shutil.which", side_effect=which),
        patch("PySide6.QtCore.QProcess.startDetached", return_value=True) as started,
    ):
        err = open_local_path(target, editor="code")
    assert err is None
    started.assert_called_once()
    assert started.call_args[0][0] == "/usr/bin/xdg-open"


def test_open_local_path_reports_when_all_handlers_fail(qapp, tmp_path):
    from evid.gui.open_external import open_local_path

    target = tmp_path / "file.typ"
    target.write_text("")
    with (
        patch("evid.gui.open_external.shutil.which", return_value=None),
        patch("PySide6.QtGui.QDesktopServices.openUrl", return_value=False),
    ):
        err = open_local_path(target, editor="code")
    assert err is not None
    assert "Could not open" in err


def test_open_local_path_popen_fallback_when_qprocess_refuses(qapp, tmp_path):
    from evid.gui.open_external import open_local_path

    target = tmp_path / "file.typ"
    target.write_text("")
    with (
        patch("evid.gui.open_external.shutil.which", return_value="/usr/bin/code"),
        patch("PySide6.QtCore.QProcess.startDetached", return_value=False),
        patch("evid.gui.open_external.subprocess.Popen") as popen,
    ):
        err = open_local_path(target, editor="code")
    assert err is None
    popen.assert_called_once()
    assert popen.call_args.kwargs.get("start_new_session") is True


# ── Docs tab Label / Open dir ─────────────────────────────────────────────────


def test_open_dir_without_selection_is_reported(qapp, tmp_path):
    tab, _signals = _make_tab(tmp_path, qapp)
    with patch("evid.gui.open_external.open_local_path") as opener:
        tab._on_open_dir()
    opener.assert_not_called()
    assert "Select a document first" in tab._mw.statusBar().currentMessage()


def test_label_without_selection_is_reported(qapp, tmp_path):
    tab, _signals = _make_tab(tmp_path, qapp)
    with patch.object(tab._labeler, "label_doc") as label_doc:
        tab._on_label_doc()
    label_doc.assert_not_called()
    assert "Select a document first" in tab._mw.statusBar().currentMessage()


def test_open_dir_reports_helper_error(qapp, tmp_path):
    from evid.services.set_manager import SetManager

    tab, _signals = _make_tab(tmp_path, qapp)
    sm = SetManager(tmp_path)
    es = sm.create_set("Open Set")
    doc_uuid = "c" * 32
    doc_dir = _make_doc_dir(es.path, doc_uuid)
    tab._evidence_set = es
    _select_doc(tab, doc_dir, doc_uuid)

    with patch(
        "evid.gui.open_external.open_local_path", return_value="Could not open dir"
    ):
        tab._on_open_dir()
    assert "Could not open dir" in tab._mw.statusBar().currentMessage()


def test_open_dir_opens_selected_doc_directory(qapp, tmp_path):
    from evid.services.set_manager import SetManager

    tab, _signals = _make_tab(tmp_path, qapp)
    sm = SetManager(tmp_path)
    es = sm.create_set("Open Set")
    doc_uuid = "d" * 32
    doc_dir = _make_doc_dir(es.path, doc_uuid)
    tab._evidence_set = es
    _select_doc(tab, doc_dir, doc_uuid)

    with patch("evid.gui.open_external.open_local_path", return_value=None) as opener:
        tab._on_open_dir()
    opener.assert_called_once_with(doc_dir)


def test_label_open_failure_emits_error_and_still_watches(qapp, tmp_path):
    from evid.services.set_manager import SetManager

    tab, _signals = _make_tab(tmp_path, qapp)
    sm = SetManager(tmp_path)
    es = sm.create_set("Label Set")
    doc_uuid = "e" * 32
    doc_dir = _make_doc_dir(es.path, doc_uuid, with_typ=True)
    tab._evidence_set = es
    _select_doc(tab, doc_dir, doc_uuid)

    errors: list[str] = []
    tab._labeler.label_error.connect(errors.append, Qt.ConnectionType.DirectConnection)
    with patch(
        "evid.gui.label_controller.open_local_path",
        return_value="Could not open label.typ",
    ):
        tab._on_label_doc()

    assert errors == ["Could not open label.typ"]
    typ_path = str(doc_dir / "label.typ")
    assert typ_path in tab._labeler._watcher.files()
    assert "Could not open label.typ" in tab._mw.statusBar().currentMessage()


def test_label_missing_doc_dir_emits_error(qapp, tmp_path):
    from evid.gui.label_controller import LabelController

    errors: list[str] = []
    ctl = LabelController(lambda: "code")
    ctl.label_error.connect(errors.append, Qt.ConnectionType.DirectConnection)
    ctl.label_doc(tmp_path / "missing-doc", "uuid-x")
    assert errors
    assert "missing" in errors[0].lower()


def test_label_and_open_dir_buttons_disabled_without_selection(qapp, tmp_path):
    tab, _signals = _make_tab(tmp_path, qapp)
    assert not tab._open_editor_btn.isEnabled()
    assert not tab._open_dir_btn.isEnabled()


def test_label_and_open_dir_buttons_enabled_with_selection(qapp, tmp_path):
    from evid.services.set_manager import SetManager

    tab, _signals = _make_tab(tmp_path, qapp)
    sm = SetManager(tmp_path)
    es = sm.create_set("Open Set")
    doc_uuid = "f" * 32
    doc_dir = _make_doc_dir(es.path, doc_uuid)
    tab._evidence_set = es
    _select_doc(tab, doc_dir, doc_uuid)
    assert tab._open_editor_btn.isEnabled()
    assert tab._open_dir_btn.isEnabled()
