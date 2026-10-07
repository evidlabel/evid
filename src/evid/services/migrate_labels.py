"""Move a set's Typst labels and machine quotes onto ``label/`` spans.

``evid set migrate-labels`` reads ``label.typ`` (or ``label.json`` when that
extract is newer), locates each passage in the document's canonical text, and
writes ``label/labels.json``. Machine quotes in ``machine.hayagriva`` become
spans on the pass that named them. The old files move to ``legacy/``. A label
that cannot be placed is kept in ``label/migration.json``, not dropped.

Documents that already have a label are merged: a key already in
``label/labels.json`` is left as it is. Once the old files are in ``legacy/``,
a later run does not move them again. If that first commit missed the
deletions, the later run records them. A document removed from ``docs/`` stays
in HEAD.

Any set: ``evid set migrate-labels -s SET``. When the set is a git repository,
one commit records the new ``label/`` files and the removal of the old ones.
``legacy/label.typ`` stays tracked. ``legacy/label.json``, the bib files, and
``legacy/text.txt`` do not.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

from evid.core.gitops import work_tree
from evid.core.spans import locate, make_span

logger = logging.getLogger(__name__)

MIN_RATIO = 0.92
_QKEY = re.compile(r"q\d+")
_SERIAL = re.compile(r"chars\s+(\d+)\s*-\s*(\d+)")
_OLD_FILES = (
    "label.typ",
    "label.json",
    "label.bib",
    "label_table.bib",
    "machine.hayagriva",
    "text.txt",
)
# A pattern with a slash is relative to the set root, so `legacy/**/label.json`
# does not match `docs/<uuid>/legacy/label.json`. The leading `**/` does.
_GITIGNORE_BAD = (
    "legacy/**/label.json",
    "legacy/**/label.bib",
    "legacy/**/label_table.bib",
    "legacy/**/text.txt",
)
_GITIGNORE_GOOD = (
    "**/legacy/label.json",
    "**/legacy/label.bib",
    "**/legacy/label_table.bib",
    "**/legacy/text.txt",
)
_LEGACY_BYPRODUCTS = ("label.json", "label.bib", "label_table.bib", "text.txt")
_GITIGNORE_BLOCK = (
    "\n# evid 0.7 archive byproducts (legacy/label.typ stays tracked).\n"
    + "\n".join(_GITIGNORE_GOOD)
    + "\n"
)
# Re-include the new trees. A denylist that ignores every text.txt, and an
# allowlist that keeps only label.typ, both need these or the canonical text
# never gets committed. A parent directory that is ignored cannot be undone by
# a file pattern, so the directory is named before its contents.
_GITIGNORE_TRACK = """# evid 0.7 labels. Canonical label/text.txt and legacy/label.typ stay tracked.
!**/label/text.txt
!/docs/*/label/
!/docs/*/label/**
!/docs/*/pass/
!/docs/*/pass/**
!/docs/*/legacy/
!/docs/*/legacy/label.typ
!/docs/*/legacy/machine.hayagriva
!/docs/*/legacy/machine/
!/docs/*/legacy/machine/**
"""
_TRACK_MARKER = "!/docs/*/label/**"


@dataclass
class DocResult:
    uuid: str
    title: str = ""
    placed: int = 0
    fuzzy: int = 0
    unplaced: int = 0
    quotes: int = 0
    quotes_moved: int = 0
    already: int = 0
    text: bool = False  # label/text.txt written (search and labelling need it)
    skipped: str = ""
    error: str = ""
    details: list[str] = field(default_factory=list)


@dataclass
class Report:
    docs: list[DocResult] = field(default_factory=list)
    commit: str | None = None
    commit_error: str = ""

    @property
    def touched(self) -> list[DocResult]:
        return [d for d in self.docs if not d.skipped and not d.error]


def parse_typst_labs(text: str) -> list[dict]:
    """``#lab("key", "text", "note")`` calls, with Typst string escapes undone.

    A ``#`` in the document body (the old "unknown variable" failure) does not
    hide a call: only the quoted arguments are read, so the call is kept.
    """
    out = []
    i = 0
    while True:
        j = text.find("#lab(", i)
        if j < 0:
            break
        args, k = _lab_args(text, j + 5)
        if args is None:
            i = j + 5
            continue
        key, body, note = (_unescape(a) for a in args)
        out.append({"key": key.strip(), "text": body, "note": note})
        i = k
    return out


def parse_label_json(path: Path) -> list[dict]:
    """Labels from a typst-query ``label.json``, either shape.

    The query writes ``[{"value": {key, text|quote, note}}]``. A bare list or
    mapping of the same fields is accepted too. Empty or unreadable → ``[]``.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "null")
    except (OSError, json.JSONDecodeError):
        return []
    rows: list = []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        if "labels" in data and isinstance(data["labels"], list):
            rows = data["labels"]
        else:
            rows = [
                {"key": k, **v} if isinstance(v, dict) else {"key": k, "text": v}
                for k, v in data.items()
            ]
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = row.get("value") if isinstance(row.get("value"), dict) else row
        key = str(value.get("key") or "").strip()
        body = value.get("text") or value.get("quote") or ""
        if key and str(body).strip():
            out.append(
                {"key": key, "text": str(body), "note": str(value.get("note") or "")}
            )
    return out


def migrate_set(
    directory: Path,
    slug: str,
    *,
    dry_run: bool = False,
    on_doc: Callable[[DocResult], None] | None = None,
) -> Report:
    """Migrate every document of ``directory/sets/slug`` that still has old labels."""
    from evid.cli.dataset import set_dir

    root = set_dir(Path(directory), slug)
    docs_root = root / "docs"
    if not docs_root.is_dir():
        msg = f"Dataset '{slug}' has no docs directory ({docs_root})."
        raise FileNotFoundError(msg)
    report = Report()
    touched: list[Path] = []
    docs = sorted(p for p in docs_root.iterdir() if p.is_dir())
    for doc in docs:
        result = _migrate_doc(doc, dry_run=dry_run)
        report.docs.append(result)
        if on_doc is not None:
            on_doc(result)
        if not dry_run and not result.skipped and not result.error:
            touched.append(doc)
    if not dry_run and work_tree(root) is not None:
        # A finished migration has nothing to commit. An unfinished one still
        # has the old path in the index, or a new label file never committed.
        pending = _docs_needing_git_repair(root, docs_root)
        todo = list(dict.fromkeys([*touched, *pending]))
        if todo:
            _extend_gitignore(root)
            message = _message(report) if touched else _REPAIR_MESSAGE
            report.commit, report.commit_error = _commit(root, todo, message)
    return report


_REPAIR_MESSAGE = "record removal of archived label files"


def _migrate_doc(doc: Path, *, dry_run: bool) -> DocResult:
    from evid.core.bibtex_utils import load_title

    result = DocResult(uuid=doc.name, title=load_title(doc / "info.yml"))
    if not _has_old(doc):
        # An earlier run archived an unlabelled doc without writing its text,
        # which hid it from full-text and vector search. Write it now.
        result.text = _backfill_text(doc, dry_run=dry_run)
        if not result.text:
            result.skipped = "no old labels"
        return result
    # An empty label.typ and no machine quotes have nothing to locate. Archive
    # them even when the document has no PDF to extract; the canonical text is
    # still written when there is one, so the doc stays searchable.
    if not _source_labels(doc) and not _hayagriva_quotes(doc / "machine.hayagriva"):
        result.text = _backfill_text(doc, dry_run=dry_run)
        if not dry_run:
            _archive(doc)
        return result
    try:
        text, pages = _canonical(doc, dry_run=dry_run)
    except (OSError, ValueError, RuntimeError) as exc:
        result.error = str(exc)
        logger.warning("Could not read the text of %s: %s", doc.name, exc)
        return result
    old_text = _read_old_text(doc)
    when = _source_time(doc)
    labels, unplaced, already = _place_labels(doc, text, pages, when)
    quotes, quote_unplaced, quote_kept, quote_moved = _place_quotes(
        doc, text, pages, old_text
    )
    result.placed = sum(1 for h, _rec in labels if h != "fuzzy")
    result.fuzzy = sum(1 for h, _rec in labels if h == "fuzzy")
    result.already = already
    result.unplaced = len(unplaced) + len(quote_unplaced)
    result.quotes = quote_kept
    result.quotes_moved = quote_moved
    result.details = [
        f"{u.get('kind', 'label')} {u.get('key') or '(no key)'} ({float(u.get('score') or 0):.0%})"
        for u in (*unplaced, *quote_unplaced)
    ]
    if dry_run:
        return result
    _write(doc, labels, unplaced + quote_unplaced, quotes)
    _mark_unindexed(doc)
    _archive(doc)
    return result


def _has_old(doc: Path) -> bool:
    return any((doc / name).exists() for name in (*_OLD_FILES, "machine"))


def _backfill_text(doc: Path, *, dry_run: bool) -> bool:
    """Write ``label/text.txt`` from the doc's source when it is missing.

    True when it was written (or would be, in a dry run). A doc with no PDF or
    source text is left alone, with a warning.
    """
    from evid.core.labels import ensure_text, has_text
    from evid.services.doc_tags import resolve_doc_pdf

    if has_text(doc):
        return False
    if dry_run:
        return resolve_doc_pdf(doc) is not None or any(
            t.name != "text.txt" for t in doc.glob("*.txt")
        )
    try:
        ensure_text(doc)
    except (OSError, ValueError, RuntimeError) as exc:
        logger.warning("No canonical text for %s: %s", doc.name, exc)
        return False
    _mark_unindexed(doc)
    return True


def _canonical(doc: Path, *, dry_run: bool) -> tuple[str, list]:
    from evid.core.labels import ensure_text, has_text, read_text

    if dry_run:
        if has_text(doc):
            return read_text(doc)
        from evid.core.quote_extract import _read_source

        text, pages = _read_source(doc)
        return text, [list(p) for p in pages]
    text, pages = ensure_text(doc)
    return text, pages


def _read_old_text(doc: Path) -> str | None:
    path = doc / "text.txt"
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _source_time(doc: Path) -> str:
    """When the labels were written, from the file the records come from."""
    typ, js = doc / "label.typ", doc / "label.json"
    src = js if _prefer_json(doc) else typ if typ.exists() else js
    if not src.exists():
        src = doc / "machine.hayagriva"
    if not src.exists():
        return datetime.now(tz=UTC).isoformat(timespec="seconds")
    return datetime.fromtimestamp(src.stat().st_mtime, tz=UTC).isoformat(
        timespec="seconds"
    )


def _prefer_json(doc: Path) -> bool:
    """``label.json`` wins when it is newer than ``label.typ`` and it has labels."""
    js, typ = doc / "label.json", doc / "label.typ"
    if not js.is_file() or js.stat().st_size <= 2:
        return False
    if typ.is_file() and typ.stat().st_mtime > js.stat().st_mtime:
        return False
    return bool(parse_label_json(js))


def _source_labels(doc: Path) -> list[dict]:
    if _prefer_json(doc):
        return parse_label_json(doc / "label.json")
    typ = doc / "label.typ"
    if typ.is_file():
        try:
            return parse_typst_labs(typ.read_text(encoding="utf-8"))
        except OSError as exc:
            logger.warning("Could not read %s: %s", typ, exc)
    js = doc / "label.json"
    return parse_label_json(js) if js.is_file() else []


def _place_labels(
    doc: Path, text: str, pages, when: str
) -> tuple[list[tuple[str, dict]], list[dict], int]:
    from evid.core.labels import read
    from evid.core.pdf_text import has_bad_chars

    have = {r.get("key") for r in read(doc)["labels"]}
    placed: list[tuple[str, dict]] = []
    unplaced: list[dict] = []
    seen = set(have)
    already = 0
    for src in _source_labels(doc):
        key, body, note = src["key"], src["text"], src.get("note") or ""
        if not key or any(c in key for c in " \t\n:\"'"):
            unplaced.append(_lost("label", key, body, note, 0.0))
            continue
        if key in seen:
            if key in have:
                already += 1
            continue
        seen.add(key)
        found = locate(body, text, MIN_RATIO) if body.strip() else None
        if not found:
            unplaced.append(_lost("label", key, body, note, _best_score(body, text)))
            continue
        start, end, score, how = found
        try:
            span = make_span(text, start, end, pages)
        except ValueError:
            unplaced.append(_lost("label", key, body, note, score))
            continue
        if has_bad_chars(span["text"]):
            unplaced.append(_lost("label", key, body, note, score))
            continue
        rec = {
            **span,
            "key": key,
            "created": when,
            "by": "migration",
            "notes": [{"at": when, "by": "migration", "text": note.strip()}]
            if note.strip()
            else [],
        }
        placed.append((how, rec))
    return placed, unplaced, already


def _place_quotes(doc: Path, text: str, pages, old_text: str | None):
    """``(pass writes, unplaced, kept-by-offset, re-anchored)``."""
    from evid.core.quote_pass import QuotePass, load_pass

    entries = _hayagriva_quotes(doc / "machine.hayagriva")
    passes = _load_passes(doc)
    found_for: dict[str, list[dict]] = {name: [] for name, _qp in passes}
    unplaced = []
    kept = moved = 0
    used: set[str] = set()
    for entry in entries:
        qkey = entry["qkey"]
        if qkey in used:
            unplaced.append(_lost("machine", qkey, entry["text"], "", 0.0))
            continue
        used.add(qkey)
        span, how = _quote_span(entry, text, pages, old_text)
        if span is None:
            unplaced.append(
                _lost(
                    "machine", qkey, entry["text"], "", _best_score(entry["text"], text)
                )
            )
            continue
        span = {
            **span,
            "key": qkey,
            "score": round(entry.get("score") or (1.0 if how == "same" else 0.0), 4),
        }
        if how == "same":
            kept += 1
        else:
            moved += 1
            span["score"] = round(_best_score(entry["text"], text) or span["score"], 4)
        name = _pass_for(qkey, entry["hay_key"], passes)
        if name is None:
            name = "_migrated"
            found_for.setdefault(name, [])
        found_for[name].append(span)
    writes: list[tuple[str, QuotePass]] = []
    for name, qp in passes:
        extra = found_for.get(name) or []
        if not extra:
            continue
        have = {q.get("key") for q in qp.found}
        qp.found = [*qp.found, *[s for s in extra if s["key"] not in have]]
        writes.append((name, qp))
    migrated = found_for.get("_migrated") or []
    if migrated:
        writes.append((_migrated_name(doc), _migrated_pass(doc, migrated)))
    return writes, unplaced, kept, moved


def _quote_span(
    entry: dict, text: str, pages, old_text: str | None
) -> tuple[dict | None, str]:
    start, end = entry.get("start"), entry.get("end")
    title = (entry.get("text") or "").strip()
    if (
        start is not None
        and end is not None
        and old_text is not None
        and 0 <= start < end <= len(old_text)
        and old_text[start:end].strip() == title
        and 0 <= start < end <= len(text)
        and text[start:end].strip() == title
    ):
        try:
            return make_span(text, start, end, pages), "same"
        except ValueError:
            pass
    found = locate(title, text, MIN_RATIO) if title else None
    if not found:
        return None, "lost"
    a, b, _score, how = found
    try:
        return make_span(text, a, b, pages), how
    except ValueError:
        return None, "lost"


def _hayagriva_quotes(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return []
    if not isinstance(data, dict):
        return []
    out = []
    for key, item in data.items():
        if not isinstance(item, dict):
            continue
        part = str(key).split(":")[-1]
        if not _QKEY.fullmatch(part):
            continue
        title = item.get("title") or ""
        start = end = None
        serial = str(item.get("serial-number") or "")
        m = _SERIAL.search(serial)
        if m:
            start, end = int(m.group(1)), int(m.group(2))
        out.append(
            {
                "hay_key": str(key),
                "qkey": part,
                "text": str(title),
                "start": start,
                "end": end,
            }
        )
    return out


def _load_passes(doc: Path) -> list[tuple[str, object]]:
    from evid.core.quote_pass import load_pass

    folder = doc / "machine"
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("*.json")):
        try:
            out.append((path.name, load_pass(path)))
        except (OSError, ValueError, json.JSONDecodeError):
            continue  # candidate files (from-*.json) stay in the archive
    return out


def _pass_for(qkey: str, hay_key: str, passes) -> str | None:
    for name, qp in passes:
        for row in qp.results:
            key = row.key or ""
            if key in (hay_key, qkey) or key.endswith(":" + qkey):
                return name
    return None


def _migrated_name(doc: Path) -> str:
    src = doc / "machine.hayagriva"
    when = (
        datetime.fromtimestamp(src.stat().st_mtime, tz=UTC)
        if src.exists()
        else datetime.now(tz=UTC)
    )
    return when.strftime("%Y-%m-%dT%H-%M-%SZ") + "_migrated.json"


def _migrated_pass(doc: Path, found: list[dict]):
    from evid import __version__ as evid_version
    from evid.core.quote_pass import PassResult, QuotePass

    src = doc / "machine.hayagriva"
    when = (
        datetime.fromtimestamp(src.stat().st_mtime, tz=UTC)
        if src.exists()
        else datetime.now(tz=UTC)
    )
    return QuotePass(
        id=when.strftime("%Y-%m-%dT%H-%M-%SZ") + "_migrated",
        timestamp=when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        model=None,
        evid_version=evid_version,
        job="migrated from machine.hayagriva",
        results=[
            PassResult(
                candidate=s["text"],
                matched=True,
                score=s.get("score") or 0.0,
                key=s["key"],
                page=s.get("page"),
            )
            for s in found
        ],
        found=found,
    )


def _write(doc: Path, labels, unplaced: list[dict], quotes) -> None:
    from evid.core.labels import _locked
    from evid.core.quote_pass import MACHINE_DIR

    with _locked(doc) as data:
        have = {r.get("key") for r in data["labels"]}
        for _how, rec in labels:
            if rec["key"] not in have:
                data["labels"].append(rec)
                have.add(rec["key"])
    if unplaced:
        path = doc / "label" / "migration.json"
        path.write_text(
            json.dumps(
                {"schema": 1, "unplaced": unplaced}, ensure_ascii=False, indent=1
            )
            + "\n",
            encoding="utf-8",
        )
    dest = doc / MACHINE_DIR
    for name, qp in quotes:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / name).write_text(
            qp.model_dump_json(indent=2, by_alias=True) + "\n", encoding="utf-8"
        )


def _lost(kind: str, key: str, text: str, note: str, score: float) -> dict:
    rec = {"kind": kind, "key": key, "text": text, "score": round(score, 4)}
    if note.strip():
        rec["note"] = note.strip()
    return rec


def _best_score(needle: str, full_text: str) -> float:
    needle = (needle or "").strip()
    if not needle or not full_text:
        return 0.0
    from rapidfuzz import fuzz

    return fuzz.partial_ratio_alignment(needle, full_text).score / 100.0


def _mark_unindexed(doc: Path) -> None:
    from evid.core.evid_meta import read_meta, write_meta

    meta = read_meta(doc)
    meta["indexed"] = False
    write_meta(doc, meta)


def _archive(doc: Path) -> None:
    legacy = doc / "legacy"
    legacy.mkdir(exist_ok=True)
    for name in _OLD_FILES:
        src = doc / name
        if src.is_file():
            dest = legacy / name
            if dest.exists():
                logger.warning("Leaving %s in place; %s already exists", src, dest)
                continue
            shutil.move(src, dest)
    mach = doc / "machine"
    if mach.is_dir():
        dest = legacy / "machine"
        if dest.exists():
            logger.warning("Leaving %s in place; %s already exists", mach, dest)
        else:
            shutil.move(mach, dest)


def _extend_gitignore(root: Path) -> None:
    """Ignore archive byproducts and keep the new label trees trackable.

    Creates the set ``.gitignore`` when the set has none. Rewrites
    ``legacy/**/label.json``, which does not match ``docs/<uuid>/legacy/``.
    Appends re-includes so a ``text.txt`` denylist or a ``label.typ`` allowlist
    still commits ``label/text.txt``, ``pass/``, and ``legacy/label.typ``.
    """
    path = root / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if _GITIGNORE_GOOD[0] not in text:
        for bad, good in zip(_GITIGNORE_BAD, _GITIGNORE_GOOD, strict=True):
            text = text.replace(bad, good)
        if _GITIGNORE_GOOD[0] not in text:
            base = text.rstrip("\n")
            addition = _GITIGNORE_BLOCK.lstrip("\n")
            text = (base + "\n" if base else "") + addition
    if _TRACK_MARKER not in text:
        base = text.rstrip("\n")
        text = (base + "\n" if base else "") + _GITIGNORE_TRACK.lstrip("\n")
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")


def _message(report: Report) -> str:
    docs = report.touched
    labels = sum(d.placed + d.fuzzy for d in docs)
    unplaced = sum(d.unplaced for d in docs)
    texts = sum(1 for d in docs if d.text)
    return f"migrate labels to evid 0.7 ({len(docs)} docs, {labels} labels, {unplaced} unplaced, {texts} texts)"


# A set commit of litc is thousands of paths. The shared git helper stops at 30s,
# and one missing name on the command line makes `git add -u` reject the rest.
_GIT_TIMEOUT = 3600
_ROOT_TRACKED = frozenset((*_OLD_FILES, "evidmgr_meta.yml"))


def _run_git(
    cwd: Path, args: list[str], pathspecs: list[str] | None = None
) -> subprocess.CompletedProcess:
    """Run git. Path lists go on stdin so one missing name cannot abort the rest."""
    cmd = ["git", *args]
    data = None
    if pathspecs is not None:
        cmd += ["--pathspec-from-file=-", "--pathspec-file-nul"]
        data = "\0".join(pathspecs)
    try:
        return subprocess.run(
            cmd,
            cwd=cwd,
            input=data,
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        err = exc.stderr or ""
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        return subprocess.CompletedProcess(
            cmd, 124, "", f"git timed out after {_GIT_TIMEOUT}s: {err}"
        )


def _batches(pathspecs: list[str], limit: int = 200):
    for i in range(0, len(pathspecs), limit):
        yield pathspecs[i : i + limit]


def _tracked(root: Path, pathspecs: list[str] | None = None) -> list[str]:
    """Tracked paths. ``git ls-files`` has no pathspec file, so long lists are batched.

    A name git does not track is omitted. Unlike ``git add -u``, it does not
    reject the rest of the list.
    """
    if pathspecs is not None and not pathspecs:
        return []
    groups = [None] if pathspecs is None else list(_batches(pathspecs))
    found: list[str] = []
    for group in groups:
        args = ["ls-files", "-z"] if group is None else ["ls-files", "-z", "--", *group]
        listed = _run_git(root, args)
        if listed.returncode != 0:
            logger.warning("git ls-files failed: %s", listed.stderr.strip())
            return []
        found.extend(line for line in listed.stdout.split("\0") if line)
    return found


def _docs_needing_git_repair(root: Path, docs_root: Path) -> list[Path]:
    """Docs whose archive is on disk but not yet recorded.

    A document directory that is gone is left alone: that deletion was not
    made by the migration, and the last run kept those paths in HEAD.
    """
    if not docs_root.is_dir():
        return []
    tracked = set(_tracked(root))
    present = {p.name for p in docs_root.iterdir() if p.is_dir()}
    wanted: set[str] = set()
    for path in tracked:
        parts = path.split("/")
        if len(parts) < 3 or parts[0] != "docs" or parts[1] not in present:
            continue
        uuid, name = parts[1], parts[2]
        if (root / path).exists():
            if name == "legacy" and parts[-1] in _LEGACY_BYPRODUCTS:
                wanted.add(uuid)
            continue
        if name in _ROOT_TRACKED or name == "machine":
            wanted.add(uuid)
    for uuid in present:
        doc = docs_root / uuid
        rel = f"docs/{uuid}"
        if uuid in wanted:
            continue
        if (
            not (doc / "legacy").is_dir()
            and not (doc / "label" / "labels.json").is_file()
        ):
            continue
        for name in ("label/labels.json", "label/text.txt", "legacy/label.typ"):
            if (doc / name).is_file() and f"{rel}/{name}" not in tracked:
                wanted.add(uuid)
                break
    return [docs_root / uuid for uuid in sorted(wanted)]


def _untrack_legacy_byproducts(root: Path, docs: list[Path]) -> None:
    """Drop legacy label.json, bib, and text.txt from the index. Files stay."""
    rels = [
        str(doc.resolve().relative_to(root.resolve()) / "legacy" / name)
        for doc in docs
        for name in _LEGACY_BYPRODUCTS
    ]
    tracked = _tracked(root, rels)
    if not tracked:
        return
    removed = _run_git(root, ["rm", "-q", "--cached"], tracked)
    if removed.returncode != 0:
        logger.warning("git rm --cached failed: %s", removed.stderr.strip())


def _cached_names(root: Path) -> set[str]:
    # --no-renames keeps the deleted path. A rename otherwise shows only the new
    # name, and the commit path list then leaves the old file in HEAD.
    listed = _run_git(root, ["diff", "--cached", "--name-only", "--no-renames", "-z"])
    if listed.returncode != 0:
        logger.warning("git diff --cached failed: %s", listed.stderr.strip())
        return set()
    return {line for line in listed.stdout.split("\0") if line}


def _our_path(path: str, exact: set[str], dirs: list[str]) -> bool:
    if path in exact:
        return True
    return any(path.startswith(f"{rel}/") for rel in dirs)


def _commit(root: Path, docs: list[Path], message: str) -> tuple[str | None, str]:
    """One commit of the migrated paths. Other staged or dirty files stay out of it.

    Paths already staged by a commit that timed out are included again. Anything
    else that was staged before this call stays staged and out of the commit.
    """
    if work_tree(root) is None:
        return None, ""
    mine: list[str] = []
    gone: list[str] = []
    for doc in docs:
        rel = str(doc.resolve().relative_to(root.resolve()))
        for name in (*_OLD_FILES, "machine", "evidmgr_meta.yml"):
            gone.append(f"{rel}/{name}")
        for name in ("label", "pass", "legacy", "evid_meta.yml"):
            if (doc / name).exists():
                mine.append(f"{rel}/{name}")
    if (root / ".gitignore").exists():
        mine.append(".gitignore")
    if mine:
        added = _run_git(root, ["add", "-A"], mine)
        if added.returncode != 0:
            err = added.stderr.strip() or "git add failed"
            logger.warning("git add failed: %s", err)
            return None, err
    # Only paths git already tracks. A missing name makes `git add -u` reject the whole list.
    tracked = set(_tracked(root, gone)) if gone else set()
    deleted = [rel for rel in tracked if not (root / rel).exists()]
    if deleted:
        removed = _run_git(root, ["add", "-u"], deleted)
        if removed.returncode != 0:
            logger.warning("git add -u failed: %s", removed.stderr.strip())
    _untrack_legacy_byproducts(root, docs)
    exact = {".gitignore", *deleted}
    dirs: list[str] = []
    for rel in mine:
        if rel == ".gitignore" or not (root / rel).is_dir():
            exact.add(rel)
        else:
            dirs.append(rel)
    staged = [
        line for line in sorted(_cached_names(root)) if _our_path(line, exact, dirs)
    ]
    if not staged:
        return None, ""
    committed = _run_git(root, ["commit", "-q", "-m", message], staged)
    if committed.returncode != 0:
        err = (committed.stderr or committed.stdout).strip() or "git commit failed"
        logger.warning("git commit failed (%s): %s", message, err)
        return None, err
    short = _run_git(root, ["rev-parse", "--short", "HEAD"]).stdout.strip()
    return (short or None), ""


def _unescape(text: str) -> str:
    """Undo a Typst string escape. ``\\n`` is a newline; ``\\#`` is ``#``."""
    out = []
    i = 0
    named = {"n": "\n", "t": "\t", "r": "\r"}
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            out.append(named.get(text[i + 1], text[i + 1]))
            i += 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _lab_args(text: str, i: int) -> tuple[list[str] | None, int]:
    args = []
    while len(args) < 3:
        while i < len(text) and text[i] in " \t\n\r,":
            i += 1
        if i >= len(text) or text[i] != '"':
            return None, i
        body, i = _string(text, i)
        if body is None:
            return None, i
        args.append(body)
    while i < len(text) and text[i] in " \t\n\r":
        i += 1
    if i < len(text) and text[i] == ")":
        i += 1
    return args, i


def _string(text: str, i: int) -> tuple[str | None, int]:
    """A Typst double-quoted string starting at ``text[i] == '"'``."""
    if i >= len(text) or text[i] != '"':
        return None, i
    out = []
    i += 1
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            out.append(c)
            out.append(text[i + 1])
            i += 2
            continue
        if c == '"':
            return "".join(out), i + 1
        out.append(c)
        i += 1
    return None, i
