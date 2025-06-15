"""Extract PDF metadata functions."""
import logging
from rich.logging import RichHandler
from pathlib import Path
import pypdf
from evid.utils.text import normalize_text
from io import BytesIO
# Configure Rich handler for colored logging
logging.basicConfig(handlers=[RichHandler(rich_tracebacks=True)], level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_pdf_metadata(
    pdf_source: Path | BytesIO, file_name: str
) -> tuple[str, str, str]:
    """Extract title, authors, and date from PDF as plain strings, preserving Danish characters."""
    try:
        if isinstance(pdf_source, Path):
            with open(pdf_source, "rb") as f:
                reader = pypdf.PdfReader(f)
                meta = reader.metadata
        else:
            pdf_source.seek(0)
            reader = pypdf.PdfReader(pdf_source)
            meta = reader.metadata

        title = normalize_text(meta.get("/Title", Path(file_name).stem))
        authors = normalize_text(meta.get("/Author", ""))
        date = normalize_text(meta.get("/CreationDate") or meta.get("/ModDate", ""))
        if date and date.startswith("D:"):
            date = f"{date[2:6]}-{date[6:8]}-{date[8:10]}"  # YYYY-MM-DD
        else:
            date = ""
    except Exception:
        title = normalize_text(Path(file_name).stem)
        authors = ""
        date = ""
        logger.warning(f"Failed to extract metadata from {file_name}, using defaults.")
    return title, authors, date
