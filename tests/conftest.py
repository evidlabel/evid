"""Pytest bootstrap for the evid package.

Under ``--import-mode=importlib`` (set in the root ``pyproject.toml``) pytest
does not add the rootdir to ``sys.path``. The ``tests`` package therefore is
not importable by its dotted name from a *fresh* interpreter.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
