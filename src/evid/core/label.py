"""Label creation functions."""

import logging
import subprocess
from pathlib import Path

from rich.logging import RichHandler

from evid.config import EvidConfig
from evid.core.bibtex import generate_bib_from_typ
from evid.core.typst_generation import text_to_typst, textpdf_to_typst

# Configure Rich handler for colored logging
logging.basicConfig(handlers=[RichHandler(rich_tracebacks=True)], level=logging.INFO)
logger = logging.getLogger(__name__)


def create_label(
    file_path: Path,
    dataset: str,
    uuid: str,
    autolabel: bool = False,
    filename: str = "label.typ",
) -> None:
    """Generate a label file and open it in the configured editor."""
    label_file = file_path.parent / filename
    try:
        if not label_file.exists():
            # Ensure static directory exists for frontend (used by fitz)
            Path("static").mkdir(exist_ok=True)
            if file_path.suffix.lower() == ".pdf":
                textpdf_to_typst(file_path, label_file, autolabel)
            elif file_path.suffix.lower() == ".txt":
                text_to_typst(file_path, label_file, autolabel)
            else:
                logger.warning(f"Unsupported file type: {file_path.suffix}")
                return

        # Open the editor
        logger.info(
            f"Opening editor '{EvidConfig.load().editor}' with file: {label_file}"
        )
        try:
            subprocess.run([EvidConfig.load().editor, str(label_file)], check=True)
        except FileNotFoundError:
            logger.error(
                f"The configured editor '{EvidConfig.load().editor}' not found. Please ensure it is in your PATH."
            )
            return  # Exit early if editor fails to open
        except subprocess.SubprocessError as e:
            logger.exception(f"Error opening the configured editor: {e!s}")
            return  # Exit early if editor fails

        success, msg = generate_bib_from_typ(label_file)
        if not success:
            logger.error(f"Error during label workflow: {msg}")
            return

        # csv had no function other than to generate the bib file, fully deprecate csv use
    except Exception as e:
        logger.exception(f"Error during label workflow: {e!s}")
