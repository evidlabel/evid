#!/usr/bin/env python3
"""Write assets/gui-docs.png and assets/gui-search.png for the README.

Seeds a fictional set (no real case material). Offscreen Qt; no embedding model.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("HEADLESS", "1")

ROOT = Path(__file__).resolve().parents[1]
OUT_DOCS = ROOT / "assets" / "gui-docs.png"
OUT_SEARCH = ROOT / "assets" / "gui-search.png"

_DOCS = (
    (
        "1b43434c74391c1c59b505139398c30c",
        "kommune-afgorelse",
        "overvåget samvær uden partshøring",
        "sample.afgorelse",
    ),
    (
        "3c8f418ca17eda5b43adb3aa96db7a3e",
        "psykolog-erklaering",
        "anbefaler gradvis udvidelse af samværet",
        "sample.psykolog",
    ),
    (
        "606525d4aed2bf50ff2693ca5f49321a",
        "klage-ankestyrelsen",
        "klage over manglende partshøring",
        "sample.klage",
    ),
)


def _write_doc(set_dir: Path, uuid: str, label: str, quote: str, tag: str) -> None:
    import yaml

    doc_dir = set_dir / "docs" / uuid
    doc_dir.mkdir(parents=True)
    info = {
        "uuid": uuid,
        "original_name": f"{label}.pdf",
        "title": label,
        "label": label,
        "authors": "",
        "dates": "2026-07-13",
        "url": "",
        "tags": tag,
        "time_added": "2026-07-13",
    }
    (doc_dir / "info.yml").write_text(
        yaml.safe_dump(info, allow_unicode=True), encoding="utf-8"
    )
    (doc_dir / "evid_meta.yml").write_text(
        yaml.safe_dump({"notes": "", "indexed": False}, allow_unicode=True),
        encoding="utf-8",
    )
    (doc_dir / "original.pdf").write_bytes(b"%PDF")
    (doc_dir / "label.typ").write_text(
        f'#lab("{label.replace("-", "_")}", "{quote}", "")\n',
        encoding="utf-8",
    )
    (doc_dir / "label.json").write_text(
        json.dumps(
            [
                {
                    "value": {
                        "key": label.replace("-", "_"),
                        "opage": 1,
                        "text": quote,
                        "note": "",
                    }
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _pump(_app, ms: int = 40) -> None:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _wait_rows(app, table, timeout_ms: int = 8000) -> None:
    from PySide6.QtCore import QElapsedTimer

    timer = QElapsedTimer()
    timer.start()
    while timer.elapsed() < timeout_ms:
        app.processEvents()
        if table.rowCount() > 0:
            return
        _pump(app, 30)
    msg = "search produced no rows for README snapshot"
    raise SystemExit(msg)


def _grab(win, dest: Path) -> None:
    from PySide6.QtCore import Qt

    dest.parent.mkdir(parents=True, exist_ok=True)
    pix = win.grab().scaledToWidth(900, Qt.TransformationMode.SmoothTransformation)
    if not pix.save(str(dest), "PNG"):
        msg = f"failed to write {dest}"
        raise SystemExit(msg)
    print(f"wrote {dest}", flush=True)


def main() -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    db = Path(tempfile.mkdtemp()) / "evid"
    db.mkdir(parents=True)

    from evid.config import EvidConfig
    from evid.gui.main_window import EvidWindow
    from evid.services.set_manager import SetManager

    sm = SetManager(db)
    evidence_set = sm.create_set("Sample brief")
    for uuid, label, quote, tag in _DOCS:
        _write_doc(evidence_set.path, uuid, label, quote, tag)

    app = QApplication.instance() or QApplication(sys.argv)
    try:
        QGuiApplication.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except Exception:
        pass

    config = EvidConfig()
    config.data_dir = db
    win = EvidWindow(config=config)
    win.resize(1200, 760)
    win.show()
    for _ in range(12):
        _pump(app, 20)

    win._sidebar.select_first()
    for _ in range(8):
        _pump(app, 20)
    if win._docs_tab._table.rowCount() > 0:
        win._docs_tab._table.selectRow(0)
    _pump(app, 50)
    # Re-assert the size: a transient status-bar message during load can grow the
    # window's minimum height, and the window does not shrink back when it hides.
    win.resize(1200, 760)
    _pump(app, 20)
    _grab(win, OUT_DOCS)

    win._tab_bar.setCurrentIndex(1)
    _pump(app, 50)
    search = win._search_tab
    search._sub_tabs.setCurrentIndex(2)
    _pump(app, 30)
    search._text_query.setText("partshøring")
    search._run_text_search()
    _wait_rows(app, search._table)
    search._table.selectRow(0)
    _pump(app, 80)
    win.resize(1200, 760)
    _pump(app, 20)
    _grab(win, OUT_SEARCH)

    win.close()


if __name__ == "__main__":
    main()
