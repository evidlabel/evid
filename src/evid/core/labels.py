"""Human labels on a document's plain text (evid 0.7; no Typst).

A document's ``label/`` folder holds:

- ``text.txt``: the canonical plain text — the PDF's extracted text (ligatures
  expanded, end-of-line hyphens joined per page). Written once and then frozen,
  so the spans that point into it never drift. It is tracked in git.
- ``pages.json``: ``{"schema": 1, "pages": [[offset, page], …], "sha256": …}``,
  where each page starts in ``text.txt``.
- ``labels.json``: ``{"schema": 1, "labels": […], "annotations": […],
  "document": […]}``. A label is a span (see :mod:`evid.core.spans`) with a
  ``key`` and a growing list of dated ``notes``; an annotation is a span with
  notes but no key — a comment on a passage made while reading. A ``document``
  record is the same kind of label or annotation assigned to the whole
  document: no ``start``, ``end``, ``page``, or ``text``, and it is not
  re-anchored when the canonical text changes.

Schema stays 1. ``document`` is additive, so an older file still reads.
Each note is ``{at, by, text}``: the author stays, and ``at`` changes only
when the text changes. That list is the record's own history. Git versions
the file the same way it versions span labels (``label/`` is what a label
save commits). There is no second history format.

Everything on a span is verbatim: a record's ``text`` is always
``text.txt[start:end]``. Writes are atomic and take a lock, so the GUI and
an agent's CLI can both write.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import re
import secrets
import unicodedata
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evid.core.spans import locate, make_span, reanchor

LABEL_DIR = "label"
TEXT_FILE = "text.txt"
PAGES_FILE = "pages.json"
LABELS_FILE = "labels.json"
SCHEMA = 1


def _now() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def label_dir(doc_dir: Path) -> Path:
    return Path(doc_dir) / LABEL_DIR


# ── the canonical text ───────────────────────────────────────────────────────


def has_text(doc_dir: Path) -> bool:
    return (label_dir(doc_dir) / TEXT_FILE).exists()


def read_text(doc_dir: Path) -> tuple[str, list[list[int]]]:
    """``(text, pages)`` of the document (``ensure_text`` first)."""
    d = label_dir(doc_dir)
    text = (d / TEXT_FILE).read_text(encoding="utf-8")
    pages = json.loads((d / PAGES_FILE).read_text(encoding="utf-8")).get("pages") or [
        [0, 1]
    ]
    return text, pages


def _write_text(doc_dir: Path, text: str, pages: list) -> None:
    d = label_dir(doc_dir)
    d.mkdir(exist_ok=True)
    (d / TEXT_FILE).write_text(text, encoding="utf-8")
    meta = {
        "schema": SCHEMA,
        "pages": [list(p) for p in pages],
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "extractor": "evid page_text (ligatures expanded, dehyphenated per page)",
    }
    (d / PAGES_FILE).write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")


def ensure_text(doc_dir: Path) -> tuple[str, list[list[int]]]:
    """The canonical text, extracting it from the document's PDF (or .txt) once.

    A frozen text that still holds characters that are not text (unmapped
    ligature glyphs from an older extractor) is extracted again when the new
    extraction is clean, and every span is re-anchored.
    """
    if has_text(doc_dir):
        text, pages = read_text(doc_dir)
        from evid.core.pdf_text import has_bad_chars

        if has_bad_chars(text):
            from evid.core.quote_extract import _read_source

            try:
                fresh, _ = _read_source(Path(doc_dir))
            except (FileNotFoundError, ValueError):
                fresh = text  # no source to extract from: keep what there is
            if not has_bad_chars(fresh):
                import logging

                logging.getLogger(__name__).warning(
                    "%s held characters that are not text; extracted it again and re-anchored the labels",
                    label_dir(doc_dir) / TEXT_FILE,
                )
                refresh_text(doc_dir)
                return read_text(doc_dir)
        return text, pages
    from evid.core.quote_extract import _read_source

    text, pages = _read_source(Path(doc_dir))
    _write_text(doc_dir, text, pages)
    return read_text(doc_dir)


def refresh_text(doc_dir: Path) -> dict[str, int]:
    """Extract the text again and re-anchor every record. Returns counts by outcome."""
    from evid.core.quote_extract import _read_source

    text, pages = _read_source(Path(doc_dir))
    counts: dict[str, int] = {}
    with _locked(doc_dir) as data:
        for kind in ("labels", "annotations"):  # document records have no span
            kept = []
            for rec in data[kind]:
                new, how = reanchor(rec, text, pages)
                counts[how] = counts.get(how, 0) + 1
                kept.append(new or {**rec, "lost": True})
            data[kind] = kept
        _write_text(doc_dir, text, pages)
    return counts


# ── records ──────────────────────────────────────────────────────────────────


def _empty() -> dict[str, Any]:
    return {"schema": SCHEMA, "labels": [], "annotations": [], "document": []}


def read(doc_dir: Path) -> dict[str, Any]:
    """Labels, passage annotations, and whole-document records (empty when none)."""
    p = label_dir(doc_dir) / LABELS_FILE
    if not p.exists():
        return _empty()
    data = json.loads(p.read_text(encoding="utf-8")) or {}
    return {**_empty(), **data}


@contextmanager
def _locked(doc_dir: Path):
    d = label_dir(doc_dir)
    d.mkdir(exist_ok=True)
    with (Path(doc_dir) / ".labels.lock").open(
        "a"
    ) as lf:  # outside label/, so it is never committed
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            data = read(doc_dir)
            yield data
            data["labels"].sort(key=lambda r: (r.get("start", 0), r.get("key", "")))
            data["annotations"].sort(key=lambda r: (r.get("start", 0), r.get("id", "")))
            if not isinstance(data.get("document"), list):
                data["document"] = []
            data["document"].sort(key=lambda r: r.get("created") or "")
            tmp = d / (LABELS_FILE + ".tmp")
            tmp.write_text(
                json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
            )
            tmp.replace(d / LABELS_FILE)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def _check_text(span: dict) -> None:
    from evid.core.pdf_text import has_bad_chars

    if has_bad_chars(span["text"]):
        msg = "the passage holds characters that are not text (an unmapped glyph); it cannot be cited"
        raise ValueError(msg)


def span_at(doc_dir: Path, start: int, end: int) -> dict:
    text, pages = ensure_text(doc_dir)
    span = make_span(text, int(start), int(end), pages)
    _check_text(span)
    return span


def span_of(
    doc_dir: Path, passage: str, min_ratio: float = 0.92
) -> tuple[dict, float, str]:
    """A span for a passage given as text: ``(span, score, how)``; ValueError if not found."""
    text, pages = ensure_text(doc_dir)
    found = locate(passage, text, min_ratio)
    if not found:
        msg = f"the passage is not in the document's text (needs a match of {min_ratio:.2f} or better)"
        raise ValueError(msg)
    start, end, score, how = found
    span = make_span(text, start, end, pages)
    _check_text(span)
    return span, score, how


def _note(text: str, by: str) -> dict:
    return {"at": _now(), "by": by, "text": text.strip()}


def _check_key(key: str) -> str:
    key = (key or "").strip()
    if not key or any(c in key for c in " \t\n:\"'"):
        msg = f"bad label key {key!r}: use letters, digits, - and _"
        raise ValueError(msg)
    return key


def _taken_keys(data: dict) -> set[str]:
    """Label keys already used, on a span or on the whole document."""
    keys = {r["key"] for r in data.get("labels") or [] if r.get("key")}
    for rec in data.get("document") or []:
        if rec.get("kind") == "label" and rec.get("key"):
            keys.add(rec["key"])
    return keys


def taken_keys(doc_dir: Path) -> set[str]:
    return _taken_keys(read(doc_dir))


def add_label(
    doc_dir: Path, span: dict, key: str, note: str = "", by: str = "you"
) -> dict:
    key = _check_key(key)
    with _locked(doc_dir) as data:
        if key in _taken_keys(data):
            msg = f"there is already a label {key!r} in this document"
            raise ValueError(msg)
        rec = {
            **span,
            "key": key,
            "created": _now(),
            "by": by,
            "notes": [_note(note, by)] if note.strip() else [],
        }
        data["labels"].append(rec)
    return rec


def _find(items: list, field: str, value: str) -> dict:
    rec = next((r for r in items if r.get(field) == value), None)
    if rec is None:
        msg = f"no {'label' if field == 'key' else 'annotation'} {value!r}"
        raise KeyError(msg)
    return rec


def add_note(doc_dir: Path, key: str, text: str, by: str = "you") -> dict:
    if not text.strip():
        msg = "the note is empty"
        raise ValueError(msg)
    with _locked(doc_dir) as data:
        rec = _find(data["labels"], "key", key)
        rec.setdefault("notes", []).append(_note(text, by))
        return dict(rec)


def _note_slot(notes: list, index: int, owner: str) -> dict:
    if index < 0 or index >= len(notes):
        msg = f"no note {index} on {owner}"
        raise KeyError(msg)
    return notes[index]


def _rewrite_note(notes: list, index: int, text: str, owner: str) -> None:
    text = text.strip()
    if not text:
        msg = "the note is empty"
        raise ValueError(msg)
    note = _note_slot(notes, index, owner)
    if note.get("text") == text:
        return
    note["text"] = text
    note["at"] = _now()


def edit_note(doc_dir: Path, key: str, index: int, text: str) -> dict:
    """Replace the text of note *index* on label *key*. The author stays."""
    with _locked(doc_dir) as data:
        rec = _find(data["labels"], "key", key)
        _rewrite_note(rec.setdefault("notes", []), index, text, key)
        return dict(rec)


def remove_note(doc_dir: Path, key: str, index: int) -> dict:
    """Drop note *index* from label *key*. The label stays."""
    with _locked(doc_dir) as data:
        rec = _find(data["labels"], "key", key)
        notes = rec.setdefault("notes", [])
        _note_slot(notes, index, key)
        del notes[index]
        return dict(rec)


def remove_label(doc_dir: Path, key: str) -> None:
    with _locked(doc_dir) as data:
        _find(data["labels"], "key", key)
        data["labels"] = [r for r in data["labels"] if r["key"] != key]


def rename_label(doc_dir: Path, key: str, new: str) -> dict:
    new = _check_key(new)
    with _locked(doc_dir) as data:
        if new in _taken_keys(data):
            msg = f"there is already a label {new!r}"
            raise ValueError(msg)
        rec = _find(data["labels"], "key", key)
        rec["key"] = new
        return dict(rec)


def add_annotation(doc_dir: Path, span: dict, text: str, by: str = "you") -> dict:
    if not text.strip():
        msg = "the annotation is empty"
        raise ValueError(msg)
    with _locked(doc_dir) as data:
        rec = {
            **span,
            "id": secrets.token_hex(3),
            "created": _now(),
            "by": by,
            "notes": [_note(text, by)],
        }
        data["annotations"].append(rec)
    return rec


def annotate(doc_dir: Path, ann_id: str, text: str, by: str = "you") -> dict:
    if not text.strip():
        msg = "the note is empty"
        raise ValueError(msg)
    with _locked(doc_dir) as data:
        rec = _find(data["annotations"], "id", ann_id)
        rec.setdefault("notes", []).append(_note(text, by))
        return dict(rec)


def edit_annotation_note(doc_dir: Path, ann_id: str, index: int, text: str) -> dict:
    """Replace note *index* on an annotation. The author stays."""
    with _locked(doc_dir) as data:
        rec = _find(data["annotations"], "id", ann_id)
        _rewrite_note(rec.setdefault("notes", []), index, text, ann_id)
        return dict(rec)


def remove_annotation_note(doc_dir: Path, ann_id: str, index: int) -> dict | None:
    """Drop note *index*. The annotation goes away with its last note."""
    with _locked(doc_dir) as data:
        rec = _find(data["annotations"], "id", ann_id)
        notes = rec.setdefault("notes", [])
        _note_slot(notes, index, ann_id)
        del notes[index]
        if notes:
            return dict(rec)
        data["annotations"] = [r for r in data["annotations"] if r["id"] != ann_id]
        return None


def remove_annotation(doc_dir: Path, ann_id: str) -> None:
    with _locked(doc_dir) as data:
        _find(data["annotations"], "id", ann_id)
        data["annotations"] = [r for r in data["annotations"] if r["id"] != ann_id]


def _document_record(kind: str, by: str, note: str, key: str = "") -> dict:
    rec = {
        "id": secrets.token_hex(3),
        "kind": kind,
        "created": _now(),
        "by": by,
        "notes": [_note(note, by)] if note.strip() else [],
    }
    if kind == "label":
        rec["key"] = key
    return rec


def add_document_label(
    doc_dir: Path, key: str, note: str = "", by: str = "you"
) -> dict:
    """A label on the whole document: a key and dated notes, no span."""
    key = _check_key(key)
    with _locked(doc_dir) as data:
        if key in _taken_keys(data):
            msg = f"there is already a label {key!r} in this document"
            raise ValueError(msg)
        rec = _document_record("label", by, note, key)
        data["document"].append(rec)
    return rec


def add_document_annotation(doc_dir: Path, text: str, by: str = "you") -> dict:
    """An annotation on the whole document: dated notes, no key and no span."""
    if not text.strip():
        msg = "the annotation is empty"
        raise ValueError(msg)
    with _locked(doc_dir) as data:
        rec = _document_record("annotation", by, text)
        data["document"].append(rec)
    return rec


def _document(data: dict, rec_id: str) -> dict:
    rec = _find(data["document"], "id", rec_id)
    return rec


def add_document_note(doc_dir: Path, rec_id: str, text: str, by: str = "you") -> dict:
    if not text.strip():
        msg = "the note is empty"
        raise ValueError(msg)
    with _locked(doc_dir) as data:
        rec = _document(data, rec_id)
        rec.setdefault("notes", []).append(_note(text, by))
        return dict(rec)


def edit_document_note(doc_dir: Path, rec_id: str, index: int, text: str) -> dict:
    """Replace note *index*. The author stays; ``at`` changes only when the text does."""
    with _locked(doc_dir) as data:
        rec = _document(data, rec_id)
        _rewrite_note(rec.setdefault("notes", []), index, text, rec_id)
        return dict(rec)


def remove_document_note(doc_dir: Path, rec_id: str, index: int) -> dict | None:
    """Drop note *index*. An annotation goes away with its last note; a label stays."""
    with _locked(doc_dir) as data:
        rec = _document(data, rec_id)
        notes = rec.setdefault("notes", [])
        _note_slot(notes, index, rec_id)
        del notes[index]
        if rec.get("kind") == "annotation" and not notes:
            data["document"] = [r for r in data["document"] if r.get("id") != rec_id]
            return None
        return dict(rec)


def rename_document_label(doc_dir: Path, rec_id: str, new: str) -> dict:
    new = _check_key(new)
    with _locked(doc_dir) as data:
        rec = _document(data, rec_id)
        if rec.get("kind") != "label":
            msg = "only a document label has a key"
            raise ValueError(msg)
        if new in _taken_keys(data):
            msg = f"there is already a label {new!r}"
            raise ValueError(msg)
        rec["key"] = new
        return dict(rec)


def remove_document(doc_dir: Path, rec_id: str) -> None:
    with _locked(doc_dir) as data:
        _document(data, rec_id)
        data["document"] = [r for r in data["document"] if r.get("id") != rec_id]


def clear_document_annotations(doc_dir: Path) -> int:
    """Remove whole-document annotations. Keyed document labels stay."""
    with _locked(doc_dir) as data:
        before = [r for r in data["document"] if r.get("kind") == "annotation"]
        data["document"] = [
            r for r in data["document"] if r.get("kind") != "annotation"
        ]
    return len(before)


def adopt_legacy_document_note(doc_dir: Path) -> bool:
    """Move the old single document note into one whole-document annotation.

    The old note is ``annotations.yml`` key ``.``, or the ``notes`` string in
    ``evid_meta.yml`` until a note was written here. It is cleared afterwards,
    so deleting the new record does not bring the old string back. A record
    that already has this text is left as it is. Returns whether a record
    was added.
    """
    from evid.core.annotations import DOC, read_annotations, write_annotation

    legacy = (read_annotations(doc_dir).get(DOC) or "").strip()
    if not legacy:
        return False
    with _locked(doc_dir) as data:
        already = any(
            (notes_text(r).strip() == legacy)
            for r in data["document"]
            if isinstance(r, dict)
        )
        if not already:
            data["document"].append(_document_record("annotation", "you", legacy))
        made = not already
    write_annotation(doc_dir, DOC, "")
    return made


def document_blurb(doc_dir: Path, legacy: str | None = None) -> str:
    """Whole-document notes joined, oldest first, else the legacy single note.

    Pass *legacy* when the caller already read it, so a document list does not
    open ``annotations.yml`` again. ``None`` reads it.
    """
    parts: list[str] = []
    path = label_dir(doc_dir) / LABELS_FILE
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            data = {}
        if isinstance(data, dict):
            for rec in data.get("document") or []:
                if isinstance(rec, dict):
                    text = notes_text(rec)
                    if text:
                        parts.append(text)
    if legacy is None:
        from evid.core.annotations import DOC, read_annotations

        legacy = read_annotations(doc_dir).get(DOC) or ""
    legacy = (legacy or "").strip()
    if legacy and all(legacy != part.strip() for part in parts):
        parts.append(legacy)
    return "\n".join(parts)


def notes_text(rec: dict) -> str:
    """A record's notes as one string, oldest first."""
    return "\n".join(n.get("text", "") for n in rec.get("notes") or [] if n.get("text"))


_KEY_WORDS = 3  # first words of a passage, same as the GUI's labKey
_KEY_SUFFIX_FROM = 2


def suggest_key(text: str, taken: set[str] | None = None) -> str:
    """A label key from the passage's first words, unique among *taken*."""
    norm = unicodedata.normalize("NFKD", text or "")
    norm = "".join(c for c in norm if not unicodedata.combining(c)).lower()
    norm = norm.replace("æ", "ae").replace("ø", "oe").replace("å", "aa")
    words = re.findall(r"[a-z0-9]+", norm)
    base = "-".join(words[:_KEY_WORDS]) or "label"
    have = set(taken or ())
    if base not in have:
        return base
    n = _KEY_SUFFIX_FROM
    while f"{base}-{n}" in have:
        n += 1
    return f"{base}-{n}"


def paragraph_spans(text: str, pages) -> list[dict]:
    """One span per blank-line paragraph (the same split the old autolabel used)."""
    spans = []
    offset = 0
    parts = text.split("\n\n")
    last = len(parts) - 1
    for i, part in enumerate(parts):
        stripped = part.strip()
        if stripped:
            rel = part.find(stripped)
            start = offset + rel
            spans.append(make_span(text, start, start + len(stripped), pages))
        offset += len(part)
        if i != last:
            offset += len("\n\n")
    return spans


def autolabel(doc_dir: Path, by: str = "you") -> list[dict]:
    """One label per paragraph of the canonical text. Keys are ``lab1``, ``lab2``, ….

    A paragraph that is not citable text (an unmapped glyph) is skipped.
    """
    import logging

    text, pages = ensure_text(doc_dir)
    taken = taken_keys(doc_dir)
    made: list[dict] = []
    seq = 0
    for span in paragraph_spans(text, pages):
        try:
            _check_text(span)
        except ValueError:
            logging.getLogger(__name__).warning(
                "skipped a paragraph that is not citable text"
            )
            continue
        seq += 1
        while f"lab{seq}" in taken:
            seq += 1
        key = f"lab{seq}"
        made.append(add_label(doc_dir, span, key, by=by))
        taken.add(key)
    return made


def label_entries(doc_dir: Path) -> list[tuple[str, dict]]:
    """``(key, value)`` pairs in the shape the quote exporters read (text, note, opage)."""
    return [
        (
            r["key"],
            {
                "key": r["key"],
                "text": r["text"],
                "note": notes_text(r),
                "opage": r.get("page"),
                "start": r["start"],
                "end": r["end"],
            },
        )
        for r in read(doc_dir)["labels"]
        if not r.get("lost")
    ]
