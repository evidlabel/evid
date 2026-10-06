"""Commit a document's labelling files when its set lives in git.

Saving a label commits ``label/`` (and a pass commits ``pass/``) at once, so the
document's history shows every labelling step. Only those paths are touched:
``git commit -- <paths>`` leaves anything else you have staged as it was.
Not in a git work tree, or git missing: nothing happens. Failures are logged as
warnings and never fail the save.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False, timeout=30
    )


def work_tree(path: Path) -> Path | None:
    """The top of the git work tree that contains *path*, if any."""
    if shutil.which("git") is None:
        return None
    path = Path(path)
    r = _git(path if path.is_dir() else path.parent, "rev-parse", "--show-toplevel")
    return Path(r.stdout.strip()) if r.returncode == 0 else None


def commit_paths(paths: list[Path], message: str) -> str | None:
    """Commit *paths* (files or folders) with *message*; returns the short hash, or None."""
    paths = [Path(p) for p in paths if Path(p).exists()]
    if not paths:
        return None
    top = work_tree(paths[0])
    if top is None:
        return None
    rel = [str(p.resolve().relative_to(top.resolve())) for p in paths]
    add = _git(top, "add", "-A", "--", *rel)
    if add.returncode != 0:
        logger.warning("git add failed for %s: %s", ", ".join(rel), add.stderr.strip())
        return None
    if _git(top, "diff", "--cached", "--quiet", "--", *rel).returncode == 0:
        return None  # nothing changed there
    c = _git(top, "commit", "-q", "-m", message, "--", *rel)
    if c.returncode != 0:
        logger.warning(
            "git commit failed (%s): %s", message, (c.stderr or c.stdout).strip()
        )
        return None
    h = _git(top, "rev-parse", "--short", "HEAD").stdout.strip()
    logger.info("Committed %s: %s", h, message)
    return h


def commit_labels(doc_dir: Path, message: str) -> str | None:
    """Commit the document's ``label/`` and ``pass/`` folders."""
    doc_dir = Path(doc_dir)
    return commit_paths([doc_dir / "label", doc_dir / "pass"], message)
