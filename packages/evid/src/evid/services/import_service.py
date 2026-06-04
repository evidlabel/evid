"""ImportService — import an existing evid directory into an evidmgr set.

An evid directory has the layout:
    {db_dir}/{dataset}/{uuid}/
        info.yml        # InfoModel fields: original_name, uuid, label, tags, url, …
        <original_name> # the original file (PDF, txt, …)
        label.typ       # optional: Typst file
        label.json      # optional: extracted labels
        label.bib       # optional: BibTeX

evidmgr adds:
    evidmgr_meta.yml    # notes, indexed, anon_pending
    set.yml             # top-level set metadata (created once per dataset)
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from evid.models import EvidenceSet
    from evid.services.set_manager import SetManager

logger = logging.getLogger(__name__)

# Progress callback: (done: int, total: int, message: str) -> None
ProgressCallback = Callable[[int, int, str], None]

_DEFAULT_META = {
    "notes": "",
    "indexed": False,
    "anon_pending": False,
}


def _is_uuid_dir(path: Path) -> bool:
    """True if *path* looks like an evid document directory (contains info.yml)."""
    return path.is_dir() and (path / "info.yml").exists()


def _scan_evid_dir(evid_dir: Path) -> dict[str, list[Path]]:
    """Return {dataset_name: [uuid_dir, …]} for a given evid db root.

    evid layout: db_dir/dataset/uuid/info.yml
    """
    datasets: dict[str, list[Path]] = {}
    for dataset_dir in sorted(evid_dir.iterdir()):
        if not dataset_dir.is_dir():
            continue
        uuid_dirs = [d for d in sorted(dataset_dir.iterdir()) if _is_uuid_dir(d)]
        if uuid_dirs:
            datasets[dataset_dir.name] = uuid_dirs
    return datasets


def import_evid_dir(
    evid_dir: Path,
    set_manager: SetManager,
    set_type: str = "normal",
    progress: ProgressCallback | None = None,
) -> list[EvidenceSet]:
    """Import all datasets found inside *evid_dir* into evidmgr sets.

    Each evid dataset becomes one EvidenceSet.  Files are **copied** (not
    moved) so the original evid directory is left intact.

    Returns the list of imported EvidenceSets.
    """
    if progress is None:
        progress = lambda done, total, msg: logger.info("[%d/%d] %s", done, total, msg)

    datasets = _scan_evid_dir(evid_dir)
    if not datasets:
        logger.warning("No evid datasets found in %s", evid_dir)
        return []

    imported: list[EvidenceSet] = []
    total_sets = len(datasets)

    for set_idx, (dataset_name, uuid_dirs) in enumerate(datasets.items(), 1):
        progress(
            set_idx,
            total_sets,
            f"Importing dataset '{dataset_name}' ({len(uuid_dirs)} docs)",
        )
        try:
            evidence_set = _import_dataset(
                dataset_name=dataset_name,
                uuid_dirs=uuid_dirs,
                set_manager=set_manager,
                set_type=set_type,
                progress=progress,
            )
            imported.append(evidence_set)
        except Exception:
            logger.exception("Failed to import dataset '%s'", dataset_name)

    return imported


def import_evid_dir_single(
    evid_dir: Path,
    dataset_name: str,
    set_manager: SetManager,
    set_type: str = "normal",
    progress: ProgressCallback | None = None,
) -> EvidenceSet:
    """Import a single evid *dataset* directory (not the db root) as one set.

    Use this when the user points directly at a dataset directory (i.e.,
    the directory whose children are UUID dirs).
    """
    if progress is None:
        progress = lambda done, total, msg: logger.info("[%d/%d] %s", done, total, msg)

    uuid_dirs = [d for d in sorted(evid_dir.iterdir()) if _is_uuid_dir(d)]
    if not uuid_dirs:
        # Maybe evid_dir itself is a UUID dir (single-doc import)
        if _is_uuid_dir(evid_dir):
            uuid_dirs = [evid_dir]
        else:
            msg = f"No evid document directories found in {evid_dir}"
            raise ValueError(msg)

    return _import_dataset(
        dataset_name=dataset_name,
        uuid_dirs=uuid_dirs,
        set_manager=set_manager,
        set_type=set_type,
        progress=progress,
    )


# ── internals ─────────────────────────────────────────────────────────────────


def _import_dataset(
    dataset_name: str,
    uuid_dirs: list[Path],
    set_manager: SetManager,
    set_type: str,
    progress: ProgressCallback,
) -> EvidenceSet:
    from evid.models import SetType

    # Create the evidmgr set (skip if already exists with same slug)
    try:
        evidence_set = set_manager.create_set(
            name=dataset_name,
            set_type=SetType(set_type),
        )
    except FileExistsError:
        from slugify import slugify

        slug = slugify(dataset_name)
        evidence_set = set_manager.load_set(slug)
        logger.info("Set '%s' already exists — merging docs into it", slug)

    docs_dir = evidence_set.path / "docs"
    total_docs = len(uuid_dirs)

    for doc_idx, src_uuid_dir in enumerate(uuid_dirs, 1):
        progress(doc_idx, total_docs, f"Importing {src_uuid_dir.name}")
        try:
            _import_doc(src_uuid_dir, docs_dir, evidence_set.set_type.value)
        except Exception:
            logger.exception("Failed to import doc %s", src_uuid_dir.name)

    return evidence_set


def _import_doc(src_dir: Path, dest_docs_dir: Path, set_type: str) -> None:
    """Copy one evid UUID directory into dest_docs_dir and add evidmgr_meta.yml."""
    dest_dir = dest_docs_dir / src_dir.name

    if dest_dir.exists():
        logger.debug("Doc %s already imported, skipping", src_dir.name)
        return

    # Copy the whole UUID dir (info.yml, original file, label.* if present)
    shutil.copytree(src_dir, dest_dir)

    # Write evidmgr_meta.yml if it doesn't already exist
    meta_path = dest_dir / "evidmgr_meta.yml"
    if not meta_path.exists():
        meta = dict(_DEFAULT_META)
        if set_type == "anon":
            meta["anon_pending"] = True
        with meta_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(meta, f, allow_unicode=True)

    logger.debug("Imported doc %s", src_dir.name)
