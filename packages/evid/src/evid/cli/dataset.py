"""Handle dataset operations via evidmgr SetManager."""

import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

try:
    from git import InvalidGitRepositoryError, Repo
except ImportError:
    Repo = None

from evid.services.set_manager import SetManager

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path helpers — all callers use these instead of raw path arithmetic
# ---------------------------------------------------------------------------


def set_dir(directory: Path, slug: str) -> Path:
    """Return the evidmgr set directory: data_dir/sets/{slug}/."""
    return directory / "sets" / slug


def docs_dir(directory: Path, slug: str) -> Path:
    """Return the evidmgr docs directory: data_dir/sets/{slug}/docs/."""
    return directory / "sets" / slug / "docs"


# ---------------------------------------------------------------------------
# Dataset CRUD — backed by SetManager
# ---------------------------------------------------------------------------


def get_datasets(directory: Path) -> list[str]:
    """Return slugs of all sets in the evidmgr data directory."""
    sets_dir = directory / "sets"
    if not sets_dir.exists():
        return []
    return [
        d.name for d in sets_dir.iterdir() if d.is_dir() and (d / "set.yml").exists()
    ]


def list_datasets(directory: Path) -> None:
    """List all available datasets."""
    try:
        ev_sets = SetManager(directory).list_sets()
    except Exception as e:
        logger.error(f"Failed to list datasets: {e}")
        print("No datasets found.")
        return
    if not ev_sets:
        print("No datasets found.")
        return

    console = Console()
    table = Table(title="Available datasets")
    table.add_column("Nr", justify="right")
    table.add_column("Name")
    table.add_column("Slug")
    table.add_column("Type")
    table.add_column("Created")

    for i, s in enumerate(ev_sets, 1):
        table.add_row(
            str(i),
            s.name,
            s.slug,
            s.set_type.value,
            s.created.strftime("%Y-%m-%d") if s.created else "",
        )

    console.print(table)


def select_dataset(
    directory: Path, prompt_message: str = "Select dataset", allow_create: bool = True
) -> str:
    """Prompt user to select a dataset; returns slug."""
    try:
        ev_sets = SetManager(directory).list_sets()
    except Exception:
        ev_sets = []

    if not ev_sets:
        if not allow_create:
            sys.exit("No datasets found and creation is not allowed.")
        name = input("No datasets found. Enter new dataset name: ").strip()
        if name:
            return create_dataset(directory, name)
        sys.exit("No dataset name provided.")

    console = Console()
    table = Table(title=prompt_message)
    table.add_column("Nr", justify="right")
    table.add_column("Name")
    table.add_column("Slug")

    for i, s in enumerate(ev_sets, 1):
        table.add_row(str(i), s.name, s.slug)

    console.print(table)

    choice = input(
        "Select dataset (number)"
        + (" or enter a new dataset name" if allow_create else "")
        + ": "
    ).strip()
    try:
        choice_num = int(choice)
        if 1 <= choice_num <= len(ev_sets):
            return ev_sets[choice_num - 1].slug
        if not allow_create:
            sys.exit("Invalid number and creation is not allowed.")
        name = input("Invalid number. Enter new dataset name: ").strip()
        if name:
            return create_dataset(directory, name)
        sys.exit("No dataset name provided.")
    except ValueError:
        if not allow_create:
            sys.exit("Invalid selection and creation is not allowed.")
        if choice:
            return create_dataset(directory, choice)
        sys.exit("Invalid selection or no dataset name provided.")


def create_dataset(directory: Path, name: str) -> str:
    """Create a new evidmgr set; return its slug."""
    try:
        ev_set = SetManager(directory).create_set(name)
        print(f"Created dataset '{ev_set.name}' (slug: {ev_set.slug}) at {ev_set.path}")
        return ev_set.slug
    except FileExistsError:
        sys.exit(f"Dataset '{name}' already exists.")
    except Exception as e:
        sys.exit(f"Failed to create dataset: {e}")


def track_dataset(directory: Path, dataset: str = None) -> None:
    """Initialize a Git repository in the specified dataset with a .gitignore."""
    if not Repo:
        logger.warning("GitPython not installed. Cannot track dataset.")
        print("GitPython is not installed. Please install it to use Git tracking.")
        return

    if not dataset:
        dataset = select_dataset(directory, "Select dataset to track")

    dataset_path = set_dir(directory, dataset)
    if not dataset_path.exists():
        sys.exit(f"Dataset '{dataset}' does not exist.")

    try:
        Repo(dataset_path)
        sys.exit(f"Dataset '{dataset}' is already tracked as a Git repository.")
    except InvalidGitRepositoryError:
        pass

    try:
        repo = Repo.init(dataset_path)
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
        with (dataset_path / ".gitignore").open("w", encoding="utf-8") as f:
            f.write(gitignore_content)
        repo.index.add([".gitignore"])
        repo.index.commit("Initial commit: Add .gitignore")
        logger.info(f"Initialized Git repository for dataset: {dataset_path}")
        print(f"Initialized Git repository for dataset: {dataset_path}")
    except Exception as e:
        logger.error(f"Failed to initialize Git repository for {dataset_path}: {e!s}")
        sys.exit(f"Failed to initialize Git repository: {e!s}")
