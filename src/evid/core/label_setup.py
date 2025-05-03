from pathlib import Path
import fitz
import re
import yaml


LATEX_TEMPLATE = r"""
\documentclass[parskip=full]{article}
\nonstopmode

%% HEADER

\usepackage{xargs}
\usepackage{xcolor}
\usepackage{hyperref}
\hypersetup{
  colorlinks=true,
  linkcolor=blue,
  anchorcolor=blue,
  filecolor=magenta,
  urlcolor=cyan,
}

\usepackage{todonotes}
\usepackage{etoolbox}
\makeatletter
\pretocmd{\@startsection}{\gdef\thesectiontype{#1}}{}{}
\pretocmd{\@sect}{\@namedef{the\thesectiontype title}{#8}}{}{}
\pretocmd{\@ssect}{\@namedef{the\thesectiontype title}{#5}}{}{}
\makeatother

\newwrite\textfile
\immediate\openout\textfile=\jobname.csv
\immediate\write\textfile{label ; quote ; note ; section title ; section no ; page ; date ; opage}


\newcommandx{\lb}[3]{\immediate\write\textfile{#1 \space; #2 \space; #3 \space; \thesectiontitle \space;  \thesection  \space;  \thepage  \space;  \pdate \space; \thesubsectiontitle}%
  \csdef{#1}{#2}%
  \hypertarget{#1}{\textcolor{blue}{#2}}\todo[color=blue!10!white,caption={\small#1; #3; #2}]{#1: #3}%
}

\newcommandx{\cc}[1]{
  \hyperlink{#1}{\csuse{#1}}
}


\newcommand{\sdate}[1]{%
  \def\localdate{#1}%
}

\newcommand{\pdate}{%
  \localdate%
}

\usepackage{scrextend}
%% HEADER

% \title{}

\begin{document}
\maketitle

\tableofcontents
\listoftodos[Labels]

\sdate{DATE}

\section{NAME}
BODY

\end{document}
"""


def clean_text_for_latex(text: str) -> str:
    # Only escape specific LaTeX special characters as per test expectation
    text = re.sub(r"([#%&])", r"\\\1", text)
    text = re.sub(r"(\n\s*\n)+", r"\n\n", text)
    return text


def textpdf_to_latex(pdfname: Path, outputfile: Path = None) -> str:
    info_file = pdfname.with_name("info.yml")
    if info_file.exists():
        with info_file.open() as f:
            info = yaml.safe_load(f)
            date = info.get("dates", "DATE")
            if isinstance(date, list):
                date = date[0] if date else "DATE"
            # Ensure date is a string
            date = str(date)
            name = info.get("label", "label")
    else:
        date, name = "DATE", "NAME"

    pdf = fitz.open(pdfname)
    text = "".join(
        f"\\subsection{{{i.number}}}\n\n{clean_text_for_latex(i.get_text())}"
        for i in pdf
    )
    pdf.close()

    out = (
        LATEX_TEMPLATE.replace("BODY", text)
        .replace("DATE", date)
        .replace("NAME", name.replace("_", " "))
    )

    if outputfile:
        outputfile.write_text(out)
    return out
