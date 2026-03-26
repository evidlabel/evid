"""Shared Rich console and output helpers."""

from rich.console import Console
from rich.table import Table

console = Console()


def print_counts(counts: dict, verb: str) -> None:
    """Render entity counts as a rich table. verb is 'found' or 'replaced'."""
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Entity type", style="dim")
    table.add_column(verb.capitalize(), justify="right")
    keys = [
        ("PERSON",         f"person_{verb}"),
        ("EMAIL_ADDRESS",  f"email_address_{verb}"),
        ("LOCATION",       f"location_{verb}"),
        ("PHONE_NUMBER",   f"phone_number_{verb}"),
        ("DATE_NUMBER",    f"date_number_{verb}"),
        ("ID_NUMBER",      f"id_number_{verb}"),
        ("CODE_NUMBER",    f"code_number_{verb}"),
        ("GENERAL_NUMBER", f"general_number_{verb}"),
    ]
    for label, key in keys:
        n = counts.get(key, 0)
        style = "green" if n > 0 else "dim"
        table.add_row(label, f"[{style}]{n}[/{style}]")
    console.print(table)
