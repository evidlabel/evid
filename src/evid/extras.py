"""Optional install extras: gui (PySide6) and vec (chromadb + sentence-transformers)."""

from __future__ import annotations

import importlib.util

VEC_INSTALL = (
    "Vector search requires the vec extra. "
    'Install with: uv tool install "evid[vec] @ git+https://github.com/evidlabel/evid.git" '
    '(not PyPI — evid is git-only). From a checkout: uv pip install -e ".[vec]"'
)
GUI_INSTALL = (
    "GUI requires the gui extra (PySide6). "
    'Install with: uv tool install "evid[gui] @ git+https://github.com/evidlabel/evid.git" '
    '(not PyPI — evid is git-only). From a checkout: uv pip install -e ".[gui]"'
)
VEC_SKIP_INDEX = "Skipping vector index (install evid[vec] to enable)."


def has_vec() -> bool:
    return (
        importlib.util.find_spec("chromadb") is not None
        and importlib.util.find_spec("sentence_transformers") is not None
    )


def has_gui() -> bool:
    return importlib.util.find_spec("PySide6") is not None


def require_vec() -> None:
    if not has_vec():
        raise ImportError(VEC_INSTALL)


def require_gui() -> None:
    if not has_gui():
        raise ImportError(GUI_INSTALL)
