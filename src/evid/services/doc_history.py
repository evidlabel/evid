"""The git history of one document, summarised for people.

Works wherever the document folder sits in a git work tree (a set tracked with
``evid set track``, or a case repo around ``evid/``). Each commit that touched
the folder becomes an entry saying what happened to the document:

- ``details``: info.yml fields that changed (title, tags, …)
- ``notes``: annotations added, changed or removed (per path)
- ``labels``: keys added or removed in label/labels.json (span labels and
  whole-document labels), notes added, and whole-document annotations added
  or removed (``documents``)
- ``passes``: machine-quote passes added (pass/*.json: job, matched/tried)
- ``added`` / ``files``: the document appearing, other files touched

Uncommitted changes in the folder come first, as an entry without a commit.
Plain ``git`` subprocesses; nothing is written.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DETAIL_FILES = {"info.yml"}
NOTE_FILES = {"annotations.yml"}
QUIET = {
    "label.json",
    "label.bib",
    "evid_meta.yml",
    "evidmgr_meta.yml",
}  # regenerated / bookkeeping


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=20,
    )


def _wanted(name: str) -> bool:
    """Only these files are read; the rest (PDFs, …) are summarised by name."""
    return (
        name in DETAIL_FILES
        or name in NOTE_FILES
        or name == "label/labels.json"
        or (name.startswith("pass/") and name.endswith(".json"))
    )


def _show(top: Path, rev: str, path: str) -> str | None:
    r = _git(top, "show", f"{rev}:{path}")
    return r.stdout if r.returncode == 0 else None


def _read(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _doc_preview(rec: dict) -> str:
    for note in rec.get("notes") or []:
        if not isinstance(note, dict):
            continue
        text = " ".join(str(note.get("text") or "").split())
        if text:
            return text if len(text) <= 48 else text[:47] + "…"
    return str(rec.get("id") or "annotation")


def _label_state(
    text: str | None,
) -> tuple[list[str], dict[str, int], dict[str, tuple[int, str]]]:
    """Label keys in file order, notes per key, and whole-document annotations.

    A whole-document label shares the key list with span labels (keys are
    unique across both). An annotation has no key: ``id -> (note count, preview)``.
    """
    try:
        data = json.loads(text or "")
    except ValueError:
        return [], {}, {}
    if not isinstance(data, dict):
        return [], {}, {}
    keys: list[str] = []
    notes: dict[str, int] = {}
    anns: dict[str, tuple[int, str]] = {}
    for rec in data.get("labels") or []:
        if not isinstance(rec, dict) or not rec.get("key"):
            continue
        key = str(rec["key"])
        keys.append(key)
        notes[key] = len(rec.get("notes") or [])
    for rec in data.get("document") or []:
        if not isinstance(rec, dict):
            continue
        if rec.get("kind") == "label" and rec.get("key"):
            key = str(rec["key"])
            if key not in notes:
                keys.append(key)
            notes[key] = notes.get(key, 0) + len(rec.get("notes") or [])
        elif rec.get("kind") == "annotation" and rec.get("id"):
            anns[str(rec["id"])] = (len(rec.get("notes") or []), _doc_preview(rec))
    return keys, notes, anns


def _yaml(text: str | None) -> dict:
    if not text:
        return {}
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _changed_keys(old: dict, new: dict) -> list[str]:
    return sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))


def summarise(
    name: str, status: str, old: str | None, new: str | None
) -> dict[str, Any] | None:
    """What a change to one file of the document means (None: nothing worth showing)."""
    base = name.rsplit("/", 1)[-1]
    if name in DETAIL_FILES:
        if status == "A":
            return {"kind": "added"}
        keys = [k for k in _changed_keys(_yaml(old), _yaml(new)) if k != "uuid"]
        return {"kind": "details", "fields": keys} if keys else None
    if name in NOTE_FILES:
        paths = _changed_keys(_yaml(old), _yaml(new))
        return (
            {
                "kind": "notes",
                "paths": ["the document" if p == "." else p for p in paths],
            }
            if paths
            else None
        )
    if name == "label/labels.json":
        before, before_n, before_d = _label_state(old)
        after, after_n, after_d = _label_state(new)
        added = [k for k in after if k not in before]
        removed = [k for k in before if k not in after]
        noted = [k for k in after if k in before_n and after_n[k] > before_n[k]]
        documents = []
        for ann_id, (count, preview) in after_d.items():
            prev = before_d.get(ann_id)
            if prev is None:
                documents.append(f"+ doc: {preview}")
            elif count > prev[0]:
                documents.append(f"note on doc: {preview}")
        for ann_id, (_count, preview) in before_d.items():
            if ann_id not in after_d:
                documents.append(f"- doc: {preview}")
        if not (added or removed or noted or documents):
            return None
        item: dict[str, Any] = {
            "kind": "labels",
            "file": name,
            "added": added,
            "removed": removed,
        }
        if noted:
            item["notes"] = noted
        if documents:
            item["documents"] = documents
        return item
    if name.startswith("pass/") and name.endswith(".json") and status[:1] == "A":
        try:
            p = json.loads(new or "{}")
        except ValueError:
            p = {}
        results = p.get("results") or []
        return {
            "kind": "pass",
            "id": p.get("id") or base[:-5],
            "job": p.get("job") or "",
            "model": p.get("model") or "",
            "matched": sum(1 for x in results if x.get("matched")),
            "tried": len(results),
        }
    if name in QUIET or name == "machine.hayagriva":
        return None
    word = {"A": "added", "D": "removed", "M": "edited"}.get(status[:1], "changed")
    return {"kind": "files", "files": [name], "what": word}


def _merge_files(items: list[dict]) -> list[dict]:
    """One 'files' item per verb instead of one per file; no file list when the doc was just added."""
    is_new = any(it["kind"] == "added" for it in items)
    out, groups = [], {}
    for it in items:
        if is_new and it["kind"] == "files" and it["what"] == "added":
            continue
        if it["kind"] != "files":
            out.append(it)
            continue
        g = groups.get(it["what"])
        if g is None:
            g = groups[it["what"]] = {"kind": "files", "what": it["what"], "files": []}
            out.append(g)
        g["files"].extend(it["files"])
    return sorted(out, key=lambda it: it["kind"] != "added")  # "document added" first


def doc_history(doc_dir: Path, limit: int = 50) -> dict[str, Any]:
    """{tracked, root, entries: [{commit?, short?, date, author?, subject?, items}]}."""
    doc_dir = Path(doc_dir).resolve()
    top_r = _git(doc_dir, "rev-parse", "--show-toplevel")
    if top_r.returncode != 0:
        return {"tracked": False, "entries": []}
    top = Path(top_r.stdout.strip())
    rel = doc_dir.relative_to(top).as_posix()
    entries: list[dict] = []

    # uncommitted changes first
    st = _git(top, "status", "--porcelain=v1", "--untracked-files=all", "--", rel)
    items = []
    for line in st.stdout.splitlines():
        code, path = line[:2], line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        name = path[len(rel) + 1 :] if path.startswith(rel + "/") else path
        status = "A" if "?" in code or "A" in code else "D" if "D" in code else "M"
        want = _wanted(name)
        old = None if status == "A" or not want else _show(top, "HEAD", path)
        new = None if status == "D" or not want else _read(top / path)
        s = summarise(name, status, old, new)
        if s:
            items.append(s)
    if items:
        entries.append(
            {"commit": None, "uncommitted": True, "items": _merge_files(items)}
        )

    log = _git(
        top,
        "log",
        f"-n{limit}",
        "--name-status",
        "--no-renames",
        "--format=%x1e%H%x1f%h%x1f%aI%x1f%an%x1f%s",
        "--",
        rel,
    )
    if log.returncode != 0:
        return {
            "tracked": True,
            "root": str(top),
            "entries": entries,
            "error": log.stderr.strip(),
        }
    for block in log.stdout.split("\x1e")[1:]:
        head, *rest = block.strip("\n").split("\n")
        full, short, date, author, subject = (head.split("\x1f") + [""] * 5)[:5]
        items = []
        for line in rest:
            if not line.strip():
                continue
            status, path = line.split("\t", 1)
            name = path[len(rel) + 1 :] if path.startswith(rel + "/") else path
            want = _wanted(name)
            old = None if status == "A" or not want else _show(top, f"{full}^", path)
            new = None if status == "D" or not want else _show(top, full, path)
            s = summarise(name, status, old, new)
            if s:
                items.append(s)
        entries.append(
            {
                "commit": full,
                "short": short,
                "date": date,
                "author": author,
                "subject": subject,
                "items": _merge_files(items),
            }
        )
    return {"tracked": True, "root": str(top), "entries": entries}
