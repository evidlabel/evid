"""The git history of one document, summarised for people.

Works wherever the document folder sits in a git work tree (a set tracked with
``evid set track``, or a case repo around ``evid/``). Each commit that touched
the folder becomes an entry saying what happened to the document:

- ``details``: info.yml fields that changed (title, tags, …)
- ``notes``: annotations added, changed or removed (per path)
- ``labels``: ``#lab`` keys added / removed in label.typ
- ``passes``: machine-quote passes added (machine/*.json: job, matched/tried)
- ``added`` / ``files``: the document appearing, other files touched

Uncommitted changes in the folder come first, as an entry without a commit.
Plain ``git`` subprocesses; nothing is written.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

LAB_KEY = re.compile(r'#lab\(\s*"((?:[^"\\]|\\.)*)"')
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
        or name.endswith(".typ")
        or (name.startswith("machine/") and name.endswith(".json"))
    )


def _show(top: Path, rev: str, path: str) -> str | None:
    r = _git(top, "show", f"{rev}:{path}")
    return r.stdout if r.returncode == 0 else None


def _read(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def lab_keys(text: str | None) -> list[str]:
    return LAB_KEY.findall(text or "")


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
    if base.endswith(".typ"):
        before, after = lab_keys(old), lab_keys(new)
        added = [k for k in after if k not in before]
        removed = [k for k in before if k not in after]
        if added or removed:
            return {"kind": "labels", "file": name, "added": added, "removed": removed}
        word = {"A": "added", "D": "removed"}.get(status[:1], "edited")
        return {"kind": "files", "files": [name], "what": word}
    if name.startswith("machine/") and name.endswith(".json") and status == "A":
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
