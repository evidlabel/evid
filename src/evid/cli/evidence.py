import logging
from rich.logging import RichHandler
import requests
from io import BytesIO
import shutil
import uuid
import sys
from pathlib import Path
from bs4 import BeautifulSoup
from evid.utils.text import normalize_text
from evid.core.label_setup import clean_text_for_typst
from evid.core.pdf_metadata import extract_pdf_metadata  # Moved to new file
from evid.core.label import create_label  # Moved to new file
import arrow
import yaml
from evid.core.models import InfoModel  # Added for validation
import hashlib
from rich.console import Console
from rich.table import Table


# Configure Rich handler for colored logging
logging.basicConfig(handlers=[RichHandler(rich_tracebacks=True)], level=logging.INFO)
logger = logging.getLogger(__name__)


def to_plain_dict(data):
    """Recursively convert data to plain dict with string values."""
    if isinstance(data, dict):
        return {k: to_plain_dict(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [to_plain_dict(v) for v in data]
    else:
        return str(data)


def add_evidence(
    directory: Path, dataset: str, source: str, label: bool = False
) -> None:
    """Add a PDF or text content to the specified dataset."""
    is_url = source.startswith("http://") or source.startswith("https://")
    file_name = None
    is_pdf = False
    pdf_file = None
    text_content = None

    if is_url:
        try:
            response = requests.get(source, timeout=10)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            file_name = source.split("/")[-1] or "document"

            if "application/pdf" in content_type:
                pdf_file = BytesIO(response.content)
                file_name = Path(file_name).stem + ".pdf"
                is_pdf = True
                content_bytes = pdf_file.getvalue()
            else:
                soup = BeautifulSoup(response.text, "html.parser")
                for elem in soup(["script", "style", "head", "nav", "footer"]):
                    elem.decompose()
                text_content = soup.get_text(separator="\n", strip=True)
                text_content = clean_text_for_typst(normalize_text(text_content))
                file_name = Path(file_name).stem + ".txt"
                is_pdf = False
                content_bytes = text_content.encode("utf-8")
        except requests.RequestException as e:
            sys.exit(f"Failed to download content: {str(e)}")
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
    unique_dir = directory / dataset / unique_id.hex

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

    label_str = title.replace(" ", "_").lower()

    target_path = unique_dir / file_name
    if is_url:
        if is_pdf:
            pdf_file.seek(0)
            with target_path.open("wb") as f:
                f.write(pdf_file.getvalue())
        else:
            with target_path.open("w", encoding="utf-8") as f:
                f.write(text_content)
    else:
        shutil.copy2(pdf_file, target_path)

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

    if label:
        logger.info(f"Generating and opening label file for {file_name}...")
        create_label(target_path, dataset, unique_id.hex)


def get_evidence_list(directory: Path, dataset: str) -> list[dict]:
    """Return a list of document metadata in the dataset."""
    dataset_path = directory / dataset
    documents = []
    for d in dataset_path.iterdir():
        if d.is_dir() and not d.name.startswith("."):
            info_path = d / "info.yml"
            if info_path.exists():
                try:
                    with info_path.open("r") as f:
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
        else:
            sys.exit("Invalid number.")
    except ValueError:
        sys.exit("Invalid selection.")


def label_evidence(directory: Path, dataset: str = None, uuid: str = None) -> None:
    """Label a document in the specified dataset."""
    from evid.cli.dataset import select_dataset

    if not dataset:
        dataset = select_dataset(
            directory, "Select dataset to label", allow_create=False
        )

    if not uuid:
        uuid = select_evidence(directory, dataset)

    evidence_path = directory / dataset / uuid
    if not evidence_path.exists():
        sys.exit(f"Document {uuid} in {dataset} does not exist.")

    files = list(evidence_path.glob("*.pdf")) + list(evidence_path.glob("*.txt"))
    if not files:
        sys.exit("No PDF or TXT found in document directory.")
    if len(files) > 1:
        logger.warning("Multiple files found, using the first one.")
    file_path = files[0]

    create_label(file_path, dataset, uuid)
