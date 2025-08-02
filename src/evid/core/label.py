"""Label creation functions."""

import logging
from rich.logging import RichHandler
from pathlib import Path
import subprocess
from evid.core.label_setup import textpdf_to_typst, text_to_typst, json_to_bib
from evid import CONFIG  # Import CONFIG to access the editor setting
import json
import pandas as pd

# Configure Rich handler for colored logging
logging.basicConfig(handlers=[RichHandler(rich_tracebacks=True)], level=logging.INFO)
logger = logging.getLogger(__name__)


def create_label(file_path: Path, dataset: str, uuid: str) -> None:
    """Generate a label file and open it in the configured editor."""
    label_file = file_path.parent / "label.typ"
    try:
        if not label_file.exists():
            if file_path.suffix.lower() == ".pdf":
                textpdf_to_typst(file_path, label_file)
            elif file_path.suffix.lower() == ".txt":
                text_to_typst(file_path, label_file)
            else:
                logger.warning(f"Unsupported file type: {file_path.suffix}")
                return

        # Open the editor
        try:
            subprocess.run([CONFIG["editor"], str(label_file)], check=True)
        except FileNotFoundError:
            logger.error(
                f"The configured editor '{CONFIG['editor']}' not found. Please ensure it is in your PATH."
            )
            print(
                f"The configured editor '{CONFIG['editor']}' is not installed or not in your PATH."
            )
            return  # Exit early if editor fails to open
        except subprocess.SubprocessError as e:
            logger.error(f"Error opening the configured editor: {str(e)}")
            print(f"Failed to open the configured editor: {str(e)}")
            return  # Exit early if editor fails

        json_file = file_path.parent / "label.json"

        # Pipe the results from typst query to a JSON file
        try:
            subprocess.run(
                ["typst", "query", str(label_file), "<lab>"],
                stdout=open(json_file, "w"),
                check=True,
            )
        except subprocess.SubprocessError as e:
            logger.error(f"Error running typst query: {str(e)}")
            print(f"Failed to run typst query: {str(e)}")
            return  # Exit early if query fails

        bib_file = file_path.parent / "label.bib"
        if json_file.exists():
            json_to_bib(json_file, bib_file, exclude_note=True)
            logger.info(f"Generated BibTeX file: {bib_file}")

            # csv had no function other than to generate the bib file, fully deprecate csv use
        else:
            logger.warning(f"JSON file {json_file} not found after labelling")
            print(
                f"No label.json found in {file_path.parent}. BibTeX generation skipped."
            )
    except Exception as e:
        logger.error(f"Error during label workflow: {str(e)}")
        print(f"An unexpected error occurred: {str(e)}")
