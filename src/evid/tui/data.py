"""Data loading and mutations for the TUI.

This module is curses-free so it can be tested headlessly and reused. Every
mutation goes through the same service layer the CLI uses; nothing here prints
or exits, so callers (the TUI) control all output.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from evid.cli.evidence import _expand_sources
from evid.config import EvidConfig
from evid.models import EvidenceSet
from evid.services.doc_ops import update_doc
from evid.services.set_manager import SetManager

logger = logging.getLogger(__name__)

# Fields INFO_FIELDS lets the TUI edit through ``update_doc``.
EDITABLE = ("title", "authors", "dates", "url")


def index_default() -> bool:
    """Whether indexing should be on by default (honours ``evid[vec]``)."""
    from evid import extras

    return extras.has_vec()


def resolve_directory(db: str | None) -> Path:
    """Return the data directory the same way evid.cli.main resolves it."""
    if db is not None:
        return Path(db).expanduser()
    return EvidConfig.load().data_dir


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


@dataclass
class DocRow:
    """A concise, TUI-shaped view of one document."""

    uuid: str
    dir: Path
    title: str = ""
    authors: str = ""
    dates: str = ""
    url: str = ""
    tags: list[str] = field(default_factory=list)
    time_added: str = ""
    note: str = ""


def list_sets(directory: Path) -> list[EvidenceSet]:
    """All evidence sets, newest first; empty list if none exist."""
    try:
        return list(SetManager(directory).list_sets())
    except Exception as e:  # pragma: no cover - defensive, mirrors CLI
        logger.warning("Could not list sets: %s", e)
        return []


def list_docs(directory: Path, slug: str) -> list[DocRow]:
    """Documents of *slug*, newest first. Returns [] when the set is absent."""
    try:
        doc_dirs = list(SetManager(directory).list_documents(slug))
    except FileNotFoundError:
        return []
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Could not list documents for %s: %s", slug, e)
        return []

    rows: list[DocRow] = []
    for d in doc_dirs:
        info = _read_info(d)
        if info is None:
            continue
        rows.append(
            DocRow(
                uuid=d.name,
                dir=d,
                title=info.get("title") or d.name,
                authors=_join(info.get("authors")),
                dates=_join(info.get("dates")),
                url=str(info.get("url") or ""),
                tags=_tag_list(info.get("tags")),
                time_added=str(info.get("time_added") or ""),
                note=str(info.get("note") or ""),
            )
        )
    # Newest first by time_added, then directory mtime.
    rows.sort(
        key=lambda r: (r.time_added or "", str(r.dir.stat().st_mtime)), reverse=True
    )
    return rows


@dataclass
class ParaRow:
    """One paragraph of a document's canonical text, with the keys labelling it."""

    number: int
    start: int
    end: int
    text: str
    page: int | None = None
    keys: list[str] = field(default_factory=list)


def list_paragraphs(doc_dir: Path) -> list[ParaRow]:
    """Paragraphs of *doc_dir*, labelled with the keys that begin inside them.

    The canonical text is extracted on first use into ``label/text.txt`` (the
    same file ``evid label`` reads and writes), so the TUI can label a document
    without shelling out. Returns [] when the document has no readable text.
    """
    from evid.core.labels import ensure_text, paragraph_spans, read

    try:
        text, pages = ensure_text(doc_dir)
    except (FileNotFoundError, ValueError) as e:
        logger.warning("Could not read text for %s: %s", doc_dir.name, e)
        return []

    labels = read(doc_dir).get("labels") or []
    rows: list[ParaRow] = []
    for number, span in enumerate(paragraph_spans(text, pages), start=1):
        keys = [
            rec["key"]
            for rec in labels
            if rec.get("key") and span["start"] <= rec.get("start", -1) < span["end"]
        ]
        rows.append(
            ParaRow(
                number=number,
                start=span["start"],
                end=span["end"],
                text=span["text"],
                page=span.get("page"),
                keys=keys,
            )
        )
    return rows


def suggest_key(doc_dir: Path, text: str) -> str:
    """A key for *text* that no label in *doc_dir* uses yet."""
    from evid.core.labels import suggest_key as suggest
    from evid.core.labels import taken_keys

    return suggest(text, taken_keys(doc_dir))


def label_paragraph(doc_dir: Path, start: int, end: int, key: str) -> tuple[bool, str]:
    """Write one label over ``text[start:end]``; (True, msg) on success."""
    from evid.core.labels import add_label, span_at

    try:
        rec = add_label(doc_dir, span_at(doc_dir, start, end), key)
    except (ValueError, KeyError) as e:
        return False, str(e)
    note = _commit_labels(doc_dir, f"+{rec['key']}")
    return True, f"Labelled ¶ as '{rec['key']}'." + note


def unlabel(doc_dir: Path, key: str) -> tuple[bool, str]:
    """Remove label *key* from *doc_dir*; (True, msg) on success."""
    from evid.core.labels import remove_label

    try:
        remove_label(doc_dir, key)
    except KeyError as e:
        return False, str(e)
    note = _commit_labels(doc_dir, f"-{key}")
    return True, f"Removed label '{key}'." + note


def export_labels(directory: Path, slug: str) -> str:
    """All saved labels in the active set, in the GUI's clipboard YAML format."""
    from evid.core.labels import label_entries
    from evid.core.prompt import labels_to_yaml

    return labels_to_yaml(
        [
            (
                {
                    "uuid": doc.uuid,
                    "title": doc.title,
                    "authors": doc.authors,
                    "url": doc.url,
                },
                label_entries(doc.dir),
            )
            for doc in list_docs(directory, slug)
        ]
    )


def _commit_labels(doc_dir: Path, delta: str) -> str:
    """Commit ``label/`` when the set is a git repo, as ``evid label`` does."""
    from evid.cli.label_cmd import commit_doc_labels
    from evid.core.bibtex_utils import load_title

    try:
        commit_doc_labels(
            doc_dir, f"label: {load_title(doc_dir / 'info.yml')} ({delta})"
        )
    except Exception as e:  # pragma: no cover - git trouble must not lose the write
        logger.warning("Could not commit labels for %s: %s", doc_dir.name, e)
        return f" (not committed: {e})"
    return ""


def create_set(directory: Path, name: str) -> tuple[str, str]:
    """Create a normal evidence set; returns ``(slug, message)`` (slug '' on failure)."""
    try:
        ev_set = SetManager(directory).create_set(name, "normal")
    except FileExistsError:
        return "", f"Set '{name}' already exists."
    except Exception as e:  # pragma: no cover - defensive
        return "", f"Failed to create set: {e}"
    return ev_set.slug, f"Created set '{ev_set.slug}'."


def _read_info(doc_dir: Path) -> dict | None:
    from evid.core.annotations import doc_note

    info_path = doc_dir / "info.yml"
    if not info_path.exists():
        return None
    try:
        import yaml

        with info_path.open("r", encoding="utf-8") as f:
            info = yaml.safe_load(f) or {}
        info["note"] = doc_note(doc_dir)
        return info
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Could not read info.yml for %s: %s", doc_dir.name, e)
        return None


def _join(v) -> str:
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    return str(v or "")


def _tag_list(v) -> list[str]:
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    return [t for t in str(v or "").split() if t]


# --------------------------------------------------------------------------
# Quick addition
# --------------------------------------------------------------------------


@dataclass
class AddResult:
    source: str
    ok: bool
    message: str
    uuid: str = ""


def run_add(
    directory: Path,
    slug: str,
    sources: list[str],
    *,
    do_index: bool | None = None,
    autolabel: bool = False,
    title: str = "",
    authors: str = "",
    dates: str = "",
    url: str = "",
    on_progress: Callable[[AddResult], None] | None = None,
) -> list[AddResult]:
    """Add *sources* (URLs, PDF paths, directories) to *slug* as a batch.

    Mirrors ``evid doc add`` but reports instead of printing/exiting: creates
    the set if missing, expands directories to their PDFs, then ingests each
    source through :class:`~evid.services.doc_ingester.DocIngester`. A single
    long-lived index child is reused across the batch (model loads once).
    Non-empty *title* / *authors* / *dates* / *url* are written over whatever
    the source provided, as in ``evid doc add --title …``.

    *on_progress* is called as each result is produced. Returns ``AddResult``
    per source, never raises for per-source failures.
    """
    if not sources:
        return []
    from evid import extras
    from evid.services.doc_ingester import DocIngester
    from evid.services.vec_service import VecService

    sm = SetManager(directory)
    try:
        evidence_set = sm.load_set(slug)
    except FileNotFoundError:
        evidence_set = sm.create_set(slug)

    expanded = _expand_sources(list(sources))
    if not expanded:
        return [AddResult(sources[0], False, "No readable documents matched.")]

    if do_index is None:
        do_index = extras.has_vec()
    vec_service = VecService() if do_index else None
    ingester = DocIngester(vec_service=vec_service)

    pool = None
    if do_index and len(expanded) > 1:
        from evid.vec.safe_index import IndexWorkerPool

        pool = IndexWorkerPool()

    results: list[AddResult] = []
    try:
        for src in expanded:
            try:
                doc = ingester.ingest_source(
                    src, evidence_set, do_index=do_index, pool=pool
                )
            except (FileNotFoundError, ValueError) as e:
                res = _result(src, False, str(e))
            except Exception as e:  # network / resolve / ingest failures
                msg = (
                    f"Failed to download content: {e!s}"
                    if src.startswith(("http://", "https://"))
                    else f"Failed to add document: {e!s}"
                )
                res = _result(src, False, msg)
            else:
                step_warnings = "; ".join(
                    f"{what}: {err}" for _, what, err in ingester.errors
                )
                if ingester.last_was_existing:
                    res = _result(
                        src,
                        True,
                        f"Already present in '{slug}' at {doc.uuid}",
                        doc.uuid,
                    )
                else:
                    if autolabel and not ingester.last_was_existing:
                        _paragraph_labels(doc.path)
                    _apply_metadata(
                        doc.path,
                        title=title,
                        authors=authors,
                        dates=dates,
                        url=url,
                    )
                    res = _result(
                        src,
                        True,
                        step_warnings or f"Added {doc.uuid[:8]}",
                        doc.uuid,
                    )
            results.append(res)
            if on_progress is not None:
                on_progress(res)
    finally:
        if pool is not None:
            pool.close()
    return results


def _apply_metadata(doc_dir: Path, *, title="", authors="", dates="", url="") -> None:
    """Write non-empty editable info.yml fields over whatever the source gave."""
    fields = {
        k: v
        for k, v in (
            ("title", title),
            ("authors", authors),
            ("dates", dates),
            ("url", url),
        )
        if v
    }
    if not fields:
        return
    try:
        from evid.services.doc_ops import update_doc

        update_doc(doc_dir, fields)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Could not apply metadata to %s: %s", doc_dir, e)


def _paragraph_labels(doc_dir: Path) -> None:
    """Label each paragraph of *doc_dir* as a span (mirrors ``--label``)."""
    try:
        from evid.cli.label_cmd import write_paragraph_labels

        write_paragraph_labels(doc_dir)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Autolabel failed for %s: %s", doc_dir, e)


def _result(source: str, ok: bool, message: str, uuid: str = "") -> AddResult:
    return AddResult(source=source, ok=ok, message=message, uuid=uuid)


# --------------------------------------------------------------------------
# Curation mutations
# --------------------------------------------------------------------------


def assign_tag(directory: Path, uuid: str, tag: str) -> tuple[bool, str]:
    """Add *tag* to *uuid*; namespaced like the CLI. (True, msg) on success."""
    from evid.cli.tags import assign_tag as cli_assign

    return cli_assign(directory, uuid, tag)


def remove_tag(directory: Path, uuid: str, tag: str) -> tuple[bool, str]:
    """Remove one *tag* (qualified name) from one document."""
    from evid.services.tag_service import TagService

    doc_dir = uuid_dir(directory, uuid)
    if doc_dir is None:
        return False, f"No document matching UUID prefix '{uuid}'."
    slug = set_slug_of(directory, doc_dir)
    qualified = TagService.qualify(tag, slug) if slug else tag
    info = _read_info(doc_dir) or {}
    keep = [t for t in _tag_list(info.get("tags")) if t not in (tag, qualified)]
    update_doc(doc_dir, {"tags": " ".join(keep)})
    return True, f"Removed '{qualified}' from {doc_dir.name[:8]}."


def known_tags(directory: Path, slug: str) -> list[str]:
    """Tags already in use (qualified), for quick-pick during tag assignment."""
    try:
        from evid.services.tag_service import TagService

        return [t.name for t in TagService(directory).list_tags(slug)]
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Could not list tags: %s", e)
        return []


def update_metadata(
    directory: Path, uuid: str, fields: dict[str, str]
) -> tuple[bool, str]:
    """Write editable info.yml fields (title/authors/dates/url) for *uuid*."""
    doc_dir = uuid_dir(directory, uuid)
    if doc_dir is None:
        return False, f"No document matching UUID prefix '{uuid}'."
    field, value = next(iter(fields.items()))
    if field not in EDITABLE:
        return False, f"Field '{field}' is not editable here."
    update_doc(doc_dir, {field: str(value or "").strip()})
    return True, f"{field} set on {doc_dir.name[:8]}."


def set_note(directory: Path, uuid: str, text: str) -> tuple[bool, str]:
    """Set a whole-document annotation (note) on *uuid*; empty clears it."""
    doc_dir = uuid_dir(directory, uuid)
    if doc_dir is None:
        return False, f"No document matching UUID prefix '{uuid}'."
    text = (text or "").strip()
    if text:
        update_doc(doc_dir, {"notes": text})
        return True, f"Note set on {doc_dir.name[:8]}."
    _clear_notes(doc_dir)
    return True, f"Note cleared from {doc_dir.name[:8]}."


def _clear_notes(doc_dir: Path) -> None:
    try:
        from evid.core.labels import (
            adopt_legacy_document_note,
            clear_document_annotations,
        )

        adopt_legacy_document_note(doc_dir)
        clear_document_annotations(doc_dir)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Could not clear notes for %s: %s", doc_dir, e)


def doc_dir_of(directory: Path, uuid: str) -> Path | None:
    """Resolve a (possibly truncated) UUID to its directory."""
    try:
        return uuid_dir(directory, uuid)
    except Exception:  # pragma: no cover - defensive
        return None


def uuid_dir(directory: Path, uuid: str) -> Path | None:
    """Locate the document directory for a (possibly truncated) UUID."""
    needle = uuid.strip().lower()
    if not needle:
        return None
    sm = SetManager(directory)
    found: Path | None = None
    for es in sm.list_sets():
        try:
            dirs = list(sm.list_documents(es.slug))
        except Exception:  # pragma: no cover - defensive
            continue
        for d in dirs:
            if d.name.lower().startswith(needle):
                if found is not None:
                    return None  # ambiguous prefix
                found = d
    return found


def set_slug_of(directory: Path, doc_dir: Path) -> str:
    """The set slug that contains *doc_dir* (its ``docs/`` parent dir's parent)."""
    sm = SetManager(directory)
    for es in sm.list_sets():
        docs = es.path / "docs"
        if doc_dir.parent == docs:
            return es.slug
    return ""
