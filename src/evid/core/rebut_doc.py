from pathlib import Path
import logging
import bibtexparser as bib
import subprocess

logger = logging.getLogger(__name__)

REBUT_TEMPLATE = r"""\documentclass[12pt]{article}
    \usepackage{tabularx}
    \usepackage{hyperref}
    \usepackage[backend=biber,style=numeric,sorting=none]{biblatex}
    \addbibresource{BIBPATH}
    \usepackage[breakable]{tcolorbox}
    \usepackage[danish]{babel}
    \newcommand{\bcite}[1]{\begin{tcolorbox}[left skip=0cm,   size=fbox, arc=1mm, boxsep=0mm,left=1mm, right=1mm, top=1mm, bottom=1mm, colframe=black, colback=white,box align=base, breakable]
    {\small \cite{#1}: \fullcite{#1}}
    \end{tcolorbox}}
    \usepackage{enumitem}
    \newcounter{globalenumi}
    
    % Custom enumerate environment using the global counter
    \newenvironment{cenum}
    {
        \begin{enumerate}
            \setcounter{enumi}{\value{globalenumi}} % Set enumi to the global counter
            }
            {
            \setcounter{globalenumi}{\value{enumi}} % Save enumi back to the global counter
        \end{enumerate}
    }

\begin{document}
\noindent\begin{tabularx}{\textwidth}{l|X}
      \textbf{Topic}   &       \\
      \textbf{Reference}&        \\
      \textbf{Author}&        \\
      \textbf{Date}  & \today \\
\end{tabularx}

\begin{cenum}
POINTS
\end{cenum}

\printbibliography[title={Referencer}]

\end{document}
"""


def base_rebuttal(bibfile: Path) -> str:
    bibdb = bib.load(open(bibfile))

    latex_body = ""
    for row in bibdb.entries:
        latex_body += (
            f"\t% prompt: {row['nonote'] if 'nonote' in row else row['note']}\n"
        )
        latex_body += f"\t\\item Angående citat: \\bcite{{{row['ID']}}} \n"

    rebuttal_body = REBUT_TEMPLATE.replace("POINTS", latex_body).replace(
        "BIBPATH", str(bibfile.absolute())
    )
    return rebuttal_body


def write_rebuttal(body: str, output_file: Path):
    if not output_file.exists():
        with open(output_file, "w") as rebuttal_file:
            rebuttal_file.write(body)
            logger.info(f"Written a new {output_file}")
    else:
        logger.info(f"{output_file} already exists. Not overwriting.")


def rebut_doc(workdir: Path):
    """Generate rebuttal document from evidence directory."""
    from .label_setup import csv_to_bib

    csv_file = workdir / "label.csv"
    bib_file = workdir / "label_table.bib"
    rebut_file = workdir / "rebut.tex"

    try:
        if csv_file.exists():
            csv_to_bib(csv_file, bib_file, exclude_note=True)
        else:
            raise FileNotFoundError(f"CSV file {csv_file} not found")

        rebut_body = base_rebuttal(bib_file)
        write_rebuttal(rebut_body, rebut_file)

        if rebut_file.exists():
            subprocess.run(["xdg-open", str(rebut_file)])
        else:
            logger.warning(f"Rebuttal file {rebut_file} was not generated")
    except Exception as e:
        logger.error(f"Failed to generate rebuttal: {str(e)}")
        raise
