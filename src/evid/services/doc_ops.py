"""Per-document operations shared by the GUI server and the CLI.

Pure filesystem work, no UI: list a set's documents, read / update a doc's
``info.yml`` + ``evid_meta.yml``, delete, copy between sets, and make sure a
``label.typ`` exists for labelling.
"""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from evid.models import Document, EvidenceSet
    from evid.services.set_manager import SetManager

logger = logging.getLogger(__name__)

INFO_FIELDS = ("title", "authors", "dates", "tags", "label", "url")


def collect_documents(set_manager: SetManager, slug: str) -> list[Document]:
    """Read every document's info.yml / evid_meta.yml for *slug* into Documents.

    Sorted newest-first (added date, then dir mtime). ``load_yaml`` uses the
    libyaml loader because this parses one YAML file per document.
    """
    from evid.core.evid_meta import read_meta
    from evid.models import Document, _join_if_list
    from evid.utils.yaml_io import load_yaml

    docs: list[Document] = []
    mtime_by_uuid: dict[str, float] = {}
    for doc_dir in set_manager.list_documents(slug):
        try:
            info_path = doc_dir / "info.yml"
            try:
                with info_path.open("r", encoding="utf-8") as f:
                    info = load_yaml(f) or {}
            except yaml.YAMLError as exc:
                logger.warning("Skipping %s — bad info.yml: %s", doc_dir.name, exc)
                continue
            meta = read_meta(doc_dir)
            tags_raw = info.get("tags", "")
            if isinstance(tags_raw, list):
                tags = [str(t).strip() for t in tags_raw if str(t).strip()]
            elif tags_raw:
                tags = [t.strip() for t in str(tags_raw).split(",") if t.strip()]
            else:
                tags = []
            raw_added = info.get("time_added", "")
            mtime = doc_dir.stat().st_mtime
            mtime_by_uuid[doc_dir.name] = mtime
            try:
                if isinstance(raw_added, date):
                    added = datetime(
                        raw_added.year, raw_added.month, raw_added.day, tzinfo=UTC
                    )
                else:
                    added = datetime.strptime(str(raw_added), "%Y-%m-%d").replace(
                        tzinfo=UTC
                    )
            except (ValueError, TypeError):
                added = datetime.fromtimestamp(mtime, tz=UTC)
            docs.append(
                Document(
                    uuid=doc_dir.name,
                    path=doc_dir,
                    label=info.get("label", doc_dir.name),
                    tags=tags,
                    added=added,
                    indexed=meta.get("indexed", False),
                    notes=meta.get("notes", ""),
                    source_url=info.get("url", ""),
                    authors=_join_if_list(info.get("authors", info.get("author", ""))),
                    dates=_join_if_list(info.get("dates", "")),
                )
            )
        except Exception:
            logger.exception("Failed to load doc at %s", doc_dir)
    docs.sort(key=lambda d: (d.added, mtime_by_uuid.get(d.uuid, 0.0)), reverse=True)
    return docs


def doc_dir_of(evidence_set: EvidenceSet, uuid: str) -> Path:
    """The doc directory for *uuid*; rejects anything that is not a plain name."""
    if not uuid or "/" in uuid or "\\" in uuid or uuid in (".", ".."):
        msg = f"bad document id: {uuid!r}"
        raise ValueError(msg)
    doc_dir = evidence_set.path / "docs" / uuid
    if not doc_dir.is_dir():
        msg = f"no document {uuid} in set '{evidence_set.slug}'"
        raise FileNotFoundError(msg)
    return doc_dir


def _read_info(doc_dir: Path) -> dict:
    info_path = doc_dir / "info.yml"
    if not info_path.exists():
        return {}
    with info_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_doc(doc_dir: Path) -> dict[str, Any]:
    """The editable detail of one doc: info.yml fields (validated) plus notes."""
    from evid.core.evid_meta import read_meta
    from evid.models import InfoModel
    from evid.services.doc_tags import resolve_doc_pdf

    info = _read_info(doc_dir)
    try:
        model = InfoModel.model_validate(
            {**info, "uuid": info.get("uuid") or doc_dir.name}
        )
    except Exception:
        logger.exception("Failed to parse info.yml for %s", doc_dir.name)
        model = InfoModel(uuid=doc_dir.name)
    meta = read_meta(doc_dir)
    out = {k: str(getattr(model, k) or "") for k in INFO_FIELDS}
    out.update(
        uuid=doc_dir.name,
        path=str(doc_dir),
        notes=meta.get("notes", "") or "",
        indexed=bool(meta.get("indexed", False)),
        has_pdf=resolve_doc_pdf(doc_dir) is not None,
        has_json=(doc_dir / "label.json").exists(),
        has_typ=(doc_dir / "label.typ").exists() or any(doc_dir.glob("*.typ")),
    )
    return out


def update_doc(doc_dir: Path, fields: dict[str, Any]) -> dict[str, Any]:
    """Write the editable fields in *fields* to info.yml / evid_meta (notes).

    Keys not in *fields* are left as they are. Returns the new detail.
    """
    from evid.core.evid_meta import read_meta, write_meta
    from evid.models import InfoModel

    info = _read_info(doc_dir)
    for key in INFO_FIELDS:
        if key in fields:
            info[key] = str(fields[key] or "").strip()
    try:
        info = InfoModel(**{k: (v or "") for k, v in info.items()}).model_dump()
    except Exception:
        logger.exception("InfoModel validation failed on save for %s", doc_dir.name)
    with (doc_dir / "info.yml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(info, f, allow_unicode=True)
    if "notes" in fields:
        meta = read_meta(doc_dir)
        meta["notes"] = str(fields["notes"] or "")
        write_meta(doc_dir, meta)
    return get_doc(doc_dir)


def delete_doc(doc_dir: Path) -> None:
    """Remove a document directory and everything in it."""
    shutil.rmtree(doc_dir)
    logger.info("Deleted document %s", doc_dir.name)


def copy_doc(src_doc_dir: Path, dest_set: EvidenceSet) -> tuple[Path, bool]:
    """Copy a doc dir into *dest_set*, marked unindexed.

    Returns ``(dest_doc_dir, copied)``; ``copied`` is False when the doc was
    already in the destination set (nothing is overwritten).
    """
    from evid.core.evid_meta import write_meta

    dest_doc_dir = dest_set.path / "docs" / src_doc_dir.name
    if dest_doc_dir.exists():
        logger.info(
            "Doc %s already present in '%s' — skipping copy",
            src_doc_dir.name,
            dest_set.slug,
        )
        return dest_doc_dir, False
    dest_doc_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src_doc_dir, dest_doc_dir)
    write_meta(dest_doc_dir, {"notes": "", "indexed": False})
    return dest_doc_dir, True


def find_label_typ(doc_dir: Path) -> Path:
    """``label.typ``, else any other ``*.typ``, else where label.typ would go."""
    typ_path = doc_dir / "label.typ"
    if typ_path.exists():
        return typ_path
    existing = sorted(doc_dir.glob("*.typ"))
    return existing[0] if existing else typ_path


def label_source(doc_dir: Path) -> Path | None:
    """The PDF (or text file) a label.typ is generated from."""
    from evid.services.doc_tags import resolve_doc_pdf

    pdf = resolve_doc_pdf(doc_dir)
    if pdf:
        return pdf
    candidates = sorted(doc_dir.glob("*.txt"))
    return candidates[0] if candidates else None


def ensure_label_typ(doc_dir: Path) -> Path:
    """Return the doc's .typ file, generating ``label.typ`` from the source first.

    Raises ``FileNotFoundError`` when there is no .typ and nothing to make one from.
    """
    from evid.core.typst_generation import text_to_typst, textpdf_to_typst

    typ_path = find_label_typ(doc_dir)
    if typ_path.exists():
        return typ_path
    source = label_source(doc_dir)
    if source is None:
        msg = "No PDF or text file found to generate labels from."
        raise FileNotFoundError(msg)
    if source.suffix.lower() == ".pdf":
        textpdf_to_typst(source, typ_path)
    else:
        text_to_typst(source, typ_path)
    return typ_path


TEXT_SUFFIXES = {
    ".typ",
    ".yml",
    ".yaml",
    ".json",
    ".bib",
    ".txt",
    ".md",
    ".hayagriva",
    ".csv",
}


def doc_path(doc_dir: Path, rel: str) -> Path:
    """*rel* inside *doc_dir*; refuses anything that escapes it."""
    p = (doc_dir / (rel or "")).resolve()
    root = doc_dir.resolve()
    if p != root and root not in p.parents:
        msg = f"path outside the document folder: {rel!r}"
        raise ValueError(msg)
    if not p.exists():
        msg = f"no such file: {rel}"
        raise FileNotFoundError(msg)
    return p


def list_doc_files(doc_dir: Path, sub: str = "") -> list[dict[str, Any]]:
    """One level of the doc folder (or of *sub* inside it): folders first, then files."""
    base = doc_path(doc_dir, sub)
    if not base.is_dir():
        msg = f"not a folder: {sub}"
        raise ValueError(msg)
    out = []
    for child in sorted(base.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
        st = child.stat()
        out.append(
            {
                "name": child.name,
                "path": str(child.relative_to(doc_dir.resolve())),
                "dir": child.is_dir(),
                "size": 0 if child.is_dir() else st.st_size,
                "mtime": st.st_mtime,
            }
        )
    return out
