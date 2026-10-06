"""Human labels on a document's plain text (evid 0.7; no Typst).

A document's ``label/`` folder holds:

- ``text.txt``: the canonical plain text — the PDF's extracted text (ligatures
  expanded, end-of-line hyphens joined per page). Written once and then frozen,
  so the spans that point into it never drift. It is tracked in git.
- ``pages.json``: ``{"schema": 1, "pages": [[offset, page], …], "sha256": …}``,
  where each page starts in ``text.txt``.
- ``labels.json``: ``{"schema": 1, "labels": […], "annotations": […]}``.
  A label is a span (see :mod:`evid.core.spans`) with a ``key`` and a growing
  list of dated ``notes``; an annotation is a span with notes but no key — a
  comment on a passage made while reading.

Everything is verbatim: a record's ``text`` is always ``text.txt[start:end]``.
Writes are atomic and take a lock, so the GUI and an agent's CLI can both write.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import secrets
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
    """The canonical text, extracting it from the document's PDF (or .txt) once."""
    if has_text(doc_dir):
        return read_text(doc_dir)
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
        for kind in ("labels", "annotations"):
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
    return {"schema": SCHEMA, "labels": [], "annotations": []}


def read(doc_dir: Path) -> dict[str, Any]:
    """``{"labels": […], "annotations": […]}`` (empty when there are none)."""
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


def add_label(
    doc_dir: Path, span: dict, key: str, note: str = "", by: str = "you"
) -> dict:
    key = (key or "").strip()
    if not key or any(c in key for c in " \t\n:\"'"):
        msg = f"bad label key {key!r}: use letters, digits, - and _"
        raise ValueError(msg)
    with _locked(doc_dir) as data:
        if any(r["key"] == key for r in data["labels"]):
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


def remove_label(doc_dir: Path, key: str) -> None:
    with _locked(doc_dir) as data:
        _find(data["labels"], "key", key)
        data["labels"] = [r for r in data["labels"] if r["key"] != key]


def rename_label(doc_dir: Path, key: str, new: str) -> dict:
    new = new.strip()
    if not new or any(c in new for c in " \t\n:\"'"):
        msg = f"bad label key {new!r}"
        raise ValueError(msg)
    with _locked(doc_dir) as data:
        if any(r["key"] == new for r in data["labels"]):
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


def remove_annotation(doc_dir: Path, ann_id: str) -> None:
    with _locked(doc_dir) as data:
        _find(data["annotations"], "id", ann_id)
        data["annotations"] = [r for r in data["annotations"] if r["id"] != ann_id]


def notes_text(rec: dict) -> str:
    """A record's notes as one string, oldest first."""
    return "\n".join(n.get("text", "") for n in rec.get("notes") or [] if n.get("text"))


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
