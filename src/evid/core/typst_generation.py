"""Typst generation functions for evid."""

from pathlib import Path
import yaml
import logging
from evid.core.models import InfoModel
from evid.core.text_cleaning import clean_text_for_typst

logger = logging.getLogger(__name__)


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
