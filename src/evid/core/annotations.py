"""Annotations: notes on the files in a document's folder.

They are for the people and agents who use or handle the evidence set (what a
file is, what to watch out for, what is still missing). They live next to the
document in ``annotations.yml``, a plain mapping:

    original.pdf: note on that file
    attachments/scan-2.pdf: note on a file in a sub-folder

Keys are paths relative to the document folder. An empty note removes the key.
The file is kept in git by ``evid set track`` and copied with the document.

A note on the document as a whole is not stored here. It is a list of
whole-document labels and annotations in ``label/labels.json`` (see
:mod:`evid.core.labels`). Older documents kept that note as the ``.`` key in
this file, or as a ``notes`` string in ``evid_meta.yml``. Those are still read
until :func:`evid.core.labels.adopt_legacy_document_note` moves them.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import yaml

from evid.core.evid_meta import read_meta, write_meta

ANNOTATIONS_FILE = "annotations.yml"
DOC = "."


class _Dumper(yaml.SafeDumper):
    """Multi-line notes as `|` blocks, so the file reads like the notes."""


def _str(dumper: yaml.SafeDumper, data: str):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str)


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
    """Whole-document notes joined, else the legacy single note ('' if none)."""
    from evid.core.labels import document_blurb

    return document_blurb(doc_dir)


def note_rows(doc_dir: Path) -> list[dict]:
    """Whole-document records, then the file notes.

    A whole-document row has ``path`` ``.``, ``kind`` (``label`` or
    ``annotation``), ``id``, and ``key`` when it is a label. A file row has
    ``path``, ``note``, and ``missing``. The legacy ``.`` string is included
    only when no whole-document record already carries that text.
    """
    from evid.core.labels import notes_text
    from evid.core.labels import read as read_labels

    rows: list[dict] = []
    seen: set[str] = set()
    for rec in read_labels(doc_dir).get("document") or []:
        if not isinstance(rec, dict):
            continue
        text = notes_text(rec)
        kind = rec.get("kind") or "annotation"
        if kind != "label" and not text:
            continue
        row = {
            "path": DOC,
            "note": text,
            "missing": False,
            "kind": kind,
            "id": rec.get("id") or "",
        }
        if rec.get("key"):
            row["key"] = rec["key"]
        rows.append(row)
        if text:
            seen.add(text.strip())
    notes = read_annotations(doc_dir)
    gone = set(missing_targets(doc_dir, notes))
    for key, note in notes.items():
        if key == DOC and note.strip() in seen:
            continue
        rows.append({"path": key, "note": note, "missing": key in gone})
    return rows


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
            yaml.dump(
                notes, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=2**20
            ),
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
