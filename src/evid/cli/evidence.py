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


def add_evidence(
    directory: Path,
    dataset: str,
    source: str,
    label: bool = False,
    autolabel: bool = False,
    no_index: bool = False,
) -> None:
    """Add a PDF or URL to the specified dataset via DocIngester."""
    from evid import extras
    from evid.services.doc_ingester import DocIngester
    from evid.services.set_manager import SetManager
    from evid.services.vec_service import VecService

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

    try:
        doc = ingester.ingest_source(
            source,
            evidence_set,
            do_index=do_index,
        )
    except FileNotFoundError as e:
        sys.exit(str(e))
    except ValueError as e:
        sys.exit(str(e))
    except Exception as e:
        # Network errors (requests) and other resolve/ingest failures.
        if source.startswith(("http://", "https://")):
            sys.exit(f"Failed to download content: {e!s}")
        sys.exit(f"Failed to add document: {e!s}")

    if ingester.last_was_existing:
        print(f"This document is already added in {dataset} at {doc.uuid}")
        return

    info_path = doc.path / "info.yml"
    if info_path.exists():
        try:
            with info_path.open(encoding="utf-8") as f:
                info = yaml.safe_load(f) or {}
            yaml.dump(info, sys.stdout, allow_unicode=True)
        except Exception:
            logger.exception("Could not print info.yml for %s", doc.uuid)

    logger.debug("Added document to %s", doc.path)

    if label:
        pdf = resolve_doc_pdf(doc.path)
        if pdf is None:
            sys.exit(f"No PDF found for document {doc.uuid}")
        logger.debug("Opening label file for %s...", pdf.name)
        create_label(pdf, dataset, doc.uuid, autolabel=autolabel)


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
