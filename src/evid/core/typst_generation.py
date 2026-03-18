"""Typst generation functions for evid."""

import logging
from pathlib import Path

import yaml

from evid.core.models import InfoModel
from evid.core.text_cleaning import clean_text_for_typst

logger = logging.getLogger(__name__)


def web_to_pdf(url: str, output_dir: Path) -> tuple:
    """Fetch a web page, render it as a timestamped Typst document, compile to PDF.

    Returns (pdf_path, page_title).
    """
    import subprocess

    import requests
    from bs4 import BeautifulSoup

    from evid.utils.text import normalize_text

    response = requests.get(url, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    title_tag = soup.find("title")
    page_title = (
        normalize_text(title_tag.get_text())
        if title_tag
        else (url.rsplit("/", maxsplit=1)[-1] or "document")
    )

    for elem in soup(["script", "style", "head", "nav", "footer"]):
        elem.decompose()
    text = clean_text_for_typst(
        normalize_text(soup.get_text(separator="\n", strip=True))
    )
    # Escape bare # so web hashtags/anchors don't trigger Typst function calls
    text = text.replace("#", "\\#")

    safe_title = page_title.replace("\\", "\\\\").replace('"', '\\"')
    safe_url = url.replace("\\", "\\\\").replace('"', '\\"')

    typst_content = f"""#set page(margin: 2cm)
#set document(date: datetime.today())

= {safe_title}

*Archived: #datetime.today().display()*

*Source: {safe_url}*

{text}
"""

    stem = Path(url.rsplit("/", maxsplit=1)[-1] or "document").stem or "document"
    typ_path = output_dir / f"{stem}.typ"
    pdf_path = output_dir / f"{stem}.pdf"
    typ_path.write_text(typst_content, encoding="utf-8")

    result = subprocess.run(
        ["typst", "compile", str(typ_path), str(pdf_path)],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"typst compile failed: {result.stderr.decode()}")

    return pdf_path, page_title


def textpdf_to_typst(
    pdfname: Path, outputfile: Path = None, autolabel: bool = False
) -> str:
    """Generate Typst content from PDF file."""
    import fitz

    info_file = pdfname.with_name("info.yml")
    if info_file.exists():
        with info_file.open() as f:
            info = yaml.safe_load(f)
            # Validate with Pydantic
            try:
                validated_info = InfoModel(**info)
                info = validated_info.model_dump()
            except ValueError as e:
                logger.warning(f"Validation error for {info_file}: {e}")
                date, name = "DATE", "NAME"
            else:
                date = info.get("dates", "DATE")
                if isinstance(date, list):
                    date = date[0] if date else "DATE"
                # Ensure date is a string
                date = str(date)
                name = info.get("label", "label")
    else:
        date, name = "DATE", "NAME"

    # Escape for Typst string literals
    name_escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    date_escaped = date.replace("\\", "\\\\").replace('"', '\\"')
    title_display = name.replace("_", " ")

    pdf = fitz.open(pdfname)
    body = ""
    para_num = 1
    for i, page in enumerate(pdf):
        # Disable TEXT_PRESERVE_LIGATURES to dissolve ligatures
        flags = fitz.TEXT_PRESERVE_LIGATURES
        text = clean_text_for_typst(page.get_text(flags=flags))
        page_body = f"#mset(values: (opage: {i + 1}))\n== Page {i + 1}\n"
        if autolabel:
            paragraphs = [p for p in text.split("\n\n") if p.strip()]
            for para in paragraphs:
                escaped_para = para.replace("\\", "\\\\").replace('"', '\\"')
                labelled = f'#lab("lab{para_num}", "{escaped_para}", "")'
                commented = "\n".join(f"// {line}" for line in para.split("\n"))
                page_body += labelled + "\n\n" + commented + "\n\n"
                para_num += 1
        else:
            page_body += text + "\n\n"
        body += page_body
    pdf.close()

    typst_content = f"""#import "@preview/labtyp:0.1.0": lablist, lab, mset

#mset(values: (
  title: "{name_escaped}",
  date: "{date_escaped}"))

= {title_display}

{body}

= List of Labels
#lablist()
"""

    if outputfile:
        outputfile.write_text(typst_content)
    return typst_content


def text_to_typst(
    txtname: Path, outputfile: Path = None, autolabel: bool = False
) -> str:
    """Generate Typst content from text file."""
    info_file = txtname.with_name("info.yml")
    if info_file.exists():
        with info_file.open("r") as f:
            info = yaml.safe_load(f)
            # Validate with Pydantic
            try:
                validated_info = InfoModel(**info)
                info = validated_info.model_dump()
            except ValueError as e:
                logger.warning(f"Validation error for {info_file}: {e}")
                date, name = "DATE", "NAME"
            else:
                date = info.get("dates", "DATE")
                if isinstance(date, list):
                    date = date[0] if date else "DATE"
                # Ensure date is a string
                date = str(date)
                name = info.get("label", "label")
    else:
        date, name = "DATE", "NAME"

    # Escape for Typst string literals
    name_escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    date_escaped = date.replace("\\", "\\\\").replace('"', '\\"')
    title_display = name.replace("_", " ")

    with txtname.open("r", encoding="utf-8") as f:
        text = clean_text_for_typst(f.read())

    body = ""
    if autolabel:
        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        for para_num, para in enumerate(paragraphs, 1):
            escaped_para = para.replace("\\", "\\\\").replace('"', '\\"')
            labelled = f'#lab("lab{para_num}", "{escaped_para}", "")'
            commented = "\n".join(f"// {line}" for line in para.split("\n"))
            body += labelled + "\n\n" + commented + "\n\n"
    else:
        body = text + "\n\n"

    typst_content = f"""#import "@preview/labtyp:0.1.0": lablist, lab, mset

#mset(values: (
  title: "{name_escaped}",
  date: "{date_escaped}"))

= {title_display}

{body}

= List of Labels
#lablist()
"""

    if outputfile:
        outputfile.write_text(typst_content)
    return typst_content
