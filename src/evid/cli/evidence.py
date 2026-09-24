"""Handle evidence addition and management.

Deep ingest (hash → copy → metadata → typst → bibtex → index) lives in
:class:`evid.services.doc_ingester.DocIngester`. This module is a thin CLI
adapter: load/create the set, call the ingester, print results, optional labeler.
"""

import logging
import sys
from pathlib import Path

import yaml
from rich.console import Console
from rich.table import Table

from evid.cli.dataset import docs_dir
from evid.core.label import create_label
from evid.models import InfoModel
from evid.services.doc_tags import resolve_doc_pdf

# Logging is configured centrally in evid.logging_config (called from main()).
logger = logging.getLogger(__name__)


def to_plain_dict(data):
    """Recursively convert data to plain dict with string values."""
    if isinstance(data, dict):
        return {k: to_plain_dict(v) for k, v in data.items()}
    if isinstance(data, list):
        return [to_plain_dict(v) for v in data]
    return str(data)


def _expand_sources(sources: list[str]) -> list[str]:
    """Expand directory arguments to their ``*.pdf`` files, keeping URLs and
    file paths as given. Sorted within each directory for a stable order."""
    expanded: list[str] = []
    for source in sources:
        if source.startswith(("http://", "https://")):
            expanded.append(source)
            continue
        path = Path(source).expanduser()
        if path.is_dir():
            pdfs = sorted(path.glob("*.pdf"))
            if not pdfs:
                logger.warning("No PDFs found in directory %s", path)
            expanded.extend(str(f) for f in pdfs)
        else:
            expanded.append(source)
    return expanded


def add_evidence(
    directory: Path,
    dataset: str,
    source: str | list[str],
    label: bool = False,
    autolabel: bool = False,
    no_index: bool = False,
) -> None:
    """Add one or more PDFs/URLs (or a directory of PDFs) to the dataset.

    A batch reuses a single ``IndexWorkerPool`` so the embedding model loads
    once rather than once per document. Per-document failures are reported and
    skipped in batch mode; a single source still exits on error.
    """
    from evid import extras
    from evid.services.doc_ingester import DocIngester
    from evid.services.set_manager import SetManager
    from evid.services.vec_service import VecService

    sources = source if isinstance(source, (list, tuple)) else [source]
    sources = _expand_sources(list(sources))
    if not sources:
        sys.exit("No documents to add.")

    sm = SetManager(directory)
    try:
        evidence_set = sm.load_set(dataset)
    except FileNotFoundError:
        # Convenience for tests / direct API use; interactive CLI resolves the
        # set first via add_callback → _resolve_dataset.
        evidence_set = sm.create_set(dataset)

    # --no-index, or a light install without evid[vec]: never construct VecService.
    do_index = not no_index and extras.has_vec()
    if not no_index and not extras.has_vec():
        print(extras.VEC_SKIP_INDEX)
    vec_service = VecService() if do_index else None
    ingester = DocIngester(vec_service=vec_service)

    # One long-lived index child for a batch: the embedding model loads once.
    pool = None
    if do_index and len(sources) > 1:
        from evid.vec.safe_index import IndexWorkerPool

        pool = IndexWorkerPool()

    failures = 0
    try:
        for src in sources:
            try:
                doc = ingester.ingest_source(
                    src,
                    evidence_set,
                    do_index=do_index,
                    pool=pool,
                )
            except (FileNotFoundError, ValueError) as e:
                if len(sources) == 1:
                    sys.exit(str(e))
                print(f"Failed to add {src}: {e}", file=sys.stderr)
                failures += 1
                continue
            except Exception as e:
                # Network errors (requests) and other resolve/ingest failures.
                msg = (
                    f"Failed to download content: {e!s}"
                    if src.startswith(("http://", "https://"))
                    else f"Failed to add document: {e!s}"
                )
                if len(sources) == 1:
                    sys.exit(msg)
                print(msg, file=sys.stderr)
                failures += 1
                continue

            if ingester.last_was_existing:
                print(f"This document is already added in {dataset} at {doc.uuid}")
                continue

            _print_info(doc)

            if label:
                pdf = resolve_doc_pdf(doc.path)
                if pdf is None:
                    sys.exit(f"No PDF found for document {doc.uuid}")
                logger.debug("Opening label file for %s...", pdf.name)
                create_label(pdf, dataset, doc.uuid, autolabel=autolabel)
    finally:
        if pool is not None:
            pool.close()

    if failures:
        sys.exit(f"{failures} of {len(sources)} document(s) failed to add.")


def _print_info(doc) -> None:
    """Print the document's info.yml to stdout, as `doc add` always has."""
    info_path = doc.path / "info.yml"
    if not info_path.exists():
        return
    try:
        with info_path.open(encoding="utf-8") as f:
            info = yaml.safe_load(f) or {}
        yaml.dump(info, sys.stdout, allow_unicode=True)
    except Exception:
        logger.exception("Could not print info.yml for %s", doc.uuid)
    logger.debug("Added document to %s", doc.path)


def get_evidence_list(directory: Path, dataset: str) -> list[dict]:
    """Return a list of document metadata in the dataset."""
    from evid.services.set_manager import SetManager

    documents = []
    for d in SetManager(directory).list_documents(dataset):
        info_path = d / "info.yml"
        try:
            with info_path.open("r", encoding="utf-8") as f:
                info = yaml.load(f, Loader=yaml.FullLoader)
            if info is None:
                logger.warning(f"Empty or invalid YAML in {info_path}. Skipping.")
                continue
            info = to_plain_dict(info)
            validated_info = InfoModel(**info)
            info = validated_info.model_dump()
        except (yaml.YAMLError, ValueError, TypeError) as e:
            logger.warning(f"Error loading or validating {info_path}: {e}. Skipping.")
            continue
        documents.append(
            {
                "uuid": d.name,
                "title": info.get("title", d.name),
                "authors": info.get("authors", ""),
                "date": info.get("time_added", ""),
            }
        )
    return documents


def select_evidence(
    directory: Path, dataset: str, prompt_message: str = "Select document"
) -> str:
    """Prompt user to select a document from the dataset."""
    documents = get_evidence_list(directory, dataset)
    if not documents:
        sys.exit("No documents found in dataset.")

    console = Console()
    table = Table(title=prompt_message)
    table.add_column("Nr", justify="right")
    table.add_column("Title")
    table.add_column("Authors")
    table.add_column("Date")
    table.add_column("UUID")

    for i, ev in enumerate(documents, 1):
        table.add_row(str(i), ev["title"], ev["authors"], ev["date"], ev["uuid"])

    console.print(table)

    choice = input("Select document (number): ").strip()
    try:
        choice_num = int(choice)
        if 1 <= choice_num <= len(documents):
            return documents[choice_num - 1]["uuid"]
        sys.exit("Invalid number.")
    except ValueError:
        sys.exit("Invalid selection.")


def label_evidence(
    directory: Path, dataset: str = None, uuid: str = None, filename: str = "label.typ"
) -> None:
    """Label a document in the specified dataset."""
    from evid.cli.dataset import select_dataset

    if not dataset:
        dataset = select_dataset(
            directory, "Select dataset to label", allow_create=False
        )

    if not uuid:
        uuid = select_evidence(directory, dataset)

    evidence_path = docs_dir(directory, dataset) / uuid
    if not evidence_path.exists():
        sys.exit(f"Document {uuid} in {dataset} does not exist.")

    files = list(evidence_path.glob("*.pdf")) + list(evidence_path.glob("*.txt"))
    if not files:
        sys.exit("No PDF or TXT found in document directory.")
    if len(files) > 1:
        logger.warning("Multiple files found, using the first one.")
    file_path = files[0]

    create_label(file_path, dataset, uuid, filename=filename)
