"""Pytest bootstrap for the evid package.

Under ``--import-mode=importlib`` (set in the root ``pyproject.toml``) pytest
does not add the rootdir to ``sys.path``. The ``tests`` package therefore is
not importable by its dotted name from a *fresh* interpreter.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def wait_for_docs():
    """Return a helper that blocks until a DocsTab's set-load worker finishes.

    Set loading is off-thread, so a test that selects a set must wait for the
    worker and let the queued ``_on_set_loaded`` slot run before reading the
    table.
    """

    def _wait(qapp, tab, timeout_ms: int = 5000) -> None:
        for worker in list(tab._workers):
            worker.wait(timeout_ms)
        for _ in range(10):
            qapp.processEvents()

    return _wait
