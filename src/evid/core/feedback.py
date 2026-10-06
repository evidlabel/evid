"""Requests to the agent about documents of a set, and the agent's answers.

As treedit's feedback: a person asks something about a document (or a file in
its folder) — "check the date of this letter", "label the findings on p. 4" —
and the agent working on the set lists the open requests (``evid fb ls``),
does the work, and answers each with ``evid fb reply ID "…" --done``.

Kept per set in ``sets/<slug>/feedback.yml``, a list of

    id: 3                 # unique in the set
    uuid: 9e0b…           # the document
    path: "."             # "." for the document, else a file in its folder
    text: the request
    status: open | done
    reply: the agent's answer ("" until answered)
    created / updated: ISO times

Writes take an exclusive lock on the file, so the GUI and an agent's CLI can
both write.
"""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import yaml

FEEDBACK_FILE = "feedback.yml"
STATUSES = ("open", "done")


def _now() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(
    str,
    lambda d, s: d.represent_scalar(
        "tag:yaml.org,2002:str", s, style="|" if "\n" in s else None
    ),
)


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [dict(x) for x in data if isinstance(x, dict) and "id" in x]


def read(set_dir: Path) -> list[dict]:
    """All requests of the set, oldest first."""
    return _load(Path(set_dir) / FEEDBACK_FILE)


@contextmanager
def _locked(set_dir: Path):
    """Read-modify-write under an exclusive lock; yields the list to change."""
    path = Path(set_dir) / FEEDBACK_FILE
    lock = Path(set_dir) / ".feedback.lock"
    with lock.open("a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            items = _load(path)
            yield items
            tmp = path.with_suffix(".yml.tmp")
            tmp.write_text(
                yaml.dump(
                    items,
                    Dumper=_Dumper,
                    allow_unicode=True,
                    sort_keys=False,
                    width=2**20,
                ),
                encoding="utf-8",
            )
            tmp.replace(path)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def add(set_dir: Path, uuid: str, text: str, path: str = ".") -> dict:
    text = (text or "").rstrip()
    if not text.strip():
        msg = "the request is empty"
        raise ValueError(msg)
    with _locked(set_dir) as items:
        now = _now()
        item = {
            "id": max((x["id"] for x in items), default=0) + 1,
            "uuid": uuid,
            "path": path or ".",
            "text": text,
            "status": "open",
            "reply": "",
            "created": now,
            "updated": now,
        }
        items.append(item)
    return item


def update(
    set_dir: Path,
    fid: int,
    *,
    text: str | None = None,
    status: str | None = None,
    reply: str | None = None,
) -> dict:
    if status is not None and status not in STATUSES:
        msg = f"status must be one of {', '.join(STATUSES)}"
        raise ValueError(msg)
    with _locked(set_dir) as items:
        item = next((x for x in items if x["id"] == int(fid)), None)
        if item is None:
            msg = f"no request #{fid}"
            raise KeyError(msg)
        for key, value in (("text", text), ("status", status), ("reply", reply)):
            if value is not None:
                item[key] = str(value).rstrip()
        item["updated"] = _now()
        return dict(item)


def delete(set_dir: Path, fid: int) -> None:
    with _locked(set_dir) as items:
        keep = [x for x in items if x["id"] != int(fid)]
        if len(keep) == len(items):
            msg = f"no request #{fid}"
            raise KeyError(msg)
        items[:] = keep


def open_counts(items: list[dict]) -> dict[str, int]:
    """{uuid: number of open requests}."""
    out: dict[str, int] = {}
    for x in items:
        if x.get("status") != "done":
            out[x["uuid"]] = out.get(x["uuid"], 0) + 1
    return out
