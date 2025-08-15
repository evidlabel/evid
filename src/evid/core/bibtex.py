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
                "<lab>",
                "--package-path",
                os.path.expanduser("~/.cache/typst"),
            ],
            stdout=open(json_file, "w"),
            stderr=subprocess.PIPE,
            check=False,
        )

        # print the command in pastable form for debugging in shell
        cmd_for_shell = " ".join(
            [f'"{arg}"' if " " in arg else arg for arg in result.args]
        )
        logger.info(f"Running command: {cmd_for_shell} > {json_file}")
        stderr_output = result.stderr.decode("utf-8")
        if stderr_output:
            logger.info(f"Stderr: {stderr_output}")
        if result.returncode != 0:
            if "text is not locatable" in stderr_output:
                logger.warning(f"Ignoring non-fatal Typst query error: {stderr_output}")
            else:
                error_msg = f"Error running typst query on {typ_file}: Command returned non-zero exit status {result.returncode}.\nStderr: {stderr_output}"
                return False, error_msg
        try:
            json_to_bib(json_file, bib_file, exclude_note=exclude_note)
            logger.info(f"Generated BibTeX file: {bib_file}")
            return True, ""
        except Exception as e:
            return False, f"Failed to generate BibTeX for {typ_file}: {str(e)}"
    except Exception as e:
        return False, f"Unexpected error during Typst query: {str(e)}"


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
