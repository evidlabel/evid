"""Extra data directories shown as trunks beside the GUI's own data dir.

The primary directory is not stored. ``roots.yml`` in that directory is a YAML
list of the other paths. A bad file, or a path that is missing, is skipped and
the file is rewritten so the GUI still starts.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

PRIMARY = "main"
ROOTS_NAME = "roots.yml"
_BUCKETS = ("anon", "plain", "sets")


def root_id(path: Path) -> str:
    """Stable short id for a resolved data directory."""
    digest = hashlib.sha256(str(path.resolve()).encode(), usedforsecurity=False)
    return digest.hexdigest()[:8]


def label_for(path: Path, *, primary: bool) -> str:
    """Primary is always ``global``. A case ``…/<name>/evid`` is named ``<name>``."""
    if primary:
        return "global"
    path = path.resolve()
    if path.name == "evid":
        parent = path.parent.name
        if parent and parent not in (path.anchor, ".", "/"):
            return parent
    return path.name or str(path)


def disambiguate(name: str, taken: set[str]) -> str:
    if name not in taken:
        return name
    n = 2
    while f"{name}-{n}" in taken:
        n += 1
    return f"{name}-{n}"


def overlaps(a: Path, b: Path) -> bool:
    """True when the paths are the same directory, or one contains the other."""
    a, b = a.resolve(), b.resolve()
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def is_set_dir(path: Path) -> bool:
    """A single evidence set (``set.yml``), not a data directory that holds sets."""
    if not (path / "set.yml").is_file():
        return False
    return not any((path / name).is_dir() for name in _BUCKETS)


def load_saved(data_dir: Path) -> tuple[list[Path], bool]:
    """Stored paths, and whether the file is unusable and should be rewritten.

    A missing file is ``([], False)``. Bad YAML or a non-list is ``([], True)``.
    """
    file = Path(data_dir) / ROOTS_NAME
    if not file.is_file():
        return [], False
    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return [], True
    if data is None:
        return [], False
    if not isinstance(data, list):
        return [], True
    out: list[Path] = []
    dirty = False
    for item in data:
        if isinstance(item, str) and item.strip():
            out.append(Path(item).expanduser())
        else:
            dirty = True
    return out, dirty


def save_saved(data_dir: Path, paths: list[Path]) -> None:
    dest = Path(data_dir) / ROOTS_NAME
    text = yaml.safe_dump([str(p) for p in paths], allow_unicode=True, sort_keys=False)
    tmp = dest.with_suffix(".yml.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(dest)


def prepare(path: Path | str) -> Path:
    """Resolve a directory the user asked to connect.

    A missing ``…/evid`` whose parent exists is created (a case workdir that
    has not had a handoff yet). Anything else missing, or a set folder, raises
    ``ValueError``.
    """
    path = Path(path).expanduser()
    if not path.exists():
        if path.name == "evid" and path.parent.is_dir():
            path.mkdir()
        else:
            raise ValueError(f"no such directory: {path}")
    try:
        path = path.resolve()
    except OSError as exc:
        raise ValueError(f"no such directory: {path}") from exc
    if not path.is_dir():
        raise ValueError(f"not a directory: {path}")
    if is_set_dir(path):
        raise ValueError(
            f"{path} is one evidence set. Connect the data directory that holds it."
        )
    return path
