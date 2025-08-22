from pathlib import Path
import sys
import logging
from rich.console import Console
from rich.table import Table

try:
    from git import Repo
except ImportError:
    Repo = None

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
    datasets = sorted(get_datasets(directory))
    if not datasets:
        print("No datasets found.")
        return

    console = Console()
    table = Table(title="Available datasets")
    table.add_column("Nr", justify="right")
    table.add_column("Dataset")

    for i, dataset in enumerate(datasets, 1):
        table.add_row(str(i), dataset)

    console.print(table)


def select_dataset(
    directory: Path, prompt_message: str = "Select dataset", allow_create: bool = True
) -> str:
    """Prompt user to select a dataset or create a new one if allowed."""
    datasets = sorted(get_datasets(directory))
    if not datasets:
        if not allow_create:
            sys.exit("No datasets found and creation is not allowed.")
        dataset_name = input("No datasets found. Enter new dataset name: ").strip()
        if dataset_name:
            create_dataset(directory, dataset_name)
            return dataset_name
        sys.exit("No dataset name provided.")

    console = Console()
    table = Table(title=prompt_message)
    table.add_column("Nr", justify="right")
    table.add_column("Dataset")

    for i, dataset in enumerate(datasets, 1):
        table.add_row(str(i), dataset)

    console.print(table)

    choice = input(
        "Select dataset (number)"
        + (" or enter a new dataset name" if allow_create else "")
        + ": "
    ).strip()
    try:
        choice_num = int(choice)
        if 1 <= choice_num <= len(datasets):
            return datasets[choice_num - 1]
        else:
            if not allow_create:
                sys.exit("Invalid number and creation is not allowed.")
            dataset_name = input("Invalid number. Enter new dataset name: ").strip()
            if dataset_name:
                create_dataset(directory, dataset_name)
                return dataset_name
            sys.exit("No dataset name provided.")
    except ValueError:
        if not allow_create:
            sys.exit("Invalid selection and creation is not allowed.")
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
!label.bib
!*.typ
!info.yml
!*.pdf
!*.txt
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

