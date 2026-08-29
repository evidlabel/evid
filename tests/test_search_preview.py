"""Tests for SearchTab._vec_preview_html — context-window preview."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


def _make_set_with_doc(tmp_path: Path, uuid: str, typ_text: str):
    from evid.models import EvidenceSet, SetType

    set_dir = tmp_path / "sets" / "s"
    doc_dir = set_dir / "docs" / uuid
    doc_dir.mkdir(parents=True)
    (doc_dir / "label.typ").write_text(typ_text, encoding="utf-8")
    return EvidenceSet(
        name="S",
        slug="s",
        path=set_dir,
        set_type=SetType.NORMAL,
        created=datetime.now(tz=UTC),
    )


def _tab(qapp):
    from evid.gui.signals import AppSignals
    from evid.gui.tabs.search_tab import SearchTab
    from evid.services.tag_service import TagService

    return SearchTab(
        vec_service=None, tag_service=TagService(Path("/tmp")), signals=AppSignals()
    )


def _vec_result(es, uuid: str, chunk_text: str, char_start: int):
    from evid.models import Document, VecResult

    doc = Document(
        uuid=uuid,
        path=es.path / "docs" / uuid,
        label="Doc",
        tags=[],
        added=datetime.now(tz=UTC),
    )
    return VecResult(
        doc=doc, chunk_text=chunk_text, score=0.9, chunk_idx=0, char_start=char_start
    )


def test_preview_shows_context_around_short_chunk(qapp, tmp_path):
    uuid = "u1"
    full = "Intro paragraph with plenty of surrounding context here. " * 5
    heading = "Rammerne"
    typ_text = full + heading + " " + ("trailing context " * 10)
    es = _make_set_with_doc(tmp_path, uuid, typ_text)

    tab = _tab(qapp)
    tab._evidence_set = es
    res = _vec_result(es, uuid, heading, typ_text.index(heading))

    html = tab._vec_preview_html(res)
    assert html is not None
    # preview is richer than the bare chunk and highlights the match
    assert "<mark" in html
    assert heading in html
    assert len(html) > len(heading) + 20  # surrounding context included


def test_preview_returns_none_when_typ_missing(qapp, tmp_path):
    from evid.models import EvidenceSet, SetType

    es = EvidenceSet(
        name="S",
        slug="s",
        path=tmp_path / "sets" / "s",
        set_type=SetType.NORMAL,
        created=datetime.now(tz=UTC),
    )
    tab = _tab(qapp)
    tab._evidence_set = es
    res = _vec_result(es, "missing", "anything", 0)
    assert tab._vec_preview_html(res) is None


def test_full_text_subtab_present(qapp):
    tab = _tab(qapp)
    labels = [tab._sub_tabs.tabText(i) for i in range(tab._sub_tabs.count())]
    assert "Full-text search" in labels


def test_text_hits_fill_table_and_preview(qapp):
    from evid.core.fulltext import TextHit

    tab = _tab(qapp)
    hits = [
        TextHit(
            uuid="u1",
            label="Doc One",
            page=3,
            snippet="found phrase here",
            char_start=10,
            score=0.88,
        ),
        TextHit(
            uuid="u2",
            label="Doc Two",
            page=1,
            snippet="regex match here",
            char_start=0,
            score=None,
        ),
    ]
    tab._fill_table_from_text_hits(hits)
    assert tab._table.rowCount() == 2
    assert tab._table.item(0, 0).text() == "0.880"  # fuzzy score
    assert tab._table.item(1, 0).text() == "—"  # regex: no score
    assert tab._table.item(0, 3).text() == "u1"  # uuid in column 3 (tag/copy use it)

    tab._table.selectRow(0)
    tab._update_preview()
    assert tab._prev_footer.text() == "Page 3"
    assert "found phrase here" in tab._prev_text.toPlainText()
    assert tab._prev_current_uuid == "u1"


def _dummy_set(tmp_path):
    from evid.models import EvidenceSet, SetType

    return EvidenceSet(
        name="S",
        slug="s",
        path=tmp_path,
        set_type=SetType.NORMAL,
        created=datetime.now(tz=UTC),
    )


def test_input_stays_enabled_during_search(qapp, tmp_path):
    # Inputs must NOT be disabled while a search runs, or the next query's
    # keystrokes get swallowed and the old query re-runs.
    tab = _tab(qapp)
    tab._evidence_set = _dummy_set(tmp_path)
    tab._set_search_busy(True)
    assert tab._query_edit.isEnabled()
    assert tab._text_query.isEnabled()
    assert tab._meta_filter.isEnabled()
    assert not tab._vec_search_btn.isEnabled()  # button reflects busy


def test_submit_while_busy_supersedes_not_drops(qapp, tmp_path):
    # A query submitted while one is in flight is remembered (not silently
    # dropped) and run when the current finishes.
    tab = _tab(qapp)
    tab._evidence_set = _dummy_set(tmp_path)
    tab._search_busy = True
    n_workers = len(tab._workers)
    tab._query_edit.setText("a new query")
    tab._run_vector_search()
    assert tab._pending_search is not None  # remembered
    assert len(tab._workers) == n_workers  # no worker started while busy

    # _run_pending_search runs and clears the remembered request
    ran = []
    tab._pending_search = lambda: ran.append(True)
    tab._run_pending_search()
    assert ran == [True]
    assert tab._pending_search is None
