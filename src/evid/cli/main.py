"""Main CLI entry point."""
import sys
from treeparse import cli, group, command, argument, option
from evid.cli.callbacks import (
    set_directory,
    create_callback,
    track_callback,
    list_datasets_callback,
    add_callback,
    bibtex_callback,
    label_callback,
    rebut_callback,
    list_docs_callback,
    gui_callback,
    update_callback,
    show_callback,
)


def main():
    set_directory()
    if len(sys.argv) == 1:
        gui_callback()
    else:
        app.run()


# Build the CLI structure
app = cli(
    name="evid",
    help="evid CLI for managing PDF documents",
    max_width=120,
    show_types=True,
    show_defaults=True,
    line_connect=True,
)

set_group = group(name="set", help="Manage datasets")
app.subgroups.append(set_group)

set_group.commands.append(
    command(
        name="create",
        help="Create a new dataset",
        callback=create_callback,
        options=[
            option(
                flags=["-s", "--dataset"], arg_type=str, help="Dataset name or number"
            ),
        ],
    )
)

set_group.commands.append(
    command(
        name="track",
        help="Track a dataset with Git",
        callback=track_callback,
        options=[
            option(
                flags=["-s", "--dataset"], arg_type=str, help="Dataset name or number"
            ),
        ],
    )
)

set_group.commands.append(
    command(
        name="list",
        help="List all available datasets",
        callback=list_datasets_callback,
    )
)

set_group.commands.append(
    command(
        name="add",
        help="Add a PDF from a URL or local file to a dataset",
        callback=add_callback,
        arguments=[
            argument(name="source", arg_type=str),
        ],
        options=[
            option(
                flags=["-l", "--label"],
                is_flag=True,
                arg_type=bool,
                help="Open the labeler after adding the PDF",
            ),
            option(
                flags=["-a", "--autolabel"],
                is_flag=True,
                arg_type=bool,
                help="Auto-label paragraphs when labelling",
            ),
            option(
                flags=["-s", "--dataset"], arg_type=str, help="Dataset name or number"
            ),
        ],
    )
)

doc_group = group(
    name="doc",
    help="Manage documents",
    options=[
        option(flags=["-s", "--dataset"], arg_type=str, help="Dataset name"),
        option(flags=["-u", "--uuid"], arg_type=str, help="UUID of the document"),
    ],
)
app.subgroups.append(doc_group)

doc_group.commands.append(
    command(
        name="bibtex",
        help="Generate BibTeX files from label.typ files",
        callback=bibtex_callback,
    )
)

doc_group.commands.append(
    command(
        name="label",
        help="Label a document in a dataset",
        callback=label_callback,
        options=[
            option(
                flags=["-f", "--filename"],
                arg_type=str,
                default="label.typ",
                help="Typst file to label, defaults to label.typ",
            ),
        ],
    )
)

doc_group.commands.append(
    command(
        name="rebut",
        help="Generate rebuttal for a document in a dataset",
        callback=rebut_callback,
    )
)

doc_group.commands.append(
    command(
        name="list",
        help="List documents in the dataset",
        callback=list_docs_callback,
    )
)

app.commands.append(
    command(
        name="gui",
        help="Launch the evid GUI",
        callback=gui_callback,
    )
)

config_group = group(name="config", help="Deal with configuration of evid")
app.subgroups.append(config_group)

config_group.commands.append(
    command(
        name="update",
        help="Initialize or update .evidrc with default settings",
        callback=update_callback,
    )
)

config_group.commands.append(
    command(
        name="show",
        help="Show the current config settings and where they are defined",
        callback=show_callback,
    )
)

if __name__ == "__main__":
    main()
