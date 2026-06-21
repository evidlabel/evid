"""Render a light-theme GUI snapshot for the README.

Points the GUI at an empty data directory so no dataset is loaded (clean
empty-state UI, no real data). Run: `uv run python scripts/gui_snapshot.py`.
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("HEADLESS", "1")

OUT = Path(__file__).resolve().parents[1] / "docs" / "assets" / "gui-light.png"


def main() -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    empty_db = Path(tempfile.mkdtemp()) / "evid"  # empty -> no sets -> nothing loaded
    empty_db.mkdir(parents=True)

    app = QApplication(sys.argv)
    try:
        QGuiApplication.styleHints().setColorScheme(Qt.ColorScheme.Light)
    except Exception:
        pass

    from evid.config import EvidConfig
    from evid.gui.main_window import EvidWindow

    config = EvidConfig()
    config.data_dir = empty_db
    win = EvidWindow(config=config)
    win.resize(1100, 720)
    win.show()
    for _ in range(8):
        app.processEvents()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    win.grab().save(str(OUT))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
