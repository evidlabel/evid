from pathlib import Path
import logging
from evid.core.label_setup import csv_to_bib

logger = logging.getLogger(__name__)

def generate_bibtex(csv_file: Path) -> None:
    """Generate a BibTeX file from a single label.csv file."""
    bib_file = csv_file.parent / "label_table.bib"
    try:
        csv_to_bib(csv_file, bib_file, exclude_note=True)
        logger.info(f"Generated BibTeX file: {bib_file}")
        print(f"Successfully generated BibTeX file: {bib_file}")
    except Exception as e:
        logger.error(f"Failed to generate BibTeX for {csv_file}: {str(e)}")
        print(f"Error generating BibTeX for {csv_file}: {str(e)}")
