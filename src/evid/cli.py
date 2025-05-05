import argparse
import sys
from pathlib import Path
import requests
from io import BytesIO
import PyPDF2
import arrow
import yaml
import shutil
import uuid
from evid import DEFAULT_DIR
from evid.core.dateextract import extract_dates_from_pdf


def get_datasets(directory: Path) -> list[str]:
    """Return a list of dataset names in the directory."""
    return (
        [
            d.name
            for d in directory.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]
        if directory.exists()
        else []
    )


def select_dataset(directory: Path) -> str:
    """Prompt user to select or create a dataset."""
    datasets = get_datasets(directory)
    if not datasets:
        print("No datasets found.")
        dataset = input("Enter new dataset name: ").strip()
        if dataset:
            (directory / dataset).mkdir(parents=True, exist_ok=True)
            return dataset
        sys.exit("Dataset name required.")

    print("Available datasets:")
    for i, dataset in enumerate(datasets, 1):
        print(f"{i}. {dataset}")
    print(f"{len(datasets) + 1}. Create new dataset")

    choice = input("Select dataset (number): ").strip()
    try:
        choice = int(choice)
        if choice == len(datasets) + 1:
            dataset = input("Enter new dataset name: ").strip()
            if dataset:
                (directory / dataset).mkdir(parents=True, exist_ok=True)
                return dataset
            sys.exit("Dataset name required.")
        if 1 <= choice <= len(datasets):
            return datasets[choice - 1]
    except ValueError:
        pass
    sys.exit("Invalid selection.")


def extract_pdf_metadata(pdf_source: Path | BytesIO) -> tuple[str, str, str]:
    """Extract title, authors, and date from PDF."""
    try:
        if isinstance(pdf_source, Path):
            with open(pdf_source, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                meta = reader.metadata
        else:
            pdf_source.seek(0)
            reader = PyPDF2.PdfReader(pdf_source)
            meta = reader.metadata

        title = meta.get(
            "/Title",
            Path(pdf_source.name).stem if isinstance(pdf_source, Path) else "document",
        )
        authors = meta.get("/Author", "")
        date = meta.get("/CreationDate") or meta.get("/ModDate", "")
        if date and date.startswith("D:"):
            date = f"{date[2:6]}-{date[6:8]}-{date[8:10]}"  # YYYY-MM-DD
        else:
            date = ""
    except Exception:
        title = (
            Path(pdf_source.name).stem if isinstance(pdf_source, Path) else "document"
        )
        authors = ""
        date = ""
    return title, authors, date


def add_evidence(directory: Path, dataset: str, source: str, is_url: bool) -> None:
    """Add a PDF to the specified dataset."""
    unique_dir = directory / dataset / str(uuid.uuid4())
    unique_dir.mkdir(parents=True)

    if is_url:
        try:
            response = requests.get(source, timeout=10)
            response.raise_for_status()
            if "application/pdf" not in response.headers.get("Content-Type", ""):
                sys.exit("URL must point to a PDF file.")
            pdf_file = BytesIO(response.content)
            file_name = source.split("/")[-1] or "document"
            # Ensure the file has a .pdf suffix
            file_name = Path(file_name).stem + ".pdf"
        except requests.RequestException as e:
            sys.exit(f"Failed to download PDF: {str(e)}")
    else:
        file_path = Path(source)
        if not file_path.exists():
            sys.exit(f"File {file_path} does not exist.")
        if file_path.suffix.lower() != ".pdf":
            sys.exit("File must be a PDF.")
        file_name = file_path.name
        pdf_file = file_path

    # Extract metadata
    title, authors, date = extract_pdf_metadata(pdf_file)
    label = title.replace(" ", "_").lower()

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
        "label": label,
        "url": source if is_url else "",
    }

    with (unique_dir / "info.yml").open("w") as f:
        yaml.dump(info, f)

    print(f"Added evidence to {unique_dir}")


def main():
    parser = argparse.ArgumentParser(description="evid CLI for managing PDF documents")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Add URL command
    parser_url = subparsers.add_parser("add-url", help="Add a PDF from a URL")
    parser_url.add_argument("url", help="URL of the PDF file")
    parser_url.add_argument("--dataset", help="Target dataset name")

    # Add local PDF command
    parser_local = subparsers.add_parser("add-localpdf", help="Add a local PDF file")
    parser_local.add_argument("path", help="Path to the local PDF file")
    parser_local.add_argument("--dataset", help="Target dataset name")

    args = parser.parse_args()

    directory = DEFAULT_DIR
    if args.dataset:
        dataset = args.dataset
        (directory / dataset).mkdir(parents=True, exist_ok=True)
    else:
        dataset = select_dataset(directory)

    if args.command == "add-url":
        add_evidence(directory, dataset, args.url, is_url=True)
    elif args.command == "add-localpdf":
        add_evidence(directory, dataset, args.path, is_url=False)


if __name__ == "__main__":
    main()
