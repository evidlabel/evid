"""Open a local file or directory without failing silently.

Qt GUI processes are multithreaded; ``subprocess.Popen`` (fork+exec) can
deadlock or drop the child. Prefer ``QProcess.startDetached``, then a
session-detached Popen, then ``xdg-open``, then ``QDesktopServices``.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def open_local_path(path: Path | str, *, editor: str | None = None) -> str | None:
    """Open *path* in *editor* (if given) or the desktop handler.

    Returns ``None`` on success, or a short error string. Never raises.
    """
    p = Path(path).expanduser()
    try:
        path_str = str(p.resolve(strict=True))
    except OSError:
        return f"Path does not exist: {p}"

    errors: list[str] = []

    if editor and editor.strip():
        cmd = shutil.which(editor.strip())
        if cmd:
            err = _launch(cmd, path_str)
            if err is None:
                return None
            errors.append(err)
        else:
            errors.append(f"editor {editor.strip()!r} not on PATH")

    xdg = shutil.which("xdg-open")
    if xdg:
        err = _launch(xdg, path_str)
        if err is None:
            return None
        errors.append(err)

    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
    except ImportError:
        return _fmt_error(path_str, errors)

    if QDesktopServices.openUrl(QUrl.fromLocalFile(path_str)):
        return None
    errors.append("desktop handler refused the path")
    return _fmt_error(path_str, errors)


def _launch(program: str, path_str: str) -> str | None:
    """Spawn *program* with *path_str*. ``None`` means the process started."""
    name = Path(program).name
    try:
        from PySide6.QtCore import QProcess

        if QProcess.startDetached(program, [path_str]):
            return None
        logger.warning("QProcess.startDetached refused %s %s", name, path_str)
    except Exception as exc:
        logger.warning("QProcess.startDetached %s: %s", name, exc)

    try:
        subprocess.Popen(
            [program, path_str],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError as exc:
        logger.warning("Could not launch %s %s: %s", name, path_str, exc)
        return f"{name}: {exc}"
    return None


def _fmt_error(path_str: str, errors: list[str]) -> str:
    if errors:
        return f"Could not open {path_str} ({'; '.join(errors)})"
    return f"Could not open {path_str}"
