# Usage Guide

This guide explains how to use evid to manage PDF documents through its PyQt6-based GUI or command-line interface (CLI).

## Configuration

You can configure the default database location by creating a `~/.evidrc` file in YAML format. Example:

```yaml
default_dir: ~/my_custom_evid_db
```

If no `.evidrc` file is found, the default database location is `~/Documents/evid`. Alternatively, you can specify a custom directory when running CLI commands using the `--directory` option.

## Launching the Application

Launch the GUI with:

```bash
poetry run evid gui [--directory <custom_dir>]
```

This opens the GUI with two tabs: Add and Browse. The optional `--directory` argument allows you to specify a custom database directory (e.g., `poetry run evid gui --directory ~/my_evid_db`).

Alternatively, use the CLI to view available commands:

```bash
poetry run evid --help
```

## Listing Datasets

To see all available datasets, use the CLI:

```bash
poetry run evid list [--directory <custom_dir>]
```

This displays a numbered list of existing datasets in the specified or default database location.

## Managing Datasets

### Creating Datasets

#### Via GUI

In the Add tab, enter a new dataset name in the "New Dataset" field and click Create. If the dataset already exists, a warning will appear.

#### Via CLI

Create a new dataset with:

```bash
poetry run evid set create <dataset_name> [--directory <custom_dir>]
```

This creates a new dataset directory in the specified or default database location. If the dataset already exists, the command will fail with an error message.

### Tracking Datasets with Git

To enable Git version control for a dataset, use:

```bash
poetry run evid set track [<dataset_name>] [--directory <custom_dir>]
```

If no dataset name is provided, the CLI will prompt you to select an existing dataset. This command initializes a Git repository in the dataset's top-level directory with a `.gitignore` file that tracks only `label.csv`, `label_table.bib`, `*.tex`, `info.yml`, and `*.pdf` files, ignoring others (e.g., LaTeX byproducts like `label.pdf`). If the dataset is already a Git repository, the command will fail with an error message.

### Generating BibTeX Files

To convert all `label.csv` files in a dataset to `label_table.bib` files, use:

```bash
poetry run evid bibtex <dataset_name> [--parallel] [--directory <custom_dir>]
```

This command processes all `label.csv` files in the specified dataset, generating a `label_table.bib` file for each in its respective directory. Use the `--parallel` flag to process files concurrently, which can significantly speed up processing for large datasets. If the dataset does not exist or no `label.csv` files are found, the command will display an appropriate message. Errors for individual files are logged without stopping the process.

Example:

```bash
poetry run evid bibtex my_dataset --parallel --directory ~/my_evid_db
```

This generates BibTeX files for all `label.csv` files in `~/my_evid_db/my_dataset`, using parallel processing.

## Adding Documents

### Via GUI

Use the Add tab to log PDFs with metadata.

1. Select or Create a Dataset:
   
   - Choose an existing dataset from the dropdown or enter a new dataset name and click Create.
   - Datasets are folders in the default or specified database directory where documents are stored.

2. Add a PDF:
   
   - Click Browse to select a local PDF or enter a URL and click Quick Add URL.
   - The GUI auto-fills metadata (title, authors, dates) from the PDF if possible.

3. Fill Metadata:
   
   - Edit fields like Title, Authors, Tags, Dates, Label, and URL.
   - Preview the metadata in the preview pane.
   - Note: Metadata fields like title and authors are stored as plain text in `info.yml` for readability, with Danish characters (Ã¦, Ã¸, Ã¥) preserved.

4. Save Document:
   
   - Click Add to save the PDF and metadata to a unique folder in the selected dataset.
   - Metadata is stored in an `info.yml` file alongside the PDF.

### Via CLI

Add PDFs using the CLI with the following command:

- Add a PDF (from URL or local file):

```bash
poetry run evid add <url_or_path> [--dataset <dataset>] [--directory <custom_dir>]
```

If `--dataset` is not provided, the CLI prompts you to select an existing dataset. If the specified dataset does not exist, the command will fail with an error. The `add` command automatically detects whether the input is a URL (starting with `http://` or `https://`) or a local file path. After adding, it prints the metadata to stdout and prompts to open the `info.yml` file in Visual Studio Code. Use `--directory` to specify a custom database directory.

## Browsing Documents

Use the Browse tab in the GUI to view and manage existing documents.

1. Load a Dataset:
   - Select a dataset from the dropdown and click Load.
   - The table displays metadata (Author, Title, Date, File Name, UUID) for each document entry.

2. View Details:
   - Select a row and click Open Dir to open the document folder in Visual Studio Code.

3. Create Labels:
   - Select one or more entries (hold Ctrl or Shift to select multiple) and click Label Selected to generate LaTeX documents (`label.tex`) for each selected PDF.
   - Each LaTeX file opens in a separate Visual Studio Code instance, allowing parallel editing without freezing the main application.
   - Edit each LaTeX file in Visual Studio Code (Ctrl+L inserts a `\lb` snippet) to add labels.
   - Save the file to generate a `label.csv`, which is then converted to `label_table.bib`.

4. Generate BibTeX:
   - Select one or more entries and click Generate BibTeX to convert existing `label.csv` files to `label_table.bib` for each selected PDF.
   - This is useful for updating BibTeX files after manual edits to `label.csv` or LaTeX files.

5. Generate Responses:
   - Select an entry and click Rebut to create a response document (`rebut.tex`) using the BibTeX file.
   - The response lists citations with notes, formatted in LaTeX, suitable for LLM integration.

## Labelling

- When selecting one or more documents and pressing the "Label Selected" button, a LaTeX document is generated for each PDF containing the extracted text.
The LaTeX documents are saved in the same folder as their respective PDFs and opened in Visual Studio Code for editing.

- The user can label using their text editor inside the LaTeX document. For VS Code, the following keybinding allows labelling by selecting text and pressing `ctrl+l`:
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

- The header in each LaTeX document causes LaTeX compilation to write the labels to `label.csv`.
- The `label.csv` file can be converted to `label_table.bib` by clicking "Generate BibTeX" in the Browse tab, using the `bibtex` CLI command, or upon exiting the label editor (i.e., closing VS Code after editing `label.tex`).
- The `label_table.bib` files for each PDF can be concatenated and used to formulate a rebuttal.
  - Note that the first 4 characters of the PDF's UUID are used as a prefix for the BibTeX label, ensuring labels only need to be unique within the same PDF, not across all PDFs in the dataset.

## Tips

- **Date Extraction**: evid automatically extracts dates from PDFs in various formats (e.g., "12/01/2023", "15. januar 2024").
- **LaTeX Setup**: Ensure a LaTeX distribution is installed for label and response generation.
- **VS Code Integration**: Use the provided `.vscode/keybindings.json` for a Ctrl+L shortcut in LaTeX files.
- **Git Tracking**: After tracking a dataset with `evid set track`, use standard Git commands (`git add`, `git commit`, etc.) to manage changes to tracked files (`label.csv`, `label_table.bib`, `*.tex`, `info.yml`, `*.pdf`).
- **Custom Directory**: Use the `--directory` option with CLI commands to work with datasets in a non-default location (e.g., `poetry run evid list --directory ~/my_evid_db`).

For development details, see the [Development](development.md) section.
