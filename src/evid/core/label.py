"""Label creation functions."""
import logging
from rich.logging import RichHandler
from pathlib import Path
import subprocess
from evid.core.label_setup import textpdf_to_latex, csv_to_bib
from evid import CONFIG  # Import CONFIG to access the editor setting

# Configure Rich handler for colored logging
logging.basicConfig(handlers=[RichHandler(rich_tracebacks=True)], level=logging.INFO)
logger = logging.getLogger(__name__)

def create_label(file_path: Path, dataset: str, uuid: str) -> None:
    """Generate a LaTeX label file and open it in the configured editor."""
    label_file = file_path.parent / "label.tex"
    csv_file = file_path.parent / "label.csv"
    bib_file = file_path.parent / "label_table.bib"

    try:
        if not label_file.exists():
            textpdf_to_latex(file_path, label_file)
            
        print(CONFIG)
        subprocess.run([CONFIG["editor"], str(label_file)], check=True)

        if csv_file.exists():
            csv_to_bib(csv_file, bib_file, exclude_note=True)
            logger.info(f"Generated BibTeX file: {bib_file}")
        else:
            logger.warning(f"CSV file {csv_file} not found after labelling")
            print(f"No label.csv found in {file_path.parent}. BibTeX generation skipped.")
    except FileNotFoundError:
        logger.error(f"The configured editor '{CONFIG['editor']}' not found. Please ensure it is in your PATH.")
        print(f"The configured editor '{CONFIG['editor']}' is not installed or not in your PATH.")
    except subprocess.SubprocessError as e:
        logger.error(f"Error opening the configured editor: {str(e)}")
        print(f"Failed to open the configured editor: {str(e)}")
    except Exception as e:
        logger.error(f"Error during label workflow: {str(e)}")
        print(f"An unexpected error occurred: {str(e)}")
