# Usage Guide

This guide explains how to use evid to manage PDF documents through its PyQt6-based GUI or command-line interface (CLI).

## Configuration

You can configure the default database location by creating a `~/.evidrc` file in YAML format. Example:

```yaml
default_dir: ~/my_custom_evid_db
```

If no `.evidrc` file is found, the default database location is `~/Documents/evid`.

## Launching the Application

Launch the GUI with:

```bash
poetry run evid gui
```

This opens the GUI with two tabs: Add and Browse.

Alternatively, use the CLI to view available commands:

```bash
poetry run evid --help
```

## Creating Datasets

### Via GUI

In the Add tab, enter a new dataset name in the "New Dataset" field and click Create.

### Via CLI

Create a new dataset with:

```bash
poetry run evid create-dataset <dataset_name>
```

This creates a new dataset directory in the default database location.

## Adding Documents

### Via GUI

Use the Add tab to log PDFs with metadata.

1. Select or Create a Dataset:
   - Choose an existing dataset from the dropdown or enter a new dataset name and click Create.
   - Datasets are folders in the default database directory where documents are stored.

2. Add a PDF:
   - Click Browse to select a local PDF or enter a URL and click Quick Add URL.
   - The GUI auto-fills metadata (title, authors, dates) from the PDF if possible.

3. Fill Metadata:
   - Edit fields like Title, Authors, Tags, Dates, Label, and URL.
   - Preview the metadata in the preview pane.
   - Note: Metadata fields like title and authors are stored as plain text in `info.yml` for readability, with Danish characters (æ, ø, å) preserved.

4. Save Document:
   - Click Add to save the PDF and metadata to a unique folder in the selected dataset.
   - Metadata is stored in an info.yml file alongside the PDF.

### Via CLI

Add PDFs using the CLI with the following command:

- Add a PDF (from URL or local file):

```bash
poetry run evid add <url_or_path> [--dataset <dataset>]
```

If `--dataset` is not provided, the CLI prompts you to select an existing dataset or create a new one. The `add` command automatically detects whether the input is a URL (starting with `http://` or `https://`) or a local file path. After adding, it prints the metadata to stdout and prompts to open the `info.yml` file in Visual Studio Code.

## Browsing Documents

Use the Browse tab in the GUI to view and manage existing documents.

1. Load a Dataset:
   - Select a dataset from the dropdown and click Load.
   - The table displays metadata (Author, Title, Date, File Name, UUID) for each document entry.

2. View Details:
   - Select a row and click Open Dir to view the document folder in your file explorer.

3. Create Labels:
   - Select an entry and click Label to generate a LaTeX document (label.tex) from the PDF.
   - Edit the LaTeX file in Visual Studio Code (Ctrl+L inserts a \lb snippet) to add labels.
   - Save the file to generate a label.csv, which is then converted to label_table.bib.

4. Generate Responses:
   - Select an entry and click Rebut to create a response document (rebut.tex) using the BibTeX file.
   - The response lists citations with notes, formatted in LaTeX, suitable for LLM integration.

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

## Tips

- Date Extraction: evid automatically extracts dates from PDFs in various formats (e.g., "12/01/2023", "15. januar 2024").
- LaTeX Setup: Ensure a LaTeX distribution is installed for label and response generation.
- VS Code Integration: Use the provided .vscode/keybindings.json for a Ctrl+L shortcut in LaTeX files.

For development details, see the Development section.
