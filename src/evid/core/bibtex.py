from pathlib import Path
import logging
from typing import List
from evid.core.label_setup import csv_to_bib, parallel_csv_to_bib

logger = logging.getLogger(__name__)

def generate_bibtex(csv_files: List[Path], parallel: bool = False) -> None:
    """Generate BibTeX files from a list of label.csv files."""
    if not csv_files:
        print("No CSV files provided.")
        return

    if parallel:
        success_count, errors = parallel_csv_to_bib(csv_files, exclude_note=True)
    else:
        success_count = 0
        errors = []
        for csv_file in csv_files:
            if not csv_file.exists():
                error_msg = f"CSV file '{csv_file}' does not exist."
                logger.error(error_msg)
                errors.append(error_msg)
                continue
            if not csv_file.stat().st_size:
                error_msg = f"Skipped empty CSV file '{csv_file}'."
                logger.warning(error_msg)
                errors.append(error_msg)
                continue
            bib_file = csv_file.parent / "label_table.bib"
            try:
                csv_to_bib(csv_file, bib_file, exclude_note=True)
                logger.info(f"Generated BibTeX file: {bib_file}")
                success_count += 1
            except Exception as e:
                error_msg = f"Failed to generate BibTeX for {csv_file}: {str(e)}"
                logger.error(error_msg)
                errors.append(error_msg)

    print(f"Successfully generated {success_count} BibTeX files.")
    if errors:
        print(f"Encountered {len(errors)} issues:")
        for error in errors:
            print(f"  - {error}")

