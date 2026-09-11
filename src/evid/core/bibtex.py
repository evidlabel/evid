"""Handle BibTeX generation."""

import logging
import os
import subprocess
from pathlib import Path

from evid.core.bibtex_utils import json_to_bib

logger = logging.getLogger(__name__)


def generate_bib_from_typ(
    typ_file: Path, exclude_note: bool = True
) -> tuple[bool, str]:
    """Generate BibTeX from a single Typst file. Return (success, message)."""
    if not typ_file.exists():
        return False, f"Typst file '{typ_file}' does not exist."
    if not typ_file.stat().st_size:
        return False, f"Skipped empty Typst file '{typ_file}'."
    json_file = typ_file.parent / "label.json"
    bib_file = typ_file.parent / "label.bib"
    try:
        with open(json_file, "w", encoding="utf-8") as json_out:
            result = subprocess.run(
                [
                    "typst",
                    "query",
                    str(typ_file),
                    "<lab>",
                    "--package-path",
                    os.path.expanduser("~/.cache/typst"),
                ],
                stdout=json_out,
                stderr=subprocess.PIPE,
                check=False,
            )

        # print the command in pastable form for debugging in shell
        cmd_for_shell = " ".join(
            [f'"{arg}"' if " " in arg else arg for arg in result.args]
        )
        logger.debug("Running command: %s > %s", cmd_for_shell, json_file)
        stderr_output = result.stderr.decode("utf-8")
        if stderr_output:
            logger.debug("Stderr: %s", stderr_output)
        if result.returncode != 0:
            if "text is not locatable" in stderr_output:
                logger.warning(
                    "Ignoring non-fatal Typst query error: %s", stderr_output
                )
            else:
                error_msg = f"Error running typst query on {typ_file}: Command returned non-zero exit status {result.returncode}.\nStderr: {stderr_output}"
                return False, error_msg
        try:
            json_to_bib(json_file, bib_file, exclude_note=exclude_note)
            logger.debug("Generated BibTeX file: %s", bib_file)
            return True, ""
        except ValueError as e:
            # Fresh ingest has no #lab tags yet — typst query writes [].
            if "empty" in str(e).lower():
                logger.debug("No <lab> labels in %s", typ_file)
                return True, ""
            return False, f"Failed to generate BibTeX for {typ_file}: {e!s}"
        except Exception as e:
            return False, f"Failed to generate BibTeX for {typ_file}: {e!s}"
    except Exception as e:
        return False, f"Unexpected error during Typst query: {e!s}"


def generate_bibtex(typ_files: list[Path]) -> None:
    """Generate BibTeX files from a list of label.typ files."""
    if not typ_files:
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

    if errors:
        for _error in errors:
            pass
