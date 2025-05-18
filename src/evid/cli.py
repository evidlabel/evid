import argparse
import sys
from pathlib import Path
import requests
from io import BytesIO
import pypdf
import arrow
import yaml
import shutil
import uuid
import subprocess
import logging
from evid import DEFAULT_DIR
from evid.utils.text import normalize_text

try:
    from git import Repo
except ImportError:
    Repo = None

from evid.core.label_setup import textpdf_to_latex, csv_to_bib
from evid.gui.main import main as gui_main

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


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


def list_datasets(directory: Path) -> None:
    """List all available datasets."""
    datasets = get_datasets(directory)
    if not datasets:
        print("No datasets found.")
        return
    print("Available datasets:")
    for i, dataset in enumerate(datasets, 1):
        print(f"{i}. {dataset}")


def select_dataset(directory: Path, prompt_message: str = "Select dataset") -> str:
    """Prompt user to select a dataset or create a new one."""
    datasets = get_datasets(directory)
    if not datasets:
        dataset_name = input("No datasets found. Enter new dataset name: ").strip()
        if dataset_name:
            create_dataset(directory, dataset_name)
            return dataset_name
        sys.exit("No dataset name provided.")

    print(f"{prompt_message}:")
    for i, dataset in enumerate(datasets, 1):
        print(f"{i}. {dataset}")

    choice = input("Select dataset (number) or enter a new dataset name: ").strip()
    try:
        choice_num = int(choice)
        if 1 <= choice_num <= len(datasets):
            return datasets[choice_num - 1]
        else:
            dataset_name = input("Invalid number. Enter new dataset name: ").strip()
            if dataset_name:
                create_dataset(directory, dataset_name)
                return dataset_name
            sys.exit("No dataset name provided.")
    except ValueError:
        if choice:
            create_dataset(directory, choice)
            return choice
        sys.exit("Invalid selection or no dataset name provided.")


def create_dataset(directory: Path, dataset: str) -> None:
    """Create a new dataset directory, failing if it already exists."""
    dataset_path = directory / dataset
    if dataset_path.exists():
        sys.exit(f"Dataset '{dataset}' already exists.")
    dataset_path.mkdir(parents=True, exist_ok=False)
    print(f"Created dataset: {dataset_path}")


def track_dataset(directory: Path, dataset: str = None) -> None:
    """Initialize a Git repository in the specified dataset with a .gitignore."""
    if not Repo:
        logger.warning("GitPython not installed. Cannot track dataset.")
        print("GitPython is not installed. Please install it to use Git tracking.")
        return

    if not dataset:
        dataset = select_dataset(directory, "Select dataset to track")

    dataset_path = directory / dataset
    if not dataset_path.exists():
        sys.exit(f"Dataset '{dataset}' does not exist.")

    # Check if already a Git repository
    try:
        Repo(dataset_path)
        sys.exit(f"Dataset '{dataset}' is already tracked as a Git repository.")
    except:
        pass  # Not a Git repository, proceed with initialization

    try:
        # Initialize Git repository
        repo = Repo.init(dataset_path)
        # Create .gitignore file
        gitignore_content = """# Ignore everything by default
*/*
# Allow specific files
!label.csv
!label_table.bib
!*.tex
!info.yml
!*.pdf
*/label.pdf
"""
        with (dataset_path / ".gitignore").open("w") as f:
            f.write(gitignore_content)
        # Add .gitignore to the repository
        repo.index.add([".gitignore"])
        repo.index.commit("Initial commit: Add .gitignore")
        logger.info(f"Initialized Git repository for dataset: {dataset_path}")
        print(f"Initialized Git repository for dataset: {dataset_path}")
    except Exception as e:
        logger.error(
            f"Failed to initialize Git repository for {dataset_path}: {str(e)}"
        )
        sys.exit(f"Failed to initialize Git repository: {str(e)}")


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
    """Add a PDF to the specified dataset."""
    unique_dir = directory / dataset / str(uuid.uuid4())
    unique_dir.mkdir(parents=True)

    is_url = source.startswith("http://") or source.startswith("https://")

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

    # Prompt to open info.yml in VS Code
    open_vscode = (
        input("\nWould you like to open info.yml in Visual Studio Code? (y/n): ")
        .strip()
        .lower()
    )
    if open_vscode == "y":
        try:
            subprocess.run(["code", str(info_yaml_path)], check=True)
        except subprocess.SubprocessError as e:
            print(f"Failed to open info.yml in VS Code: {str(e)}")

    # Trigger labeling if --label flag is set
    if label:
        print(f"\nGenerating and opening label file for {file_name}...")
        create_label(target_path, dataset, unique_dir.name)


def main():
    parser = argparse.ArgumentParser(description="evid CLI for managing PDF documents")
    subparsers = parser.add_subparsers(dest="command")

    # Add command
    parser_add = subparsers.add_parser("add", help="Add a PDF from a URL or local file")
    parser_add.add_argument("source", help="URL or path to the PDF file")
    parser_add.add_argument("--dataset", help="Target dataset name")
    parser_add.add_argument(
        "--label", action="store_true", help="Open the labeler after adding the PDF"
    )

    # Set submenu
    parser_set = subparsers.add_parser("set", help="Manage datasets")
    set_subparsers = parser_set.add_subparsers(dest="set_command")

    # Set create command
    parser_set_create = set_subparsers.add_parser("create", help="Create a new dataset")
    parser_set_create.add_argument("dataset", help="Name of the dataset to create")

    # Set track command
    parser_set_track = subparsers.add_parser(
        "track", help="Track a dataset with Git"
    )
    parser_set_track.add_argument(
        "dataset", nargs="?", help="Name of the dataset to track"
    )

    # List datasets command
    parser_list = subparsers.add_parser("list", help="List all available datasets")

    # GUI command
    parser_gui = subparsers.add_parser("gui", help="Launch the evid GUI")
    parser_gui.add_argument(
        "--directory", default=DEFAULT_DIR, help="Directory for storing datasets"
    )

    args = parser.parse_args()

    if args.command is None:
        gui_main(DEFAULT_DIR)
    elif args.command == "add":
        directory = DEFAULT_DIR
        if args.dataset:
            dataset = args.dataset
            if not (directory / dataset).exists():
                sys.exit(
                    f"Dataset '{dataset}' does not exist. Create it with 'evid set create'."
                )
        else:
            dataset = select_dataset(directory, "Select dataset for adding evidence")
        add_evidence(directory, dataset, args.source, args.label)
    elif args.command == "set":
        if args.set_command == "create":
            create_dataset(DEFAULT_DIR, args.dataset)
        elif args.set_command == "track":
            track_dataset(DEFAULT_DIR, args.dataset)
        else:
            parser_set.print_help()
    elif args.command == "list":
        list_datasets(DEFAULT_DIR)
    elif args.command == "gui":
        gui_main(args.directory)


if __name__ == "__main__":
    main()
