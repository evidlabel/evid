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
)


from evid.cli.evidence import add_evidence, label_evidence, select_evidence
from evid.core.bibtex import generate_bibtex
from evid.gui.main import main as gui_main
from evid.core.models import ConfigModel  # For rc command
import yaml

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
    help="Directory for storing datasets (default: ~/Documents/evid)",
)
@click.pass_context
def main(ctx, directory: str):
    """evid CLI for managing PDF documents."""
    ctx.ensure_object(dict)
    ctx.obj["directory"] = Path(directory).expanduser()
    if ctx.invoked_subcommand is None:
        gui_main(ctx.obj["directory"])


# Dataset management group
set = TreeGroup(name="set", help="Manage datasets")
main.add_command(set)


@set.command(name="create", cls=TreeCommand, help="Create a new dataset")
@click.argument("dataset")
@click.pass_obj
def create(obj, dataset: str):
    directory = obj["directory"]
    create_dataset(directory, dataset)


@set.command(name="track", cls=TreeCommand, help="Track a dataset with Git")
@click.argument("dataset", required=False)
@click.pass_obj
def track(obj, dataset: str):
    directory = obj["directory"]
    track_dataset(directory, dataset)


@set.command(name="list", cls=TreeCommand, help="List all available datasets")
@click.pass_obj
def list_cmd(obj):
    directory = obj["directory"]
    list_datasets(directory)


# Evidence management group
@main.group(
    cls=TreeGroup,
    name="doc",
    help="Manage evidence documents",
)
@click.option("-s", "--dataset", help="Dataset name")
@click.pass_obj
def doc(obj, dataset: str):
    obj["dataset"] = dataset


@doc.command(name="add", cls=TreeCommand, help="Add a PDF from a URL or local file")
@click.argument("source")
@click.option(
    "-l", "--label", is_flag=True, help="Open the labeler after adding the PDF"
)
@click.pass_obj
def add(obj, source: str, label: bool):
    directory = obj["directory"]
    dataset = obj.get("dataset")
    if dataset:
        if not (directory / dataset).exists():
            sys.exit(
                f"Dataset '{dataset}' does not exist. Create it with 'evid set create'."
            )
    else:
        dataset = select_dataset(directory, "Select dataset for adding evidence")
    add_evidence(directory, dataset, source, label)


@doc.command(name="bibtex", cls=TreeCommand, help="Generate BibTeX files from label.typ files")
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


@doc.command(name="label", cls=TreeCommand, help="Label an evidence in a dataset")
@click.pass_obj
def label(obj):
    directory = obj["directory"]
    dataset = obj.get("dataset")
    uuid = obj.get("uuid")
    label_evidence(directory, dataset, uuid)


@main.command(name="gui", cls=TreeCommand, help="Launch the evid GUI")
@click.pass_obj
def gui(obj):
    directory = obj["directory"]
    gui_main(directory)


@main.command(name="rc", cls=TreeCommand, help="Initialize or update .evidrc with default settings")
@click.option(
    "-s",
    "--show",
    is_flag=True,
    help="Print the config file path and content without modifying it",
)
def rc(show: bool):
    """Initialize or update ~/.evidrc by adding missing fields from defaults."""
    config_path = Path.home() / ".evidrc"
    if show:
        if config_path.exists():
            with config_path.open("r") as f:
                content = f.read()
            print(f"Config file: {config_path}")
            print("Content:")
            print(content)
        else:
            print(f"Config file does not exist: {config_path}")
        return

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


if __name__ == "__main__":
    main()

