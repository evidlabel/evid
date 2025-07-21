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
from evid.core.label_setup import clean_text_for_latex
from evid.core.pdf_metadata import extract_pdf_metadata  # Moved to new file
from evid.core.label import create_label  # Moved to new file
import arrow
import yaml


# Configure Rich handler for colored logging
logging.basicConfig(handlers=[RichHandler(rich_tracebacks=True)], level=logging.INFO)
logger = logging.getLogger(__name__)


def add_evidence(
    directory: Path, dataset: str, source: str, label: bool = False
) -> None:
    """Add a PDF or text content to the specified dataset."""
    unique_dir = directory / dataset / str(uuid.uuid4())
    unique_dir.mkdir(parents=True)

    is_url = source.startswith("http://") or source.startswith("https://")

    if is_url:
        try:
            response = requests.get(source, timeout=10)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            file_name = source.split("/")[-1] or "document"

            if "application/pdf" in content_type:
                pdf_file = BytesIO(response.content)
                file_name = Path(file_name).stem + ".pdf"
            else:
                soup = BeautifulSoup(response.text, "html.parser")
                for elem in soup(["script", "style", "head", "nav", "footer"]):
                    elem.decompose()
                text_content = soup.get_text(separator="\n", strip=True)
                text_content = clean_text_for_latex(normalize_text(text_content))
                file_name = Path(file_name).stem + ".txt"
                title = normalize_text(file_name)
                authors = ""
                date = ""
                label_file = unique_dir / "label.tex"
                latex_content = (
                    LATEX_TEMPLATE.replace("BODY", text_content)
                    .replace("DATE", arrow.now().format("YYYY-MM-DD"))
                    .replace("NAME", title.replace("_", " "))
                )
                with label_file.open("w", encoding="utf-8") as f:
                    f.write(latex_content)
                info = {
                    "original_name": file_name,
                    "uuid": unique_dir.name,
                    "time_added": arrow.now().format("YYYY-MM-DD"),
                    "dates": date,
                    "title": title,
                    "authors": authors,
                    "tags": "",
                    "label": title.replace(" ", "_").lower(),
                    "url": source,
                }
                info_yaml_path = unique_dir / "info.yml"
                with info_yaml_path.open("w", encoding="utf-8") as f:
                    yaml.dump(info, f, allow_unicode=True)
                yaml.dump(info, sys.stdout, allow_unicode=True)
                logger.info(f"Added text content to {unique_dir}")
                return
        except requests.RequestException as e:
            sys.exit(f"Failed to download content: {str(e)}")
    else:
        file_path = Path(source)
        if not file_path.exists():
            sys.exit(f"File {file_path} does not exist.")
        if file_path.suffix.lower() != ".pdf":
            sys.exit("File must be a PDF.")
        file_name = file_path.name
        pdf_file = file_path

    title, authors, date = extract_pdf_metadata(pdf_file, file_name)
    label_str = title.replace(" ", "_").lower()

    target_path = unique_dir / file_name
    if is_url:
        with target_path.open("wb") as f:
            pdf_file.seek(0)
            f.write(pdf_file.getvalue())
    else:
        shutil.copy2(pdf_file, target_path)

    info = {
        "original_name": file_name,
        "uuid": unique_dir.name,
        "time_added": arrow.now().format("YYYY-MM-DD"),
        "dates": date,
        "title": title,
        "authors": authors,
        "tags": "",
        "label": label_str,
        "url": source if is_url else "",
    }

    info_yaml_path = unique_dir / "info.yml"
    with info_yaml_path.open("w", encoding="utf-8") as f:
        yaml.dump(info, f, allow_unicode=True)

    yaml.dump(info, sys.stdout, allow_unicode=True)

    logger.info(f"Added evidence to {unique_dir}")

    if label:
        logger.info(f"Generating and opening label file for {file_name}...")
        create_label(target_path, dataset, unique_dir.name)


# Import LATEX_TEMPLATE for non-PDF content
from evid.core.label_setup import LATEX_TEMPLATE


def get_evidence_list(directory: Path, dataset: str) -> list[dict]:
    """Return a list of evidence metadata in the dataset."""
    dataset_path = directory / dataset
    evidences = []
    for d in dataset_path.iterdir():
        if d.is_dir() and not d.name.startswith("."):
            info_path = d / "info.yml"
            if info_path.exists():
                with info_path.open("r") as f:
                    info = yaml.safe_load(f)
                    evidences.append(
                        {
                            "uuid": d.name,
                            "title": info.get("title", d.name),
                            "authors": info.get("authors", ""),
                            "date": info.get("time_added", ""),
                        }
                    )
            else:
                evidences.append(
                    {"uuid": d.name, "title": d.name, "authors": "", "date": ""}
                )
    return evidences


def select_evidence(
    directory: Path, dataset: str, prompt_message: str = "Select evidence"
) -> str:
    """Prompt user to select an evidence from the dataset."""
    evidences = get_evidence_list(directory, dataset)
    if not evidences:
        sys.exit("No evidences found in dataset.")

    print(f"{prompt_message}:")
    for i, ev in enumerate(evidences, 1):
        print(
            f"{i}. {ev['title']} by {ev['authors']} ({ev['date']}) - {ev['uuid']}"
        )

    choice = input("Select evidence (number): ").strip()
    try:
        choice_num = int(choice)
        if 1 <= choice_num <= len(evidences):
            return evidences[choice_num - 1]["uuid"]
        else:
            sys.exit("Invalid number.")
    except ValueError:
        sys.exit("Invalid selection.")


def label_evidence(directory: Path, dataset: str = None, uuid: str = None) -> None:
    """Label an evidence in the specified dataset."""
    from evid.cli.dataset import select_dataset

    if not dataset:
        dataset = select_dataset(directory, "Select dataset to label")

    if not uuid:
        uuid = select_evidence(directory, dataset)

    evidence_path = directory / dataset / uuid
    if not evidence_path.exists():
        sys.exit(f"Evidence {uuid} in {dataset} does not exist.")

    pdf_files = list(evidence_path.glob("*.pdf"))
    if not pdf_files:
        sys.exit("No PDF found in evidence directory.")
    if len(pdf_files) > 1:
        logger.warning("Multiple PDFs found, using the first one.")
    file_path = pdf_files[0]

    create_label(file_path, dataset, uuid)
