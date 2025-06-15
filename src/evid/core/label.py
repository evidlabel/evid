"""Label creation functions."""
import logging
from rich.logging import RichHandler
from pathlib import Path
import subprocess
from evid.core.label_setup import textpdf_to_latex, csv_to_bib

# Configure Rich handler for colored logging
logging.basicConfig(handlers=[RichHandler(rich_tracebacks=True)], level=logging.INFO )
logger = logging.getLogger(__name__)

def create_label(file_path: Path, dataset: str, uuid: str) -> None:
    """Generate a LaTeX label file and open it in VS Code."""
    label_file = file_path.parent / "label.tex"
    csv_file = file_path.parent / "label.csv"
    bib_file = file_path.parent / "label_table.bib"

    try:
        if not label_file.exists():
            textpdf_to_latex(file_path, label_file)

        subprocess.run(["code", "--wait", str(label_file)], check=True)

        if csv_file.exists():
            csv_to_bib(csv_file, bib_file, exclude_note=True)
            logger.info(f"Generated BibTeX file: {bib_file}")
        else:
            logger.warning(f"CSV file {csv_file} not found after labelling")
            print(f"No label.csv found in {file_path.parent}. BibTeX generation skipped.")
    except FileNotFoundError:
        logger.error("VS Code not found. Please ensure 'code' is in your PATH.")
        print("Visual Studio Code is not installed or not in your PATH.")
    except subprocess.SubprocessError as e:
        logger.error(f"Error opening VS Code: {str(e)}")
        print(f"Failed to open VS Code: {str(e)}")
    except Exception as e:
        logger.error(f"Error during label workflow: {str(e)}")
        print(f"An unexpected error occurred: {str(e)}")
