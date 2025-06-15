import argparse
import sys
from pathlib import Path
import logging
from rich.logging import RichHandler
from evid import CONFIG
from evid.cli.dataset import list_datasets, select_dataset, create_dataset, track_dataset
from evid.cli.evidence import add_evidence
from evid.core.bibtex import generate_bibtex
from evid.gui.main import main as gui_main

# Set up logging with Rich handler
logging.basicConfig(handlers=[RichHandler()], level=logging.DEBUG, rich_tracebacks=True)
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="evid CLI for managing PDF documents")
    parser.add_argument(
        "-d", "--directory",
        default=CONFIG["default_dir"],
        help="Directory for storing datasets (default: ~/Documents/evid)",
    )
    subparsers = parser.add_subparsers(dest="command")

    # Add command
    parser_add = subparsers.add_parser("add", help="Add a PDF from a URL or local file")
    parser_add.add_argument("source", help="URL or path to the PDF file")
    parser_add.add_argument("-s", "--dataset", help="Target dataset name")  # Added short option
    parser_add.add_argument("-l", "--label", action="store_true", help="Open the labeler after adding the PDF")  # Added short option

    # Set submenu
    parser_set = subparsers.add_parser("set", help="Manage datasets")
    set_subparsers = parser_set.add_subparsers(dest="set_command")

    # Set create command
    parser_set_create = set_subparsers.add_parser("create", help="Create a new dataset")
    parser_set_create.add_argument("dataset", help="Name of the dataset to create")

    # Set track command
    parser_set_track = set_subparsers.add_parser("track", help="Track a dataset with Git")
    parser_set_track.add_argument("dataset", nargs="?", help="Name of the dataset to track")

    # List datasets command
    parser_list = subparsers.add_parser("list", help="List all available datasets")

    # BibTeX command
    parser_bibtex = subparsers.add_parser("bibtex", help="Generate BibTeX files from label.csv files")
    parser_bibtex.add_argument("csv_files", nargs="+", help="Paths to the label.csv files to process")
    parser_bibtex.add_argument("-p", "--parallel", action="store_true", help="Process CSV files in parallel")  # Added short option

    # GUI command
    parser_gui = subparsers.add_parser("gui", help="Launch the evid GUI")

    args = parser.parse_args()

    directory = Path(args.directory).expanduser()

    if args.command is None:
        gui_main(directory)
    elif args.command == "add":
        if args.dataset:
            dataset = args.dataset
            if not (directory / dataset).exists():
                sys.exit(f"Dataset '{dataset}' does not exist. Create it with 'evid set create'.")
        else:
            dataset = select_dataset(directory, "Select dataset for adding evidence")
        add_evidence(directory, dataset, args.source, args.label)
    elif args.command == "set":
        if args.set_command == "create":
            create_dataset(directory, args.dataset)
        elif args.set_command == "track":
            track_dataset(directory, args.dataset)
        else:
            parser_set.print_help()
    elif args.command == "list":
        list_datasets(directory)
    elif args.command == "bibtex":
        csv_files = [Path(csv_file) for csv_file in args.csv_files]
        for csv_file in csv_files:
            if not csv_file.exists():
                logger.error(f"CSV file '{csv_file}' does not exist.")
                print(f"Error: CSV file '{csv_file}' does not exist.")
                sys.exit(1)
        generate_bibtex(csv_files, parallel=args.parallel)
    elif args.command == "gui":
        gui_main(directory)

if __name__ == "__main__":
    main()
