"""Annotations: notes on a document and on the files in its folder.

They are for the people and agents who use or handle the evidence set (what a
file is, what to watch out for, what is still missing). They live next to the
document in ``annotations.yml``, a plain mapping:

    .: note on the document as a whole
    original.pdf: note on that file
    attachments/scan-2.pdf: note on a file in a sub-folder

Keys are paths relative to the document folder (``.`` is the document itself).
An empty note removes the key. The file is kept in git by ``evid set track`` and
copied with the document.

Older documents kept one free-text ``notes`` string in ``evid_meta.yml``; it is
read as the document note until a note is written here.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import yaml

from evid.core.evid_meta import read_meta, write_meta

ANNOTATIONS_FILE = "annotations.yml"
DOC = "."


def _key(doc_dir: Path, path: str, *, must_exist: bool = True) -> str:
    """Normalise *path* to a key; refuse anything outside the document folder."""
    raw = (path or DOC).replace("\\", "/").strip()
    if raw in ("", ".", "./"):
        return DOC
    pure = PurePosixPath(raw)
    if pure.is_absolute() or ".." in pure.parts:
        msg = f"path outside the document folder: {path!r}"
        raise ValueError(msg)
    key = str(pure)
    if key == ANNOTATIONS_FILE:
        msg = f"{ANNOTATIONS_FILE} holds the annotations; it cannot have one"
        raise ValueError(msg)
    if must_exist and not (doc_dir / key).exists():
        msg = f"no such file in the document: {key}"
        raise FileNotFoundError(msg)
    return key


def read_annotations(doc_dir: Path) -> dict[str, str]:
    """All annotations of a document: ``{key: note}``, ``.`` first, then by path."""
    p = doc_dir / ANNOTATIONS_FILE
    notes: dict[str, str] = {}
    if p.exists():
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict):
            notes = {str(k): str(v) for k, v in raw.items() if v not in (None, "")}
    if DOC not in notes:
        legacy = read_meta(doc_dir).get("notes")
        if isinstance(legacy, str) and legacy.strip():
            notes[DOC] = legacy
    return dict(sorted(notes.items(), key=lambda kv: (kv[0] != DOC, kv[0])))


def doc_note(doc_dir: Path) -> str:
    """The note on the document as a whole ('' if none)."""
    return read_annotations(doc_dir).get(DOC, "")


def write_annotation(doc_dir: Path, path: str, text: str) -> dict[str, str]:
    """Set (or, with empty *text*, remove) the note on *path*. Returns all notes."""
    text = (text or "").rstrip()
    key = _key(
        doc_dir, path, must_exist=bool(text)
    )  # a stale note can still be removed
    notes = read_annotations(doc_dir)
    if text:
        notes[key] = text
    else:
        notes.pop(key, None)
    p = doc_dir / ANNOTATIONS_FILE
    if notes:
        p.write_text(
            yaml.safe_dump(notes, allow_unicode=True, sort_keys=False, width=2**20),
            encoding="utf-8",
        )
    elif p.exists():
        p.unlink()
    if key == DOC:  # the legacy string must not come back once the note is edited
        meta = read_meta(doc_dir)
        if meta.get("notes"):
            meta["notes"] = ""
            write_meta(doc_dir, meta)
    return read_annotations(doc_dir)


def missing_targets(doc_dir: Path, notes: dict[str, str]) -> list[str]:
    """Annotated paths that no longer exist in the folder."""
    return [k for k in notes if k != DOC and not (doc_dir / k).exists()]
