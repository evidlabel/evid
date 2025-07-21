![Deploy](https://github.com/evidlabel/evid/actions/workflows/ci.yml/badge.svg)![Version](https://img.shields.io/github/v/release/evidlabel/evid)
# evid - pdf labeler
`evid` is an application, aimed at the legal industry, for labelling pdf text content and making the labels citeable (for use in e.g. LaTeX or typst). 

<!-- Python-based tool for managing PDF files with metadata extraction and organization capabilities. It features a PyQt6-based GUI and a command-line interface (CLI). -->

## Workflow
- Create a dataset
- Add pdfs
- Label pdfs using an editor, surrounding labelled text with `\lb{<bibtexkey>}{text}{<remark>}`
- Latex compilation of the labelled `label.tex` file will produce a table of labels. 
- Use `generate bibtex` to create a bibtex file. 
- Use `rebut` to create a line-by-line rebuttal, that can be used in an LLM (the remarks are line prompts for the LLM).  

<!-- ## Features
- PDF logging with metadata (title, authors, tags, dates)
- Automatic date extraction from PDFs
- PyQt6 GUI with tabs for adding and browsing documents
- CLI for adding PDFs via URL or local file
- LaTeX document generation for labels and rebuttals -->

## Installation

```bash
uv pip install https://github.com/evidlabel/evid.git
```

## Usage
### GUI
Launch the gui using:
```bash
evid 
```
Which gives access to a two pane app, one for adding files, and one for browsing datasets. 

<img src="docs/assets/image.png" alt="drawing" width="50%"/><img src="docs/assets/browse.png" alt="drawing" width="50%"/>

Launch the GUI with `evid gui` or just `evid` to access the interface for adding and browsing documents.

### CLI

Use the CLI to add PDFs:
- Add a PDF (from URL or local file):
```bash
evid add <url_or_path> 
```

If `--dataset` is not specified, the CLI prompts you to select or create a dataset. 
The `add` command automatically detects whether the input is a URL (starting with `http://` or `https://`) or a local file path. Each PDF is stored in a unique folder (named with a UUID) alongside an `info.yml` file containing metadata.

## Documentation 

For more detailed information, visit the [documentation page](https://evidlabel.github.io/evid/).

## Labelling
- When selecting a document and pressing the "Label" button, a LaTeX document is generated that contains the extracted text from the PDF. 
The LaTeX document is saved in the same folder as the PDF. 

- The user can now label using their text editor inside the LaTeX document, for vscode, the following keybinding will allow labelling by selecting text and pressing `ctrl+l`:
```json 
[
    {
        "key": "ctrl+l",
        "command": "editor.action.insertSnippet",
        "when": "editorTextFocus && editorLangId == 'latex'",
        "args": {
            "snippet": "\\lb{$1}{${TM_SELECTED_TEXT}}{$2}"
        }
    }
]
```
The first field is the label attached (generally a short descriptive string), the second field is the text that was highlighted, and the third field is a comment about the label (for possible use by an LLM).

- The header in the LaTeX document causes LaTeX compilation to write the labels to `label.csv`. 
- The csv file is translated to `label_table.bib` upon exiting the label editor (i.e. closing `vscode`).  
- The `label_table.bib` files for each pdf can be concatenated, and used to formulate a rebuttal. 
  - Note that the first 4 characters of the pdf's uuid are used as a prefix for the bibtex label, this means that the labels only have to have a unique ID for the same pdf, not across all pdfs in the dataset. 

