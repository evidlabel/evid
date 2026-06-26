"""Main CLI entry point."""

import argparse
import sys
from pathlib import Path

from treeparse import argument, cli, command, group, option

from evid.cli.callbacks import (
    add_callback,
    bibtex_callback,
    create_callback,
    gather_callback,
    gui_callback,
    label_callback,
    list_datasets_callback,
    list_docs_callback,
    mcp_callback,
    quote_callback,
    rebut_callback,
    reindex_callback,
    search_meta_callback,
    search_text_callback,
    search_vec_callback,
    show_callback,
    tag_assign_callback,
    tag_list_callback,
    tag_remove_callback,
    tag_show_callback,
    track_callback,
    update_callback,
)
from evid.config import EvidConfig

_FORMAT_OPTION = option(
    flags=["-f", "--format"],
    arg_type=str,
    default="table",
    help="Output format: table, md, or json",
)

_DATASET_OPTION = option(
    flags=["-s", "--dataset"],
    arg_type=str,
    help="Dataset name or number",
)


def main():
    # Parse --db / --verbose manually before treeparse sees argv
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-d", "--db", default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args, unknown = parser.parse_known_args()

    from evid.logging_config import configure_logging

    configure_logging(verbose=args.verbose)

    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY_EXPLICIT = args.db is not None
    evid.cli.callbacks.DIRECTORY = (
        Path(args.db).expanduser()
        if args.db is not None
        else EvidConfig.load().data_dir
    )
    sys.argv = [sys.argv[0], *unknown]

    # With no subcommand, treeparse prints root help (it finds no `func`).
    # The GUI stays reachable via the explicit `evid gui` subcommand.
    app.run()


# ── root ───────────────────────────────────────────────────────────────────────

app = cli(
    name="evid",
    help="evid — evidence management CLI",
    max_width=120,
    show_types=True,
    show_defaults=True,
    line_connect=True,
    options=[
        option(
            flags=["-d", "--db"],
            arg_type=str,
            default=str(EvidConfig.load().data_dir),
            help="Data directory (default: ~/.local/share/evid)",
        ),
    ],
)

# ── gui ────────────────────────────────────────────────────────────────────────

app.commands.append(command(name="gui", help="Launch the GUI", callback=gui_callback))

# ── mcp ────────────────────────────────────────────────────────────────────────

app.commands.append(
    command(
        name="mcp",
        help="Run the MCP server (stdio) for one set — a warm query session for agents",
        callback=mcp_callback,
        arguments=[argument(name="dataset", arg_type=str)],
    )
)

# ── set ────────────────────────────────────────────────────────────────────────

set_group = group(name="set", help="Evidence set management")
app.subgroups.append(set_group)

set_group.commands.append(
    command(name="list", help="List all evidence sets", callback=list_datasets_callback)
)

set_group.commands.append(
    command(
        name="create",
        help="Create a new evidence set",
        callback=create_callback,
        options=[_DATASET_OPTION],
    )
)

set_group.commands.append(
    command(
        name="track",
        help="Git-track an evidence set",
        callback=track_callback,
        options=[_DATASET_OPTION],
    )
)

set_group.commands.append(
    command(
        name="reindex",
        help="Rebuild the vector index for every document in a set",
        callback=reindex_callback,
        options=[_DATASET_OPTION],
    )
)

set_group.commands.append(
    command(
        name="gather",
        help="Export gathered BibTeX / Markdown / JSON / Hayagriva from a set",
        callback=gather_callback,
        arguments=[argument(name="dataset", arg_type=str)],
        options=[
            option(
                flags=["-o", "--output"],
                arg_type=str,
                help="[required] Output file (.bib, .typ, .md, .json, .yaml, or .yml)",
            ),
            option(
                flags=["--no-regen"],
                flag=True,
                help="Use existing label.bib files instead of re-running typst query",
            ),
            option(
                flags=["--include-keys"],
                flag=True,
                help="Include label key names as sub-headings in .md output",
            ),
            option(
                flags=["--since"],
                arg_type=str,
                help="Only docs added on/after this date (YYYY-MM-DD, today, yesterday, or Nd)",
            ),
            option(
                flags=["--until"],
                arg_type=str,
                help="Only docs added on/before this date (defaults to today)",
            ),
        ],
    )
)

# ── doc ────────────────────────────────────────────────────────────────────────

doc_group = group(name="doc", help="Document management")
app.subgroups.append(doc_group)

doc_group.commands.append(
    command(
        name="add",
        help="Add a PDF or URL to a dataset",
        callback=add_callback,
        arguments=[argument(name="source", arg_type=str)],
        options=[
            _DATASET_OPTION,
            option(
                flags=["-l", "--label"], flag=True, help="Open labeler after adding"
            ),
            option(
                flags=["-a", "--autolabel"],
                flag=True,
                help="Auto-label paragraphs when opening labeler",
            ),
            option(
                flags=["--no-index"],
                flag=True,
                help="Skip building the vector index (faster, quieter; not searchable until re-indexed)",
            ),
        ],
    )
)

doc_group.commands.append(
    command(
        name="list",
        help="List documents in a dataset",
        callback=list_docs_callback,
        options=[_DATASET_OPTION, _FORMAT_OPTION],
    )
)

doc_group.commands.append(
    command(
        name="label",
        help="Open a document in the labeler",
        callback=label_callback,
        options=[
            _DATASET_OPTION,
            option(flags=["-u", "--uuid"], arg_type=str, help="Document UUID"),
            option(
                flags=["-f", "--filename"],
                arg_type=str,
                default="label.typ",
                help="Typst file to label",
            ),
        ],
    )
)

doc_group.commands.append(
    command(
        name="bibtex",
        help="Generate BibTeX from a document's label.typ",
        callback=bibtex_callback,
        options=[
            _DATASET_OPTION,
            option(flags=["-u", "--uuid"], arg_type=str, help="Document UUID"),
        ],
    )
)

doc_group.commands.append(
    command(
        name="quote",
        help="Machine-extract verbatim quotes from a doc (fuzzy) into machine.hayagriva",
        callback=quote_callback,
        options=[
            _DATASET_OPTION,
            option(flags=["-u", "--uuid"], arg_type=str, help="Document UUID"),
            option(
                flags=["--from"],
                dest="from_path",
                arg_type=str,
                help="quotes.json of candidate quotes (JSON, non-citable input)",
            ),
            option(
                flags=["--from-search"],
                dest="from_search",
                arg_type=str,
                help="Seed candidates from a vector search over the set (one of --from/--from-search)",
            ),
            option(
                flags=["-n", "--n"],
                arg_type=int,
                default=5,
                help="With --from-search: number of top chunks to use as candidates",
            ),
            option(
                flags=["--min-ratio"],
                arg_type=float,
                default=0.78,
                help="Fuzzy match threshold (0-1)",
            ),
            option(
                flags=["--refresh"],
                flag=True,
                help="Re-extract the cached text.txt before matching",
            ),
        ],
    )
)

doc_group.commands.append(
    command(
        name="rebut",
        help="Generate a rebuttal document",
        callback=rebut_callback,
        options=[
            _DATASET_OPTION,
            option(flags=["-u", "--uuid"], arg_type=str, help="Document UUID"),
        ],
    )
)

# ── tag ────────────────────────────────────────────────────────────────────────

tag_group = group(name="tag", help="Tag management")
app.subgroups.append(tag_group)

tag_group.commands.append(
    command(
        name="list",
        help="List all tags with doc and snippet counts",
        callback=tag_list_callback,
        options=[_DATASET_OPTION, _FORMAT_OPTION],
    )
)

tag_group.commands.append(
    command(
        name="show",
        help="Show all documents carrying a given tag",
        callback=tag_show_callback,
        arguments=[argument(name="tag", arg_type=str)],
        options=[_DATASET_OPTION, _FORMAT_OPTION],
    )
)

tag_group.commands.append(
    command(
        name="assign",
        help="Add a tag to a document by UUID",
        callback=tag_assign_callback,
        arguments=[
            argument(name="uuid", arg_type=str),
            argument(name="tag", arg_type=str),
        ],
    )
)

tag_group.commands.append(
    command(
        name="remove",
        help="Remove a tag from all documents that carry it",
        callback=tag_remove_callback,
        arguments=[argument(name="tag", arg_type=str)],
        options=[_DATASET_OPTION],
    )
)

# ── search ─────────────────────────────────────────────────────────────────────

search_group = group(name="search", help="Search documents")
app.subgroups.append(search_group)

search_group.commands.append(
    command(
        name="vec",
        help="Semantic vector search",
        callback=search_vec_callback,
        arguments=[argument(name="query", arg_type=str)],
        options=[
            _DATASET_OPTION,
            option(
                flags=["-n", "--n"],
                arg_type=int,
                default=10,
                help="Number of results",
            ),
            option(
                flags=["-t", "--tag"],
                arg_type=str,
                help="Filter results to documents with this tag",
            ),
            _FORMAT_OPTION,
        ],
    )
)

search_group.commands.append(
    command(
        name="meta",
        help="Regex search over document metadata (info.yml fields)",
        callback=search_meta_callback,
        arguments=[argument(name="pattern", arg_type=str)],
        options=[_DATASET_OPTION, _FORMAT_OPTION],
    )
)

search_group.commands.append(
    command(
        name="text",
        help="Full-text search over document bodies (fuzzy by default, or --regex)",
        callback=search_text_callback,
        arguments=[argument(name="query", arg_type=str)],
        options=[
            _DATASET_OPTION,
            option(
                flags=["-r", "--regex"],
                flag=True,
                help="Treat QUERY as a regex; return every match (else fuzzy)",
            ),
            option(
                flags=["-n", "--n"],
                arg_type=int,
                default=10,
                help="Max results",
            ),
            option(
                flags=["--min-ratio"],
                arg_type=float,
                default=0.7,
                help="Fuzzy match threshold 0-1 (fuzzy mode only)",
            ),
            option(
                flags=["--context"],
                arg_type=int,
                default=160,
                help="Context chars around each regex match",
            ),
            option(
                flags=["--refresh"],
                flag=True,
                help="Re-extract cached text.txt before searching",
            ),
            _FORMAT_OPTION,
        ],
    )
)

# ── config ─────────────────────────────────────────────────────────────────────

config_group = group(name="config", help="Configuration")
app.subgroups.append(config_group)

config_group.commands.append(
    command(
        name="show",
        help="Show current configuration",
        callback=show_callback,
    )
)

config_group.commands.append(
    command(
        name="update",
        help="Initialize or update .evidrc with defaults",
        callback=update_callback,
    )
)

if __name__ == "__main__":
    main()
