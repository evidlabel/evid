"""Headless GUI tests for document listing."""

import os

import pytest
import yaml

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


def _write_doc(set_path, doc_uuid: str, label: str = "Test doc", **info_extra) -> None:
    doc_dir = set_path / "docs" / doc_uuid
    doc_dir.mkdir(parents=True)
    payload = {
        "label": label,
        "tags": "",
        "title": label,
        "authors": "",
        "dates": "2024",
        "url": "",
    }
    payload.update(info_extra)
    with (doc_dir / "info.yml").open("w") as f:
        yaml.safe_dump(payload, f)
    with (doc_dir / "evid_meta.yml").open("w") as f:
        yaml.safe_dump({"notes": "", "indexed": False}, f)


def test_docs_table_skips_dirs_without_info_yml(qapp, tmp_path, wait_for_docs):
    from evid.config import EvidConfig
    from evid.gui.main_window import EvidMgrWindow

    config = EvidConfig(data_dir=tmp_path)
    window = EvidMgrWindow(config=config)
    evidence_set = window._set_manager.create_set("Case")
    _write_doc(
        evidence_set.path,
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        label="PHD_ER_ONLINE",
    )
    (evidence_set.path / "docs" / "sets").mkdir()
    window._sidebar.refresh()
    window._sidebar.select_first()
    wait_for_docs(qapp, window._docs_tab)
    table = window._docs_tab._table
    labels = [
        table.item(r, 2).text()
        for r in range(table.rowCount())
        if table.item(r, 2) is not None
    ]
    assert "PHD_ER_ONLINE" in labels
    assert "sets" not in labels
    window.close()
