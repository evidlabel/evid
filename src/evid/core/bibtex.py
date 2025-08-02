import os
from pathlib import Path
import logging
import subprocess
from typing import List, Tuple
from evid.core.label_setup import json_to_bib
# , parallel_csv_to_bib

logger = logging.getLogger(__name__)


def generate_bib_from_typ(
    typ_file: Path, exclude_note: bool = True
) -> Tuple[bool, str]:
    """Generate BibTeX from a single Typst file. Return (success, message)."""
    if not typ_file.exists():
        return False, f"Typst file '{typ_file}' does not exist."
    if not typ_file.stat().st_size:
        return False, f"Skipped empty Typst file '{typ_file}'."
    json_file = typ_file.parent / "label.json"
    bib_file = typ_file.parent / "label.bib"
    try:
        result = subprocess.run(
            # replace $HOME by actual home dir
            [
                "typst",
                "query",
                str(typ_file),
                '"<lab>"',
                "--package-path",
                os.path.expanduser("~/.cache/typst/packages"),
            ],
            stdout=open(json_file, "w"),
            stderr=subprocess.PIPE,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        error_msg = f"Error running typst query on {typ_file}: {str(e)}\nStderr: {e.stderr.decode('utf-8')}"
        return False, error_msg
    try:
        json_to_bib(json_file=json_file, bib_file=bib_file, exclude_note=exclude_note)
        logger.info(f"Generated BibTeX file: {bib_file}")
        return True, ""
    except Exception as e:
        return False, f"Failed to generate BibTeX for {typ_file}: {str(e)}"


def generate_bibtex(typ_files: List[Path], parallel: bool = False) -> None:
    """Generate BibTeX files from a list of label.typ files."""
    if not typ_files:
        print("No Typst files provided.")
        return

    success_count = 0
    errors = []
    for typ_file in typ_files:
        success, msg = generate_bib_from_typ(typ_file)
        if success:
            success_count += 1
        elif msg:
            logger.error(msg) if "exist" in msg else logger.warning(msg)
            errors.append(msg)

    print(f"Successfully generated {success_count} BibTeX files.")
    if errors:
        print(f"Encountered {len(errors)} issues:")
        for error in errors:
            print(f"  - {error}")

