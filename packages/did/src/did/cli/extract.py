"""Extract command for CLI."""

import sys
from pathlib import Path

from rich.rule import Rule
from rich.syntax import Syntax
from ruamel import yaml
from treeparse import argument, command, option

from ..core.anonymizer import Anonymizer
from ..utils.console import console, print_counts
from ..utils.file_utils import extract_text


def extract(files, config, language):
    """Extract entities from text files and generate YAML config."""
    if not files:
        console.print("[red]Error:[/red] At least one input file is required.")
        sys.exit(1)
    anonymizer = Anonymizer(language=language)
    try:
        console.print(Rule("extract"))
        console.print("Reading input text files...")
        texts = []
        for input_file in files:
            file_path = Path(input_file)
            text = extract_text(file_path)
            texts.append(text)

        with console.status(f"[bold green]Detecting entities in {language}...[/bold green]"):
            anonymizer.detect_entities(texts)

        console.print("[bold]Detected entities:[/bold]")
        print_counts(anonymizer.counts, "found")

        yaml_str = anonymizer.generate_yaml()
        console.print("Writing YAML config...")
        with open(config, "w") as f:
            f.write(yaml_str)

        console.print(f"Config written to [cyan]{config}[/cyan]")
        console.print(Syntax(yaml_str, "yaml"))
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

extract_cmd = command(
    name="extract",
    help="Extract entities from input text files and generate a YAML configuration file.",
    callback=extract,
    arguments=[
        argument(name="files", arg_type=str, nargs="*", sort_key=0),
    ],
    options=[
        option(
            flags=["--config", "-c"],
            arg_type=str,
            default="__temp.yaml",
            help="Output YAML config file",
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
