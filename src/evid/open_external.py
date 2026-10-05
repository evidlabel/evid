"""Open a local file, directory or URL without failing silently.

Tries the configured editor (for files), then ``xdg-open`` / ``open``, then
:mod:`webbrowser`. The child runs in its own session so it outlives evid.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import webbrowser
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

    err = _desktop_open(path_str)
    if err is None:
        return None
    errors.append(err)
    if webbrowser.open(Path(path_str).as_uri()):
        return None
    errors.append("no desktop handler accepted the path")
    return f"Could not open {path_str} ({'; '.join(errors)})"


def open_url(url: str) -> str | None:
    """Open an http(s) URL in the desktop browser. ``None`` on success."""
    if not url.startswith(("http://", "https://")):
        return f"Not a web URL: {url}"
    if _desktop_open(url) is None or webbrowser.open(url):
        return None
    return f"Could not open {url}"


def _desktop_open(target: str) -> str | None:
    opener = shutil.which("open" if sys.platform == "darwin" else "xdg-open")
    if not opener:
        return "xdg-open not found"
    return _launch(opener, target)


def _launch(program: str, arg: str) -> str | None:
    """Spawn *program* with *arg*. ``None`` means the process started."""
    name = Path(program).name
    try:
        subprocess.Popen(
            [program, arg],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError as exc:
        logger.warning("Could not launch %s %s: %s", name, arg, exc)
        return f"{name}: {exc}"
    return None
