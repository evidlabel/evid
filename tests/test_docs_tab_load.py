"""Set-switch loading: fast YAML, no redundant info.yml parse, async reload."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
import yaml

from evid.services.set_manager import SetManager

if TYPE_CHECKING:
    from pathlib import Path


def _write_doc(
    set_path: Path, uuid: str, label: str, time_added: str, tags: str
) -> None:
    doc = set_path / "docs" / uuid
    doc.mkdir(parents=True)
    (doc / "info.yml").write_text(
        yaml.safe_dump(
            {
                "uuid": uuid,
                "label": label,
                "title": label,
                "authors": "",
                "dates": "2024",
                "tags": tags,
                "url": "",
                "original_name": "original.pdf",
                "time_added": time_added,
            }
        ),
        encoding="utf-8",
    )
    (doc / "evid_meta.yml").write_text(
        yaml.safe_dump({"notes": "", "indexed": True}), encoding="utf-8"
    )
    (doc / "original.pdf").write_bytes(b"%PDF-1.4 stub")


def test_collect_documents_sorted_newest_first(tmp_path):
    from evid.gui.tabs.docs_tab import collect_documents

    sm = SetManager(tmp_path)
    es = sm.create_set("Case")
    _write_doc(es.path, "a" * 32, "Older", "2024-01-01", "alpha")
    _write_doc(es.path, "b" * 32, "Newer", "2024-06-01", "alpha, beta")

    docs = collect_documents(sm, "case")
    assert [d.label for d in docs] == ["Newer", "Older"]
    assert docs[0].tags == ["alpha", "beta"]
    assert docs[0].indexed is True
    assert docs[0].uuid == "b" * 32


def test_resolve_doc_pdf_uses_original_without_parsing_info(tmp_path, monkeypatch):
    """The canonical original.pdf short-circuits before any YAML parse."""
    from evid.services import doc_tags

    doc = tmp_path / "doc"
    doc.mkdir()
    (doc / "original.pdf").write_bytes(b"%PDF")
    (doc / "info.yml").write_text("original_name: other.pdf\n", encoding="utf-8")

    def _boom(*_args, **_kwargs):
        raise AssertionError("info.yml must not be parsed when original.pdf exists")

    monkeypatch.setattr(doc_tags, "load_yaml", _boom)
    assert doc_tags.resolve_doc_pdf(doc) == doc / "original.pdf"


def test_load_yaml_parses_like_safe_load():
    from evid.utils.yaml_io import load_yaml

    assert load_yaml("a: 1\nb: [x, y]\n") == {"a": 1, "b": ["x", "y"]}


# ── GUI: reload is off-thread and drops stale results ──────────────────────────

pytest.importorskip("PySide6")

pytestmark = pytest.mark.skipif(
    os.environ.get("CI") != "true" and os.environ.get("HEADLESS") != "1",
    reason="GUI tests require headless/CI env (set HEADLESS=1)",
)


@pytest.fixture(scope="module")
def qapp():
    import sys

    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


def _make_window(tmp_path):
    from evid.config import EvidConfig
    from evid.gui.main_window import EvidMgrWindow

    return EvidMgrWindow(config=EvidConfig(data_dir=tmp_path))


def test_reload_shows_loading_and_populates_async(qapp, tmp_path, wait_for_docs):
    sm = SetManager(tmp_path)
    es = sm.create_set("Case")
    _write_doc(es.path, "c" * 32, "Doc", "2024-01-01", "alpha")

    window = _make_window(tmp_path)
    tab = window._docs_tab
    tab.reload(es)
    # Immediately after reload the table shows a placeholder, not a freeze.
    assert tab._loading_slug == es.slug
    assert tab._table.item(0, 2).text() == "Loading…"

    wait_for_docs(qapp, tab)
    assert tab._loading_slug is None
    assert tab._table.rowCount() == 1
    assert tab._table.item(0, 2).text() == "Doc"
    window.close()


def test_on_set_loaded_ignores_stale_slug(qapp, tmp_path):
    window = _make_window(tmp_path)
    tab = window._docs_tab
    sm = SetManager(tmp_path)
    current = sm.create_set("Current")
    other = sm.create_set("Other")

    tab.reload(current)
    # A late result for a different set must be dropped.
    tab._on_set_loaded(other.slug, [])
    assert tab._evidence_set.slug == current.slug
    window.close()
