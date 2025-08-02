from pathlib import Path
import logging
import bibtexparser as bib
import subprocess

from evid.core.label_setup import json_to_bib

logger = logging.getLogger(__name__)

TYPST_TEMPLATE = r"""#set text(lang: "da")

#grid(
  columns: (auto, 1fr),
  gutter: 1em,
  strong("Topic"),   "",
  strong("Reference"), "",
  strong("Author"),   "",
  strong("Date"), datetime.today().display("[day]-[month]-[year]"),
)

POINTS

#bibliography("BIBPATH", title: "Referencer", style: "ieee", full: true)
"""


def base_rebuttal(bibfile: Path) -> str:
    """Generate Typst rebuttal content from a BibTeX file."""
    try:
        bibdb = bib.load(open(bibfile))
    except Exception as e:
        logger.error(f"Failed to load BibTeX file {bibfile}: {str(e)}")
        raise ValueError(f"Invalid BibTeX file: {str(e)}")

    body = ""
    for row in bibdb.entries:
        note_key = "nonote" if "nonote" in row else "note"
        note = row[note_key]
        prompt = "\n".join(f"// {line}" for line in note.splitlines())
        body += f"{prompt}\n+ Regarding: #cite(<{row['ID']}>, form: \"full\")\n\n"

    rebuttal_body = TYPST_TEMPLATE.replace("POINTS", body).replace(
        "BIBPATH", bibfile.name
    )
    return rebuttal_body


def write_rebuttal(body: str, output_file: Path):
    """Write rebuttal content to file if it doesn't exist."""
    if not output_file.exists():
        with open(output_file, "w", encoding="utf-8") as rebuttal_file:
            rebuttal_file.write(body)
            logger.info(f"Written a new {output_file}")
    else:
        logger.info(f"{output_file} already exists. Not overwriting.")


def rebut_doc(workdir: Path):
    """Generate rebuttal document from evidence directory."""
    from .label_setup import csv_to_bib

    json_file = workdir / "label.json"
    bib_file = workdir / "label1.bib"
    rebut_file = workdir / "rebut.typ"

    try:
        if not json_file.exists():
            raise FileNotFoundError(f"JSON file {json_file} not found")
        if not json_file.stat().st_size:
            raise ValueError(f"JSON file {json_file} is empty")

        json_to_bib(json_file, bib_file, exclude_note=True)
        rebut_body = base_rebuttal(bib_file)
        write_rebuttal(rebut_body, rebut_file)

        if rebut_file.exists():
            try:
                pdf_file = rebut_file.with_suffix(".pdf")
                subprocess.run(
                    ["typst", "compile", str(rebut_file), str(pdf_file)], check=True
                )
                subprocess.run(["xdg-open", str(pdf_file)], check=True)
            except subprocess.SubprocessError as e:
                logger.warning(
                    f"Failed to compile and open PDF: {str(e)}. Opening source file instead."
                )
                subprocess.run(["xdg-open", str(rebut_file)], check=True)
        else:
            logger.warning(f"Rebuttal file {rebut_file} was not generated")
            raise RuntimeError("Rebuttal file was not generated")

    except Exception as e:
        logger.error(f"Failed to generate rebuttal: {str(e)}")
        raise
