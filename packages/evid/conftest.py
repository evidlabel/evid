"""Pytest bootstrap for the evid package.

Under ``--import-mode=importlib`` (set in the root ``pyproject.toml``) pytest
does not add the rootdir to ``sys.path``. The ``tests`` package therefore is
not importable by its dotted name from a *fresh* interpreter.

``evid.vec.safe_index.run_in_subprocess`` uses the ``spawn`` start method,
which launches a brand-new interpreter that re-imports the target function by
its qualified name. When the target lives in ``tests.test_safe_index`` the
child fails with ``ModuleNotFoundError: No module named 'tests'``. Putting the
directory that contains the ``tests`` package on ``sys.path`` here — before any
subprocess is spawned — lets ``spawn`` (which propagates ``sys.path`` to the
child) import the test module successfully.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
