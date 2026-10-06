"""`evid label` — human labels as spans over a document's plain text.

The commands write ``label/labels.json`` and, when the set is in git, commit
``label/`` and ``pass/``. They never write ``label.typ``.
"""

from __future__ import annotations

import json
import sys

from rich.console import Console
from rich.table import Table

from evid.cli.callbacks import DIRECTORY, _resolve_dataset
from evid.cli.dataset import docs_dir
from evid.cli.evidence import select_evidence
from evid.core.bibtex_utils import load_title
from evid.core.gitops import commit_labels
from evid.core.labels import (
    add_annotation,
    add_label,
    add_note,
    autolabel,
    ensure_text,
    read,
    remove_label,
    rename_label,
    span_of,
    suggest_key,
)

_SHOW_KEYS = 6  # list the keys in the commit message up to this many

_PREVIEW = 72


def commit_doc_labels(doc_dir, message: str) -> str | None:
    """Commit ``label/`` and ``pass/`` for one document. No git: nothing happens."""
    return commit_labels(doc_dir, message)


def _title(doc_dir) -> str:
    return load_title(doc_dir / "info.yml") or doc_dir.name[:8]


def _doc(dataset: str | None, uuid: str | None, prompt: str):
    dataset = _resolve_dataset(dataset, prompt, allow_create=False)
    if not uuid:
        uuid = select_evidence(DIRECTORY, dataset, prompt)
    doc_dir = docs_dir(DIRECTORY, dataset) / uuid
    if not doc_dir.is_dir():
        sys.exit(f"No document {uuid!r} in '{dataset}'.")
    return dataset, uuid, doc_dir


def _preview(text: str) -> str:
    flat = " ".join(text.split())
    if len(flat) <= _PREVIEW:
        return flat
    return flat[: _PREVIEW - 1] + "…"


def _rows(doc_dir) -> list[dict]:
    return [
        {
            "key": rec["key"],
            "page": rec.get("page"),
            "start": rec.get("start"),
            "end": rec.get("end"),
            "notes": len(rec.get("notes") or []),
            "text": rec.get("text") or "",
        }
        for rec in read(doc_dir)["labels"]
    ]


def label_ls_callback(
    db: str = None,
    dataset: str = None,
    uuid: str = None,
    format: str = "table",
):
    """List labels. Without -u, every document in the set."""
    dataset = _resolve_dataset(dataset, "Select dataset", allow_create=False)
    if uuid:
        _, uuid, doc_dir = _doc(dataset, uuid, "Select document")
        docs = [(uuid, doc_dir)]
    else:
        from evid.services.set_manager import SetManager

        docs = [(d.name, d) for d in SetManager(DIRECTORY).list_documents(dataset)]
    listed = [
        {"uuid": doc_uuid, **row}
        for doc_uuid, doc_dir in docs
        for row in _rows(doc_dir)
    ]
    if format == "json":
        print(json.dumps(listed, ensure_ascii=False, indent=2))
        return
    if not listed:
        print(f"No labels in {dataset}" + (f"/{uuid}" if uuid else "") + ".")
        return
    if format == "md":
        print(f"## Labels — {dataset}\n")
        for row in listed:
            print(
                f"- `{row['uuid'][:8]}` **{row['key']}** p.{row['page']} — {_preview(row['text'])}"
            )
        return
    console = Console()
    table = Table(title=f"labels: {dataset}", show_header=True)
    table.add_column("Doc")
    table.add_column("Key")
    table.add_column("Page", justify="right")
    table.add_column("Notes", justify="right")
    table.add_column("Text")
    for row in listed:
        table.add_row(
            row["uuid"][:8],
            row["key"],
            str(row["page"] or ""),
            str(row["notes"]),
            _preview(row["text"]),
        )
    console.print(table)


def label_add_callback(
    db: str = None,
    dataset: str = None,
    uuid: str = None,
    text: str = None,
    key: str = None,
    note: str = None,
):
    """Locate a verbatim passage and store it as a label."""
    if not text or not text.strip():
        sys.exit('Give the passage with --text "…" (it must occur in the document).')
    _dataset, uuid, doc_dir = _doc(dataset, uuid, "Select document to label")
    try:
        span, score, how = span_of(doc_dir, text)
        chosen = key or suggest_key(
            span["text"], {r["key"] for r in read(doc_dir)["labels"]}
        )
        rec = add_label(doc_dir, span, chosen, note=note or "")
    except (ValueError, KeyError) as exc:
        sys.exit(str(exc))
    detail = "" if how == "exact" else f"  {how} {score:.2f}"
    print(f"{rec['key']}  page {rec['page']}{detail}")
    commit_doc_labels(doc_dir, f"label: {_title(doc_dir)} (+{rec['key']})")


def label_note_callback(
    db: str = None,
    dataset: str = None,
    uuid: str = None,
    key: str = None,
    text: str = None,
):
    """Append a dated note to a label."""
    if not key or not text or not text.strip():
        sys.exit('Usage: evid label note -u UUID KEY "note"')
    _dataset, _uuid, doc_dir = _doc(dataset, uuid, "Select document")
    try:
        add_note(doc_dir, key, text)
    except (ValueError, KeyError) as exc:
        sys.exit(str(exc))
    print(f"{key}  note added")
    commit_doc_labels(doc_dir, f"label: {_title(doc_dir)} ({key} note)")


def label_rm_callback(
    db: str = None,
    dataset: str = None,
    uuid: str = None,
    key: str = None,
):
    """Remove a label. The passage stays in the text."""
    if not key:
        sys.exit("Usage: evid label rm -u UUID KEY")
    _dataset, _uuid, doc_dir = _doc(dataset, uuid, "Select document")
    try:
        remove_label(doc_dir, key)
    except KeyError as exc:
        sys.exit(str(exc))
    print(f"removed {key}")
    commit_doc_labels(doc_dir, f"label: {_title(doc_dir)} (-{key})")


def label_rename_callback(
    db: str = None,
    dataset: str = None,
    uuid: str = None,
    key: str = None,
    new: str = None,
):
    """Rename a label. The span stays where it is."""
    if not key or not new:
        sys.exit("Usage: evid label rename -u UUID KEY NEW")
    _dataset, _uuid, doc_dir = _doc(dataset, uuid, "Select document")
    try:
        rename_label(doc_dir, key, new)
    except (ValueError, KeyError) as exc:
        sys.exit(str(exc))
    print(f"{key} -> {new}")
    commit_doc_labels(doc_dir, f"label: {_title(doc_dir)} ({key} -> {new})")


def label_annotate_callback(
    db: str = None,
    dataset: str = None,
    uuid: str = None,
    text: str = None,
    comment: str = None,
):
    """Annotate a passage without giving it a citation key."""
    if not text or not text.strip() or not comment or not comment.strip():
        sys.exit('Usage: evid label annotate -u UUID --text "passage" "comment"')
    _dataset, _uuid, doc_dir = _doc(dataset, uuid, "Select document")
    try:
        span, score, how = span_of(doc_dir, text)
        rec = add_annotation(doc_dir, span, comment)
    except ValueError as exc:
        sys.exit(str(exc))
    detail = "" if how == "exact" else f"  {how} {score:.2f}"
    print(f"{rec['id']}  page {rec['page']}{detail}")
    commit_doc_labels(doc_dir, f"label: {_title(doc_dir)} (+annotation {rec['id']})")


def format_canonical(text: str, pages, page: int | None = None) -> str:
    """The canonical text with a marker at each page. *page* keeps just that page."""
    bounds = []
    for i, (start, no) in enumerate(pages):
        end = pages[i + 1][0] if i + 1 < len(pages) else len(text)
        bounds.append((no, start, end))
    chunks = []
    for no, start, end in bounds:
        if page is not None and no != page:
            continue
        body = text[start:end].strip("\n")
        chunks.append(f"— page {no} —\n\n{body}")
    if page is not None and not chunks:
        sys.exit(f"No page {page}.")
    return "\n\n".join(chunks) + ("\n" if chunks else "")


def label_text_callback(
    db: str = None,
    dataset: str = None,
    uuid: str = None,
    page: int = None,
):
    """Print the canonical text with page markers."""
    _dataset, _uuid, doc_dir = _doc(dataset, uuid, "Select document")
    try:
        text, pages = ensure_text(doc_dir)
    except (FileNotFoundError, ValueError) as exc:
        sys.exit(str(exc))
    print(format_canonical(text, pages, page), end="")


def write_paragraph_labels(doc_dir) -> int:
    """Label every paragraph, commit, and print how many. Returns the count."""
    try:
        recs = autolabel(doc_dir)
    except (FileNotFoundError, ValueError) as exc:
        sys.exit(str(exc))
    if not recs:
        print(f"No paragraphs to label in {doc_dir.name}.")
        return 0
    keys = [r["key"] for r in recs]
    shown = ",".join(keys) if len(keys) <= _SHOW_KEYS else f"{len(keys)} paragraphs"
    commit_doc_labels(doc_dir, f"label: {_title(doc_dir)} (+{shown})")
    print(f"Labelled {len(recs)} paragraph(s): {', '.join(keys)}")
    return len(recs)
