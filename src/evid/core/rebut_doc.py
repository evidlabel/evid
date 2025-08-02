from pathlib import Path
import logging
import bibtexparser as bib
import subprocess

from evid.core.label_setup import csv_to_bib

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
    csv_file = workdir / "label.csv"
    bib_file = workdir / "label.bib"
    rebut_file = workdir / "rebut.typ"

    try:
        if not csv_file.exists():
            raise FileNotFoundError(f"CSV file {csv_file} not found")
        if not csv_file.stat().st_size:
            raise ValueError(f"CSV file {csv_file} is empty")

        csv_to_bib(csv_file, bib_file, exclude_note=True)
        rebut_body = base_rebuttal(bib_file)
        write_rebuttal(rebut_body, rebut_file)

        if rebut_file.exists():
            subprocess.run(["xdg-open", str(rebut_file)], check=True)
        else:
            logger.warning(f"Rebuttal file {rebut_file} was not generated")
            raise RuntimeError("Rebuttal file was not generated")

    except Exception as e:
        logger.error(f"Failed to generate rebuttal: {str(e)}")
        raise


