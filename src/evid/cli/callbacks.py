"""CLI callback functions."""
import sys
from pathlib import Path
import logging
from rich.logging import RichHandler
from evid import CONFIG
from evid.cli.dataset import (
    list_datasets,
    select_dataset,
    create_dataset,
    track_dataset,
    get_datasets,
)

from evid.cli.evidence import label_evidence, select_evidence, get_evidence_list
from evid.core.bibtex import generate_bibtex
from evid.core.models import ConfigModel
from evid.core.rebut_doc import rebut_doc
from evid.cli.evidence import add_evidence
import yaml
from rich.console import Console
from rich.table import Table
import argparse

# Set up logging with Rich handler
logging.basicConfig(handlers=[RichHandler()], level=logging.DEBUG, rich_tracebacks=True)
logger = logging.getLogger(__name__)

DIRECTORY = None


def set_directory():
    global DIRECTORY
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-d", "--directory", default=CONFIG["default_dir"])
    args, unknown = parser.parse_known_args()
    DIRECTORY = Path(args.directory).expanduser()
    sys.argv = [sys.argv[0]] + unknown


# Define callbacks
def create_callback(dataset: str = None):
    """Create a new dataset."""
    if not dataset:
        dataset = input("Enter new dataset name: ").strip()
        if not dataset:
            sys.exit("No dataset name provided.")
    create_dataset(DIRECTORY, dataset)


def track_callback(dataset: str = None):
    """Track a dataset with Git."""
    if not dataset:
        dataset = select_dataset(DIRECTORY, "Select dataset to track")
    elif dataset.isdigit():
        datasets = sorted(get_datasets(DIRECTORY))
        try:
            index = int(dataset) - 1
            if 0 <= index < len(datasets):
                dataset = datasets[index]
            else:
                sys.exit(f"Invalid dataset number: {dataset}")
        except ValueError:
            sys.exit(f"Invalid dataset number: {dataset}")
    track_dataset(DIRECTORY, dataset)


def list_datasets_callback():
    """List all available datasets."""
    list_datasets(DIRECTORY)


def add_callback(
    source: str, label: bool = False, autolabel: bool = False, dataset: str = None
):
    """Add evidence from source."""
    if dataset and dataset.isdigit():
        datasets = sorted(get_datasets(DIRECTORY))
        try:
            index = int(dataset) - 1
            if 0 <= index < len(datasets):
                dataset = datasets[index]
            else:
                sys.exit(f"Invalid dataset number: {dataset}")
        except ValueError:
            sys.exit(f"Invalid dataset number: {dataset}")
    if dataset:
        if not (DIRECTORY / dataset).exists():
            sys.exit(
                f"Dataset '{dataset}' does not exist. Create it with 'evid set create'."
            )
    else:
        dataset = select_dataset(DIRECTORY, "Select dataset for adding document")
    add_evidence(DIRECTORY, dataset, source, label, autolabel)


def bibtex_callback(dataset: str = None, uuid: str = None):
    """Generate BibTeX for document."""
    if not dataset:
        dataset = select_dataset(
            DIRECTORY, "Select dataset for BibTeX generation", allow_create=False
        )
    if not uuid:
        uuid = select_evidence(DIRECTORY, dataset)
    typ_file = DIRECTORY / dataset / uuid / "label.typ"
    if not typ_file.exists():
        sys.exit(f"label.typ not found in {dataset}/{uuid}")
    generate_bibtex([typ_file])


def label_callback(dataset: str = None, uuid: str = None, filename: str = "label.typ"):
    """Label a document."""
    if dataset and dataset.isdigit():
        datasets = sorted(get_datasets(DIRECTORY))
        try:
            index = int(dataset) - 1
            if 0 <= index < len(datasets):
                dataset = datasets[index]
            else:
                sys.exit(
                    f"Invalid dataset number: {dataset}. Use 'evid set list' to see available datasets."
                )
        except ValueError:
            sys.exit(f"Invalid dataset number: {dataset}")

    if not dataset:
        dataset = select_dataset(
            DIRECTORY, "Select dataset to label", allow_create=False
        )
    elif not (DIRECTORY / dataset).exists():
        sys.exit(f"Dataset '{dataset}' does not exist.")

    label_evidence(DIRECTORY, dataset, uuid, filename)


def rebut_callback(dataset: str = None, uuid: str = None):
    """Generate rebuttal for document."""
    if dataset and dataset.isdigit():
        datasets = sorted(get_datasets(DIRECTORY))
        try:
            index = int(dataset) - 1
            if 0 <= index < len(datasets):
                dataset = datasets[index]
            else:
                sys.exit(
                    f"Invalid dataset number: {dataset}. Use 'evid set list' to see available datasets."
                )
        except ValueError:
            sys.exit(f"Invalid dataset number: {dataset}")

    if not dataset:
        dataset = select_dataset(
            DIRECTORY, "Select dataset for rebuttal", allow_create=False
        )
    elif not (DIRECTORY / dataset).exists():
        sys.exit(f"Dataset '{dataset}' does not exist.")

    if not uuid:
        uuid = select_evidence(DIRECTORY, dataset, "Select document for rebuttal")

    workdir = DIRECTORY / dataset / uuid
    if not workdir.exists():
        sys.exit(f"Document directory {workdir} does not exist.")

    try:
        rebut_doc(workdir)
        print(f"Rebuttal generated for {dataset}/{uuid}")
    except Exception as e:
        sys.exit(f"Failed to generate rebuttal: {str(e)}")


def list_docs_callback(dataset: str = None, uuid: str = None):
    """List documents in dataset."""
    if dataset and dataset.isdigit():
        datasets = sorted(get_datasets(DIRECTORY))
        try:
            index = int(dataset) - 1
            if 0 <= index < len(datasets):
                dataset = datasets[index]
            else:
                sys.exit(
                    f"Invalid dataset number: {dataset}. Use 'evid set list' to see available datasets."
                )
        except ValueError:
            sys.exit(f"Invalid dataset number: {dataset}")

    if not dataset:
        dataset = select_dataset(
            DIRECTORY, "Select dataset to list", allow_create=False
        )
    elif not (DIRECTORY / dataset).exists():
        sys.exit(f"Dataset '{dataset}' does not exist.")

    if uuid:
        print(
            f"Listing specific document {uuid} in {dataset} (details not implemented)"
        )
        return

    documents = get_evidence_list(DIRECTORY, dataset)
    if not documents:
        print("No documents found.")
        return

    console = Console()
    table = Table(title=f"Documents in {dataset}")
    table.add_column("Nr", justify="right")
    table.add_column("Date")
    table.add_column("UUID")
    table.add_column("Label")

    for i, ev in enumerate(documents, 1):
        table.add_row(str(i), ev["date"], ev["uuid"], ev["title"])

    console.print(table)


def gui_callback():
    """Launch the GUI."""
    try:
        from evid.gui.main import main as gui_main
        gui_main(DIRECTORY)
    except ImportError:
        print("GUI requires PySide6. Install with: pip install pyside6")
        sys.exit(1)


def update_callback():
    """Update configuration file."""
    config_path = Path.home() / ".evidrc"
    if config_path.exists():
        try:
            with config_path.open("r") as f:
                user_config = yaml.safe_load(f) or {}
        except yaml.YAMLError:
            user_config = {}
            print("Invalid YAML in .evidrc, starting fresh.")
    else:
        user_config = {}

    # Validate and fill missing with defaults using Pydantic
    try:
        config_model = ConfigModel(**user_config)
    except ValueError:
        # If validation fails, use defaults and override with valid user values
        default_config = ConfigModel().model_dump()
        merged = {**default_config, **user_config}
        config_model = ConfigModel(**merged)  # Re-validate merged

    config = config_model.model_dump()

    # Write back the complete config
    with config_path.open("w") as f:
        yaml.dump(config, f, allow_unicode=True)

    action = "updated" if config_path.exists() else "created"
    print(f".evidrc {action} at {config_path} with complete default fields.")


def show_callback():
    """Show current configuration."""
    config_path = Path.home() / ".evidrc"
    defaults = ConfigModel().model_dump()
    user_config = {}
    if config_path.exists():
        try:
            with config_path.open("r") as f:
                user_config = yaml.safe_load(f) or {}
        except yaml.YAMLError:
            print("Invalid YAML in .evidrc, using defaults.")
            user_config = {}

    # Merged config (similar to load_config)
    try:
        config_model = ConfigModel(**user_config)
        merged = config_model.model_dump()
    except ValueError:
        merged = {**defaults, **user_config}
        config_model = ConfigModel(**merged)
        merged = config_model.model_dump()

    print(
        f"Config file: {config_path if config_path.exists() else 'Not found, using defaults'}"
    )
    print("Current settings:")
    for key, value in merged.items():
        if key in user_config and user_config[key] != defaults.get(key):
            source = f"overridden in {config_path}"
        else:
            source = "default"
        print(f"  {key}: {value} ({source})")
