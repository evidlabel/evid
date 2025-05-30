from pathlib import Path
import requests
from io import BytesIO
import pypdf
import arrow
import yaml
import shutil
import uuid
import subprocess
import sys
import logging
from bs4 import BeautifulSoup
from evid.utils.text import normalize_text
from evid.core.label_setup import textpdf_to_latex, clean_text_for_latex

logger = logging.getLogger(__name__)

def extract_pdf_metadata(
    pdf_source: Path | BytesIO, file_name: str
) -> tuple[str, str, str]:
    """Extract title, authors, and date from PDF as plain strings, preserving Danish characters."""
    try:
        if isinstance(pdf_source, Path):
            with open(pdf_source, "rb") as f:
                reader = pypdf.PdfReader(f)
                meta = reader.metadata
        else:
            pdf_source.seek(0)
            reader = pypdf.PdfReader(pdf_source)
            meta = reader.metadata

        title = normalize_text(meta.get("/Title", Path(file_name).stem))
        authors = normalize_text(meta.get("/Author", ""))
        date = normalize_text(meta.get("/CreationDate") or meta.get("/ModDate", ""))
        if date and date.startswith("D:"):
            date = f"{date[2:6]}-{date[6:8]}-{date[8:10]}"  # YYYY-MM-DD
        else:
            date = ""
    except Exception:
        title = normalize_text(Path(file_name).stem)
        authors = ""
        date = ""
    return title, authors, date

def create_label(file_path: Path, dataset: str, uuid: str) -> None:
    """Generate a LaTeX label file and open it in VS Code."""
    label_file = file_path.parent / "label.tex"
    csv_file = file_path.parent / "label.csv"
    bib_file = file_path.parent / "label_table.bib"

    try:
        if not label_file.exists():
            textpdf_to_latex(file_path, label_file)

        # Open the labeller in VS Code and wait for it to close
        subprocess.run(["code", "--wait", str(label_file)], check=True)

        # After labeller closes, check for CSV and generate BibTeX
        if csv_file.exists():
            csv_to_bib(csv_file, bib_file, exclude_note=True)
            logger.info(f"Generated BibTeX file: {bib_file}")
        else:
            logger.warning(f"CSV file {csv_file} not found after labelling")
            print(
                f"No label.csv found in {file_path.parent}. BibTeX generation skipped."
            )
    except FileNotFoundError:
        logger.error("VS Code not found. Please ensure 'code' is in your PATH.")
        print(
            "Visual Studio Code is not installed or not in your PATH. Please install VS Code or ensure the 'code' command is available."
        )
    except subprocess.SubprocessError as e:
        logger.error(f"Error opening VS Code: {str(e)}")
        print(f"Failed to open VS Code: {str(e)}")
    except Exception as e:
        logger.error(f"Error during label workflow: {str(e)}")
        print(f"An unexpected error occurred: {str(e)}")

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
                # Handle non-PDF content (e.g., HTML or plain text)
                soup = BeautifulSoup(response.text, "html.parser")
                # Extract text, removing scripts, styles, and boilerplate
                for elem in soup(["script", "style", "head", "nav", "footer"]):
                    elem.decompose()
                text_content = soup.get_text(separator="\n", strip=True)
                text_content = clean_text_for_latex(normalize_text(text_content))
                file_name = Path(file_name).stem + ".txt"
                title = normalize_text(file_name)
                authors = ""
                date = ""
                # Save text content to label.tex directly
                label_file = unique_dir / "label.tex"
                latex_content = LATEX_TEMPLATE.replace("BODY", text_content).replace(
                    "DATE", arrow.now().format("YYYY-MM-DD")
                ).replace("NAME", title.replace("_", " "))
                with label_file.open("w", encoding="utf-8") as f:
                    f.write(latex_content)
                # Save metadata
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
                print(f"\nAdded text content to {unique_dir}")
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

    # Extract metadata for PDF
    title, authors, date = extract_pdf_metadata(pdf_file, file_name)
    label_str = title.replace(" ", "_").lower()

    # Save PDF
    target_path = unique_dir / file_name
    if is_url:
        with target_path.open("wb") as f:
            pdf_file.seek(0)
            f.write(pdf_file.getvalue())
    else:
        shutil.copy2(pdf_file, target_path)

    # Save metadata
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

    # Print info.yml content to stdout
    yaml.dump(info, sys.stdout, allow_unicode=True)

    print(f"\nAdded evidence to {unique_dir}")

    # Trigger labeling if --label flag is set
    if label:
        print(f"\nGenerating and opening label file for {file_name}...")
        create_label(target_path, dataset, unique_dir.name)

# Import LATEX_TEMPLATE for non-PDF content
from evid.core.label_setup import LATEX_TEMPLATE
from evid.core.label_setup import csv_to_bib
