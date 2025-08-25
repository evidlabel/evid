import sys
from pathlib import Path
import logging
from rich.logging import RichHandler
import click
from treeclick import TreeGroup, TreeCommand
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
from evid.gui.main import main as gui_main
from evid.core.models import ConfigModel  # For config commands
from evid.core.rebut_doc import rebut_doc  # For rebut command
from evid.cli.evidence import add_evidence  # Import add_evidence for set add
import yaml
from rich.console import Console
from rich.table import Table

# Set up logging with Rich handler
logging.basicConfig(handlers=[RichHandler()], level=logging.DEBUG, rich_tracebacks=True)
logger = logging.getLogger(__name__)


@click.group(
    cls=TreeGroup,
    invoke_without_command=True,
    help="evid CLI for managing PDF documents",
    context_settings={"help_option_names": ["-h", "--help"]},
    use_tree=True,
    max_width=120,
)
@click.option(
    "-d",
    "--directory",
    default=CONFIG["default_dir"],
    help=f"Directory for storing datasets (default: {CONFIG['default_dir']})",
)
@click.pass_context
def main(ctx, directory: str):
    """evid CLI for managing PDF documents."""
    ctx.ensure_object(dict)
    ctx.obj["directory"] = Path(directory).expanduser()
    if ctx.invoked_subcommand is None:
        gui_main(ctx.obj["directory"])


# Dataset management group
set = TreeGroup(
    name="set",
    help="Manage datasets",
    params=[
        click.Option(
            ["-s", "--dataset"],
            help="Dataset name or number",
        )
    ],
)
main.add_command(set)


@set.command(name="create", cls=TreeCommand, help="Create a new dataset")
@click.pass_obj
def create(obj):
    directory = obj["directory"]
    dataset = obj.get("dataset")
    if not dataset:
        dataset = input("Enter new dataset name: ").strip()
        if not dataset:
            sys.exit("No dataset name provided.")
    create_dataset(directory, dataset)


@set.command(name="track", cls=TreeCommand, help="Track a dataset with Git")
@click.pass_obj
def track(obj):
    directory = obj["directory"]
    dataset = obj.get("dataset")
    if not dataset:
        dataset = select_dataset(directory, "Select dataset to track")
    elif dataset.isdigit():
        datasets = sorted(get_datasets(directory))
        try:
            index = int(dataset) - 1
            if 0 <= index < len(datasets):
                dataset = datasets[index]
            else:
                sys.exit(f"Invalid dataset number: {dataset}")
        except ValueError:
            sys.exit(f"Invalid dataset number: {dataset}")
    track_dataset(directory, dataset)


@set.command(name="list", cls=TreeCommand, help="List all available datasets")
@click.pass_obj
def list_cmd(obj):
    directory = obj["directory"]
    list_datasets(directory)


@set.command(
    name="add", cls=TreeCommand, help="Add a PDF from a URL or local file to a dataset"
)
@click.argument("source")
@click.option(
    "-l", "--label", is_flag=True, help="Open the labeler after adding the PDF"
)
@click.pass_obj
def set_add(obj, source: str, label: bool):
    directory = obj["directory"]
    dataset = obj.get("dataset")
    if dataset and dataset.isdigit():
        datasets = sorted(get_datasets(directory))
        try:
            index = int(dataset) - 1
            if 0 <= index < len(datasets):
                dataset = datasets[index]
            else:
                sys.exit(f"Invalid dataset number: {dataset}")
        except ValueError:
            sys.exit(f"Invalid dataset number: {dataset}")
    if dataset:
        if not (directory / dataset).exists():
            sys.exit(
                f"Dataset '{dataset}' does not exist. Create it with 'evid set create'."
            )
    else:
        dataset = select_dataset(directory, "Select dataset for adding document")
    add_evidence(directory, dataset, source, label)


# Document management group
@main.group(
    cls=TreeGroup,
    name="doc",
    help="Manage documents",
)
@click.option("-s", "--dataset", help="Dataset name")
@click.option("-u", "--uuid", help="UUID of the document")
@click.pass_obj
def doc(obj, dataset: str, uuid: str):
    obj["dataset"] = dataset
    obj["uuid"] = uuid


@doc.command(
    name="bibtex", cls=TreeCommand, help="Generate BibTeX files from label.typ files"
)
@click.pass_obj
def bibtex(obj):
    directory = obj["directory"]
    dataset = obj.get("dataset")
    if not dataset:
        dataset = select_dataset(
            directory, "Select dataset for BibTeX generation", allow_create=False
        )
    uuid = obj.get("uuid")
    if not uuid:
        uuid = select_evidence(directory, dataset)
    typ_file = directory / dataset / uuid / "label.typ"
    if not typ_file.exists():
        sys.exit(f"label.typ not found in {dataset}/{uuid}")
    generate_bibtex([typ_file])


@doc.command(name="label", cls=TreeCommand, help="Label a document in a dataset")
@click.pass_obj
def label(obj):
    directory = obj["directory"]
    dataset = obj.get("dataset")
    if dataset and dataset.isdigit():
        # Interpret as index from sorted dataset list
        datasets = sorted(get_datasets(directory))
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
            directory, "Select dataset to label", allow_create=False
        )
    elif not (directory / dataset).exists():
        sys.exit(f"Dataset '{dataset}' does not exist.")

    uuid = obj.get("uuid")
    label_evidence(directory, dataset, uuid)


@doc.command(
    name="rebut", cls=TreeCommand, help="Generate rebuttal for a document in a dataset"
)
@click.pass_obj
def rebut(obj):
    directory = obj["directory"]
    dataset = obj.get("dataset")
    if dataset and dataset.isdigit():
        # Interpret as index from sorted dataset list
        datasets = sorted(get_datasets(directory))
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
            directory, "Select dataset for rebuttal", allow_create=False
        )
    elif not (directory / dataset).exists():
        sys.exit(f"Dataset '{dataset}' does not exist.")

    uuid = obj.get("uuid")
    if not uuid:
        uuid = select_evidence(directory, dataset, "Select document for rebuttal")

    workdir = directory / dataset / uuid
    if not workdir.exists():
        sys.exit(f"Document directory {workdir} does not exist.")

    try:
        rebut_doc(workdir)
        print(f"Rebuttal generated for {dataset}/{uuid}")
    except Exception as e:
        sys.exit(f"Failed to generate rebuttal: {str(e)}")


@doc.command(name="list", cls=TreeCommand, help="List documents in the dataset")
@click.pass_obj
def list_docs(obj):
    directory = obj["directory"]
    dataset = obj.get("dataset")
    if dataset and dataset.isdigit():
        # Interpret as index from sorted dataset list
        datasets = sorted(get_datasets(directory))
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
            directory, "Select dataset to list", allow_create=False
        )
    elif not (directory / dataset).exists():
        sys.exit(f"Dataset '{dataset}' does not exist.")

    uuid = obj.get("uuid")
    if uuid:
        # If UUID provided, perhaps show details, but for now, ignore or handle
        print(
            f"Listing specific document {uuid} in {dataset} (details not implemented)"
        )
        return

    documents = get_evidence_list(directory, dataset)
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


@main.command(name="gui", cls=TreeCommand, help="Launch the evid GUI")
@click.pass_obj
def gui(obj):
    directory = obj["directory"]
    gui_main(directory)


# Config management group
config = TreeGroup(name="config", help="Deal with configuration of evid")
main.add_command(config)


@config.command(
    name="update",
    cls=TreeCommand,
    help="Initialize or update .evidrc with default settings",
)
def update():
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


@config.command(
    name="show",
    cls=TreeCommand,
    help="Show the current config settings and where they are defined",
)
def show():
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


if __name__ == "__main__":
    main()
