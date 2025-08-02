from pathlib import Path
import logging
import subprocess
from typing import List
from evid.core.label_setup import json_to_bib
# , parallel_csv_to_bib

logger = logging.getLogger(__name__)


def generate_bibtex(typ_files: List[Path], parallel: bool = False) -> None:
    """Generate BibTeX files from a list of label.typ files."""
    if not typ_files:
        print("No Typst files provided.")
        return

    success_count = 0
    errors = []
    for typ_file in typ_files:
        if not typ_file.exists():
            error_msg = f"Typst file '{typ_file}' does not exist."
            logger.error(error_msg)
            errors.append(error_msg)
            continue
        if not typ_file.stat().st_size:
            error_msg = f"Skipped empty Typst file '{typ_file}'."
            logger.warning(error_msg)
            errors.append(error_msg)
            continue
        bib_file = typ_file.parent / "label.bib"

        json_file = typ_file.parent / "label.json"
        if not json_file.exists():
            logger.warning(f"JSON file {json_file} not found, running typst query.")
            # Run typst query to generate JSON file
            try:
                subprocess.run(
                    ["typst", "query", str(typ_file), "<lab>"],
                    stdout=open(json_file, "w"),
                    check=True,
                )
            except subprocess.SubprocessError as e:
                logger.error(f"Error running typst query: {str(e)}")
                print(f"Failed to run typst query: {str(e)}")
                continue

        # subprocess.run(
        #     ["typst", "query", str(typ_file), "<lab>"],
        #     stdout=open(json_file, "w"),
        #     check=True,
        # )

        try:
            json_to_bib(json_file=json_file, bib_file=bib_file, exclude_note=True)
            logger.info(f"Generated BibTeX file: {bib_file}")
            success_count += 1
        except Exception as e:
            error_msg = f"Failed to generate BibTeX for {typ_file}: {str(e)}"
            logger.error(error_msg)
            errors.append(error_msg)

    print(f"Successfully generated {success_count} BibTeX files.")
    if errors:
        print(f"Encountered {len(errors)} issues:")
        for error in errors:
            print(f"  - {error}")
