"""Handle evidence addition and management."""

import hashlib
import logging
import shutil
import sys
import tempfile
import uuid
from io import BytesIO
from pathlib import Path

import arrow
import requests
import yaml
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from evid.cli.dataset import docs_dir
from evid.core.label import create_label  # Moved to new file
from evid.core.models import InfoModel  # Added for validation
from evid.core.pdf_metadata import extract_pdf_metadata  # Moved to new file
from evid.core.typst_generation import _BROWSER_HEADERS, web_to_pdf
from evid.utils.text import normalize_text

# Configure Rich handler for colored logging
logging.basicConfig(handlers=[RichHandler(rich_tracebacks=True)], level=logging.INFO)
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
) -> None:
    """Add a PDF or text content to the specified dataset."""
    is_url = source.startswith(("http://", "https://"))
    file_name = None
    is_pdf = False
    pdf_file = None
    web_page_title = ""  # set when an HTML page is rendered to PDF via Typst
    _web_tmp = None  # tempdir kept alive until target_path is written

    if is_url:
        try:
            response = requests.get(source, timeout=15, headers=_BROWSER_HEADERS)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            file_name = source.rsplit("/", maxsplit=1)[-1] or "document"

            if "application/pdf" in content_type:
                pdf_file = BytesIO(response.content)
                file_name = Path(file_name).stem + ".pdf"
                is_pdf = True
                content_bytes = pdf_file.getvalue()
            else:
                # HTML — mirror the GUI's IngestUrlWorker: render the page to a
                # Typst-generated PDF, then route through the PDF code path.
                _web_tmp = tempfile.TemporaryDirectory()
                rendered_pdf, web_page_title = web_to_pdf(
                    source,
                    Path(_web_tmp.name),
                    html=response.text,
                )
                pdf_file = BytesIO(rendered_pdf.read_bytes())
                file_name = rendered_pdf.name
                is_pdf = True
                content_bytes = pdf_file.getvalue()
        except requests.RequestException as e:
            sys.exit(f"Failed to download content: {e!s}")
    else:
        file_path = Path(source)
        if not file_path.exists():
            sys.exit(f"File {file_path} does not exist.")
        if file_path.suffix.lower() != ".pdf":
            sys.exit("File must be a PDF.")
        file_name = file_path.name
        with open(file_path, "rb") as f:
            content_bytes = f.read()
        pdf_file = file_path
        is_pdf = True

    # Compute content-based UUID
    digest = hashlib.sha256(content_bytes).digest()[:16]
    unique_id = uuid.UUID(bytes=digest)
    unique_dir = docs_dir(directory, dataset) / unique_id.hex

    if unique_dir.exists():
        print(f"This document is already added in {dataset} at {unique_id.hex}")
        return

    unique_dir.mkdir(parents=True)

    # Extract metadata if PDF, else set defaults
    if is_pdf:
        if is_url:
            pdf_file.seek(0)
        pdf_source = pdf_file if is_url else pdf_file
        title, authors, date = extract_pdf_metadata(pdf_source, file_name)
    else:
        title = normalize_text(Path(file_name).stem)
        authors = ""
        date = ""

    # For HTML pages rendered to PDF via Typst, prefer the parsed <title> and the
    # page host over whatever extract_pdf_metadata pulled from the Typst output
    # (which is usually empty / placeholder).
    if web_page_title:
        title = web_page_title
        if not authors:
            from urllib.parse import urlparse

            authors = urlparse(source).netloc

    label_str = title.replace(" ", "_").lower()

    target_path = unique_dir / file_name
    if is_url:
        pdf_file.seek(0)
        with target_path.open("wb") as f:
            f.write(pdf_file.getvalue())
    else:
        shutil.copy2(pdf_file, target_path)
    if _web_tmp is not None:
        _web_tmp.cleanup()

    info = {
        "original_name": file_name,
        "uuid": unique_id.hex,
        "time_added": arrow.now().format("YYYY-MM-DD"),
        "dates": date,
        "title": title,
        "authors": authors,
        "tags": "",
        "label": label_str,
        "url": source if is_url else "",
    }

    # Validate with Pydantic
    try:
        validated_info = InfoModel(**info)
        info = validated_info.model_dump()
    except ValueError as e:
        logger.error(f"Validation error for info.yml: {e}")
        sys.exit(f"Validation failed: {e}")

    info_yaml_path = unique_dir / "info.yml"
    with info_yaml_path.open("w", encoding="utf-8") as f:
        yaml.dump(info, f, allow_unicode=True)

    yaml.dump(info, sys.stdout, allow_unicode=True)

    logger.info(f"Added document to {unique_dir}")

    # Generate label.typ so the vector index has text to embed
    from evid.core.typst_generation import (
        text_to_typst,
        textpdf_to_typst,
    )

    typ_path = unique_dir / "label.typ"
    try:
        Path("static").mkdir(exist_ok=True)
        if is_pdf:
            textpdf_to_typst(target_path, typ_path)
        else:
            text_to_typst(target_path, typ_path)
        logger.info("Generated label.typ for %s", unique_id.hex)
    except Exception as e:
        logger.warning("label.typ generation failed for %s: %s", unique_id.hex, e)

    # Vector index
    try:
        from evid.services.doc_ingester import DocIngester
        from evid.services.set_manager import SetManager
        from evid.services.vec_service import VecService

        evidence_set = SetManager(directory).load_set(dataset)
        DocIngester(vec_service=VecService()).index_existing(unique_dir, evidence_set)
        logger.info("Indexed %s into vector store", unique_id.hex)
    except Exception as e:
        logger.warning(
            "Vector indexing failed for %s (run 'evid set index' to retry): %s",
            unique_id.hex,
            e,
        )

    if label:
        logger.info(f"Opening label file for {file_name}...")
        create_label(target_path, dataset, unique_id.hex, autolabel=autolabel)


def get_evidence_list(directory: Path, dataset: str) -> list[dict]:
    """Return a list of document metadata in the dataset."""
    dataset_path = docs_dir(directory, dataset)
    documents = []
    for d in dataset_path.iterdir():
        if d.is_dir() and not d.name.startswith("."):
            info_path = d / "info.yml"
            if info_path.exists():
                try:
                    with info_path.open("r", encoding="utf-8") as f:
                        info = yaml.load(f, Loader=yaml.FullLoader)
                    if info is None:
                        logger.warning(
                            f"Empty or invalid YAML in {info_path}. Skipping."
                        )
                        continue
                    info = to_plain_dict(info)
                    # Validate with Pydantic
                    validated_info = InfoModel(**info)
                    info = validated_info.model_dump()
                except (yaml.YAMLError, ValueError, TypeError) as e:
                    logger.warning(
                        f"Error loading or validating {info_path}: {e}. Skipping."
                    )
                    continue
                documents.append(
                    {
                        "uuid": d.name,
                        "title": info.get("title", d.name),
                        "authors": info.get("authors", ""),
                        "date": info.get("time_added", ""),
                    }
                )
            else:
                documents.append(
                    {"uuid": d.name, "title": d.name, "authors": "", "date": ""}
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
