"""Pseudo commands for CLI."""

import sys
from pathlib import Path

from rich.rule import Rule
from rich.syntax import Syntax
from ruamel import yaml
from treeparse import argument, command, group, option

from ..core.anonymizer import Anonymizer
from ..utils.console import console, print_counts
from ..utils.file_utils import anonymize_file, export_to_typst


def plain(file, config, output):
    """Pseudonymize to plain output file."""
    if config is None:
        console.print("[red]Error:[/red] --config is required")
        sys.exit(1)
    anonymizer = Anonymizer()
    input_path = Path(file)
    if output is None:
        output = str(input_path.parent / (input_path.stem + "_anon" + input_path.suffix))
    output_path = Path(output)
    try:
        console.print(Rule("pseudo plain"))
        console.print("Loading config...")
        yaml_obj = yaml.YAML()
        with open(config) as f:
            config_data = yaml_obj.load(f) or {}
        anonymizer.load_replacements(config_data)

        console.print(f"Processing [cyan]{file}[/cyan]...")
        counts = anonymize_file(input_path, anonymizer, output_path)

        console.print("[bold]Replacement counts:[/bold]")
        print_counts(counts, "replaced")

        with open(output_path, encoding="utf-8") as f:
            content = f.read()
        lang = "markdown" if output_path.suffix == ".md" else "text"
        console.print(Syntax(content, lang, theme="monokai"))
        console.print(Rule())

    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] File not found — {e}")
        sys.exit(1)
    except yaml.YAMLError as e:
        console.print(f"[red]Error:[/red] Invalid YAML — {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


def typst(file, config, output):
    """Pseudonymize to Typst files."""
    if config is None:
        console.print("[red]Error:[/red] --config is required")
        sys.exit(1)
    anonymizer = Anonymizer()
    input_path = Path(file)
    if output is None:
        output = str(input_path.with_suffix(".typ"))
    main_path = Path(output)
    if main_path.suffix != ".typ":
        console.print("[red]Error:[/red] Output file must end with .typ")
        sys.exit(1)
    stem = main_path.stem
    parent = main_path.parent
    vars_path = parent / f"{stem}_vars.typ"
    fake_path = parent / f"{stem}_fakevars.typ"
    try:
        console.print(Rule("pseudo typst"))
        console.print("Loading config...")
        yaml_obj = yaml.YAML()
        with open(config) as f:
            config_data = yaml_obj.load(f) or {}
        anonymizer.load_replacements(config_data)

        console.print(f"Processing [cyan]{file}[/cyan]...")
        export_to_typst(input_path, anonymizer, main_path)

        console.print("[bold]Replacement counts:[/bold]")
        print_counts(anonymizer.counts, "replaced")

        console.print(f"\nTypst files written to [cyan]{parent}[/cyan]")
        for p in (main_path, vars_path, fake_path):
            console.print(f"  [dim]•[/dim] [cyan]{p}[/cyan]")

        for label, path in [("vars", vars_path), ("fakevars", fake_path), ("main", main_path)]:
            console.print(f"\n[bold]Preview of {path.name}:[/bold]")
            with open(path, encoding="utf-8") as f:
                content = f.read()
            console.print(Syntax(content, "rust"))

        console.print(Rule())

    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] File not found — {e}")
        sys.exit(1)
    except yaml.YAMLError as e:
        console.print(f"[red]Error:[/red] Invalid YAML — {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


pseudo_group = group(
    name="pseudo", help="Pseudonymize input text file using a YAML configuration."
)

plain_cmd = command(
    name="plain",
    help="Pseudonymize to plain output file.",
    callback=plain,
    arguments=[
        argument(name="file", arg_type=str, sort_key=0),
    ],
    options=[
        option(flags=["--config", "-c"], arg_type=str, help="Config file", sort_key=0),
        option(flags=["--output", "-o"], arg_type=str, default=None, help="Output file path", sort_key=1),
    ],
)
pseudo_group.commands.append(plain_cmd)

typst_cmd = command(
    name="typst",
    help="Pseudonymize to Typst files, creating <input_stem>.typ, <input_stem>_vars.typ, <input_stem>_fakevars.typ.",
    callback=typst,
    arguments=[
        argument(name="file", arg_type=str, sort_key=0),
    ],
    options=[
        option(flags=["--config", "-c"], arg_type=str, help="Config file", sort_key=0),
        option(flags=["--output", "-o"], arg_type=str, default=None, help="Main Typst file path (default: <input>.typ)", sort_key=1),
    ],
)
pseudo_group.commands.append(typst_cmd)
