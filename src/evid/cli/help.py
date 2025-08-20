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
from rich.console import Console
from rich.table import Table
from rich.text import Text


from evid.cli.evidence import add_evidence, label_evidence, select_evidence
from evid.core.bibtex import generate_bibtex
from evid.gui.main import main as gui_main
from evid.core.models import ConfigModel  # For rc command
import yaml

# Configure rich-click for better formatting
click.rich_click.USE_RICH_MARKUP = True
click.rich_click.SHOW_ARGUMENTS = True
click.rich_click.GROUP_ARGUMENTS_OPTIONS = True
console = Console()


# Custom top-level help with table for alignment
def print_full_help(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    rows = []
    for cmd_name, cmd in sorted(ctx.command.commands.items()):
        # Collect arguments for the command
        args = [
            f"[orange1][{param.name.upper()}][/orange1]"
            for param in cmd.params
            if isinstance(param, click.Argument)
        ]
        arg_str = " ".join(args) if args else ""
        rows.append(
            (
                f"  [bold green]{cmd_name}[/bold green] {arg_str}",
                f"[bold]{cmd.help}[/bold]",
            )
        )
        # Print options for standalone commands or groups without subcommands
        for param in cmd.params:
            if isinstance(param, click.Option):
                opts = ", ".join(param.opts)
                rows.append(
                    (
                        f"    [bold yellow]{opts}[/bold yellow]",
                        f"  [italic yellow]{param.help or ""}[/italic yellow]",
                    )
                )
        # Check if the command is a group and has subcommands
        if isinstance(cmd, click.Group) and cmd.commands:
            for sub_name, sub_cmd in sorted(cmd.commands.items()):
                # Collect arguments for the subcommand
                sub_args = [
                    f"[orange1][{param.name.upper()}][/orange1]"
                    for param in sub_cmd.params
                    if isinstance(param, click.Argument)
                ]
                sub_arg_str = " ".join(sub_args) if sub_args else ""
                rows.append(
                    (
                        f"    [cyan]{sub_name}[/cyan] {sub_arg_str}",
                        f"{sub_cmd.help}",
                    )
                )
                # Print options for subcommand
                for param in sub_cmd.params:
                    if isinstance(param, click.Option):
                        opts = ", ".join(param.opts)
                        rows.append(
                            (
                                f"      [bold yellow]{opts}[/bold yellow]",
                                f"  [italic yellow]{param.help or ""}[/italic yellow]",
                            )
                        )
                # Check if the subcommand is a group and has sub-subcommands
                if isinstance(sub_cmd, click.Group) and sub_cmd.commands:
                    for sub_sub_name, sub_sub_cmd in sorted(sub_cmd.commands.items()):
                        # Collect arguments for the sub-subcommand
                        sub_sub_args = [
                            f"[orange1][{param.name.upper()}][/orange1]"
                            for param in sub_sub_cmd.params
                            if isinstance(param, click.Argument)
                        ]
                        sub_sub_arg_str = " ".join(sub_sub_args) if sub_sub_args else ""
                        rows.append(
                            (
                                f"      [cyan]{sub_sub_name}[/cyan] {sub_sub_arg_str}",
                                f"{sub_sub_cmd.help}",
                            )
                        )
                        # Print options for sub-subcommand
                        for param in sub_sub_cmd.params:
                            if isinstance(param, click.Option):
                                opts = ", ".join(param.opts)
                                rows.append(
                                    (
                                        f"        [bold yellow]{opts}[/bold yellow]",
                                        f"  [italic yellow]{param.help or ""}[/italic yellow]",
                                    )
                                )
    # Calculate max rendered length for command column
    max_length = max(console.measure(Text.from_markup(row[0])).maximum for row in rows)

    width = 3 * max_length

    # Create a borderless table for alignment
    table = Table(show_header=False, box=None, padding=0, expand=False, width=width)
    table.add_column("Command", width=max_length + 2, no_wrap=False)
    table.add_column("Description")
    for row in rows:
        table.add_row(row[0], row[1])

    console.print(
        f"\n[bold]Usage:[/bold] {ctx.command_path} [OPTIONS] COMMAND [ARGS]...\n"
    )
    # console.print("[bold]Options:[/bold]")
    # console.print(" --help Show this message and exit.\n")
    console.print(
        f"[bold]Description:[/bold] {ctx.command.help}" + "\n"
        if not ctx.command.help.endswith("\n")
        else "",
        no_wrap=False,
        width=width,
    )
    # console.print("[bold]Commands:[/bold]")
    # Collect rows for the table

    console.print(table)
    # console.print()
    ctx.exit()
