import sys
from pathlib import Path
import logging
from rich.logging import RichHandler
from rich.console import Console
import rich_click as click
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

# Configure rich-click for better formatting
click.rich_click.USE_RICH_MARKUP = True
click.rich_click.SHOW_ARGUMENTS = True
click.rich_click.GROUP_ARGUMENTS_OPTIONS = True

# Initialize console for rich output
console = Console()

# Set up logging with Rich handler
logging.basicConfig(handlers=[RichHandler()], level=logging.DEBUG, rich_tracebacks=True)
logger = logging.getLogger(__name__)


@click.group(
    invoke_without_command=True,
    help="evid CLI for managing PDF documents",
    context_settings={"help_option_names": ["-h", "--help"]},
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


@main.command(help="Add a PDF from a URL or local file")
@click.argument("source")
@click.option("-s", "--dataset", help="Target dataset name")
@click.option(
    "-l", "--label", is_flag=True, help="Open the labeler after adding the PDF"
)
@click.pass_obj
def add(obj, source: str, dataset: str, label: bool):
    directory = obj["directory"]
    if dataset:
        if not (directory / dataset).exists():
            sys.exit(
                f"Dataset '{dataset}' does not exist. Create it with 'evid set create'."
            )
    else:
        dataset = select_dataset(directory, "Select dataset for adding evidence")
    add_evidence(directory, dataset, source, label)


@main.group(help="Manage datasets")
def set():
    pass


@set.command(help="Create a new dataset")
@click.argument("dataset")
@click.pass_obj
def create(obj, dataset: str):
    directory = obj["directory"]
    create_dataset(directory, dataset)


@set.command(help="Track a dataset with Git")
@click.argument("dataset", required=False)
@click.pass_obj
def track(obj, dataset: str):
    directory = obj["directory"]
    track_dataset(directory, dataset)


@main.command(help="List all available datasets")
@click.pass_obj
def list(obj):
    directory = obj["directory"]
    list_datasets(directory)


# this is a path but also tuple, please fix this


@main.command(help="Generate BibTeX files from label.typ files")
@click.option("-s", "--dataset", help="Dataset name")
@click.option("-u", "--uuid", help="UUID of the evidence")
@click.pass_obj
def bibtex(obj, dataset: str, uuid: str):
    directory = obj["directory"]
    if not dataset:
        dataset = select_dataset(
            directory, "Select dataset for BibTeX generation", allow_create=False
        )

    if not uuid:
        uuid = select_evidence(directory, dataset)

    typ_file = directory / dataset / uuid / "label.typ"
    if not typ_file.exists():
        sys.exit(f"label.typ not found in {dataset}/{uuid}")

    generate_bibtex([typ_file])


@main.command(help="Launch the evid GUI")
@click.pass_obj
def gui(obj):
    directory = obj["directory"]
    gui_main(directory)


@main.command(help="Label an evidence in a dataset")
@click.option("-s", "--dataset", help="Dataset name")
@click.option("-u", "--uuid", help="UUID of the evidence")
@click.pass_obj
def label(obj, dataset: str, uuid: str):
    directory = obj["directory"]
    label_evidence(directory, dataset, uuid)


@main.command(help="Initialize or update .evidrc with default settings")
def rc():
    """Initialize or update ~/.evidrc by adding missing fields from defaults."""
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


# Custom top-level help
def print_full_help(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    console.print(
        f"\n[bold]Usage:[/bold] {ctx.command_path} [OPTIONS] COMMAND [ARGS]...\n"
    )
    console.print("[bold]Options:[/bold]")
    console.print("  --help  Show this message and exit.\n")
    console.print(f"[bold]Description:[/bold] {ctx.command.help}\n")
    console.print("[bold]Commands:[/bold]")
    for group_name, group_cmd in sorted(ctx.command.commands.items()):
        console.print(f"  [bold green]{group_name}[/bold green]  {group_cmd.help}")
        if isinstance(group_cmd, click.Group):
            for sub_name, sub_cmd in sorted(group_cmd.commands.items()):
                console.print(f"    [cyan]{sub_name}[/cyan]  {sub_cmd.help}")
                for param in sub_cmd.params:
                    if isinstance(param, click.Option):
                        opts = ", ".join(param.opts)
                        console.print(
                            f"      [yellow]{opts}[/yellow]  {param.help or ''}"
                        )
                    elif isinstance(param, click.Argument):
                        console.print(
                            f"      [yellow]{param.name}[/yellow]  {param.human_readable_name}"
                        )
    console.print()
    ctx.exit()


# Replace default --help
main.params.append(
    click.Option(
        ["--help"],
        is_flag=True,
        expose_value=False,
        is_eager=True,
        callback=print_full_help,
    )
)

if __name__ == "__main__":
    main()
