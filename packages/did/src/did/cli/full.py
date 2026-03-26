"""Full command for CLI: chains extraction and typst pseudonymization."""

import sys
from pathlib import Path

from rich.rule import Rule
from ruamel import yaml
from treeparse import argument, command, option

from ..core.anonymizer import Anonymizer
from ..utils.console import console, print_counts
from ..utils.file_utils import export_to_typst, extract_text


def full(file, output, language):
    """Extract entities from input file, generate config, then pseudonymize to Typst."""
    input_path = Path(file)
    if not input_path.exists():
        console.print(f"[red]Error:[/red] Input file {file} not found.")
        sys.exit(1)
    if output is None:
        output = str(input_path.with_suffix(".typ"))
    output_path = Path(output)
    if output_path.suffix != ".typ":
        console.print("[red]Error:[/red] Output file must end with .typ")
        sys.exit(1)

    stem = input_path.stem
    config_file = input_path.parent / f"{stem}_config.yaml"

    try:
        console.print(Rule("full"))
        console.print("[bold]Step 1:[/bold] Extracting entities...")
        anonymizer = Anonymizer(language=language)
        text = extract_text(input_path)
        anonymizer.detect_entities([text])

        console.print("[bold]Detected entities:[/bold]")
        print_counts(anonymizer.counts, "found")

        yaml_str = anonymizer.generate_yaml()
        with open(config_file, "w") as f:
            f.write(yaml_str)
        console.print(f"Config written to [cyan]{config_file}[/cyan]")

        console.print("[bold]Step 2:[/bold] Pseudonymizing to Typst...")
        pseudo_anonymizer = Anonymizer()
        yaml_obj = yaml.YAML()
        with open(config_file) as f:
            config_data = yaml_obj.load(f) or {}
        pseudo_anonymizer.load_replacements(config_data)
        export_to_typst(input_path, pseudo_anonymizer, output_path)

        console.print("[bold]Replacement counts:[/bold]")
        print_counts(pseudo_anonymizer.counts, "replaced")

        parent = output_path.parent
        vars_path = parent / f"{stem}_vars.typ"
        fake_path = parent / f"{stem}_fakevars.typ"
        console.print(f"\nTypst files written to [cyan]{parent}[/cyan]")
        for p in (output_path, vars_path, fake_path, config_file):
            console.print(f"  [dim]•[/dim] [cyan]{p}[/cyan]")
        console.print(Rule())

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

full_cmd = command(
    name="full",
    help="Extract entities from input file and pseudonymize to Typst files with sensible defaults.",
    callback=full,
    arguments=[
        argument(name="file", arg_type=str, sort_key=0),
    ],
    options=[
        option(
            flags=["--output", "-o"],
            arg_type=str,
            default=None,
            help="Main Typst file path (default: <input>.typ)",
            sort_key=0,
        ),
        option(
            flags=["--language", "-l"],
            arg_type=str,
            default="en",
            help="Language for entity detection (e.g., 'en', 'da')",
            sort_key=1,
        ),
    ],
)
