# Usage Guide

This guide explains how to use `evid` to manage PDF documents through its PyQt6-based GUI or command-line interface (CLI).

## Configuration

You can configure the default database location by creating a `~/.evidrc` file in YAML format. Example:

```yaml
default_dir: ~/my_custom_evid_db
```

If no `.evidrc` file is found, the default database location is `~/Documents/evid`. Alternatively, you can specify a custom directory when running CLI commands using the `--directory` or `-d` option.

## Launching the Application

Launch the GUI with:

```bash
evid [-d|--directory <custom_dir>]
```

This opens the GUI with two tabs: Add and Browse. The optional `-d` or `--directory` argument allows you to specify a custom database directory (e.g., `evid -d ~/my_evid_db`).

Alternatively, use the CLI to view available commands:

```bash
evid --help
```

## Listing Datasets

To see all available datasets, use the CLI:

```bash
evid list [-d|--directory <custom_dir>]
```

This displays a numbered list of existing datasets in the specified or default database location.

## Managing Datasets

### Creating Datasets

#### Via GUI

In the Add tab, enter a new dataset name in the "New Dataset" field and click Create. If the dataset already exists, a warning will appear.

#### Via CLI

Create a new dataset with:

```bash
evid set create <dataset_name> [-d|--directory <custom_dir>]
```

This creates a new dataset directory in the specified or default database location. If the dataset already exists, the command will fail with an error message.

### Tracking Datasets with Git

To enable Git version control for a dataset, use:

```bash
evid set track [<dataset_name>] [-d|--directory <custom_dir>]
```

If no dataset name is provided, the CLI will prompt you to select an existing dataset. This command initializes a Git repository in the dataset's top-level directory with a `.gitignore` file that tracks only `label.bib`, `*.typ`, `info.yml`, `*.pdf`, and `*.txt` files, ignoring others (e.g., Typst byproducts like `label.pdf`). If the dataset is already a Git repository, the command will fail with an error message.

### Generating BibTeX Files

To generate a BibTeX file from a `label.typ` file, use:

```bash
evid bibtex <typ_file> [-p|--parallel]
```

This command processes the specified `label.typ` file, generating a `label.bib` file in its respective directory. Use the `-p` or `--parallel` flag to process files concurrently (though currently supports single file). If no `typ_file` is provided, the command will display an error message. Errors are logged without stopping the process.

Example:

```bash
evid bibtex path/to/label.typ -p
```

This generates a BibTeX file from the specified `label.typ` file.

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
evid add <url_or_path> [-s|--dataset <dataset>] [-l|--label] [-d|--directory <custom_dir>]
```

If `-s` or `--dataset` is not provided, the CLI prompts you to select an existing dataset. If the specified dataset does not exist, the command will fail with an error. The `add` command automatically detects whether the input is a URL (starting with `http://` or `https://`) or a local file path. After adding, it prints the metadata to stdout. Use `-l` or `--label` to open the labeler after adding the PDF. Use `-d` or `--directory` to specify a custom database directory.

## Browsing Documents

Use the Browse tab in the GUI to view and manage existing documents.

1. Load a Dataset:
- Select a dataset from the dropdown and click Load.
- The table displays metadata (Author, Title, Date, File Name, UUID) for each document entry.

2. View Details:
- Select a row and click Open Dir to open the document folder in Visual Studio Code.

3. Create Labels:
- Select one or more entries (hold Ctrl or Shift to select multiple) and click Label Selected to generate Typst documents (`label.typ`) for each selected PDF.
- Each Typst file opens in a separate Visual Studio Code instance, allowing parallel editing without freezing the main application.
- Edit each Typst file in Visual Studio Code (Ctrl+L inserts a lb snippet) to add labels.
- Upon closing the editor, the system extracts labels to JSON and generates `label.bib`.

4. Generate BibTeX:
- Select one or more entries and click Generate BibTeX to generate `label.bib` from `label.typ` for each selected entry.
- This is useful for updating BibTeX files after edits to Typst files.

5. Generate Responses:
- Select an entry and click Rebut to create a response document (`rebut.typ`) using the BibTeX file.
- The response lists citations with notes, formatted in Typst, suitable for LLM integration.

## Labelling

- When selecting one or more documents and pressing the "Label Selected" button, a Typst document is generated for each PDF containing the extracted text.
The Typst documents are saved in the same folder as their respective PDFs and opened in Visual Studio Code for editing.

- The user can label using their text editor inside the Typst document. For VS Code, the following keybinding allows labelling by selecting text and pressing `ctrl+l`:

```json
    {
        "key": "ctrl+L",
        "command": "editor.action.insertSnippet",
        "when": "editorTextFocus && editorLangId == 'typst'",
        "args": {"snippet": "#lab(\"$1\",\"${TM_SELECTED_TEXT}\",\"$2\")"}
    }
```


The first field is the label attached (generally a short descriptive string), the second field is the text that was highlighted, and the third field is a comment about the label (for possible use by an LLM).

- After editing and saving the Typst file, upon closing the editor, the system runs a Typst query to extract labels into `label.json` and converts it to `label.bib`.
- You can also manually generate or update the `label.bib` by clicking "Generate BibTeX" in the Browse tab or using the `bibtex` CLI command.
- The `label.bib` files for each PDF can be concatenated and used to formulate a rebuttal.
- Note that the first 4 characters of the PDF's UUID are used as a prefix for the BibTeX label, ensuring labels only need to be unique within the same PDF, not across all PDFs in the dataset.

### Via CLI

Label an evidence in a dataset with:

```bash
evid label [-s|--dataset <dataset>] [-u|--uuid <uuid>] [-d|--directory <custom_dir>]
```

If `-s` or `--dataset` is not provided, the CLI prompts you to select a dataset. If `-u` or `--uuid` is not provided, the CLI prompts you to select an evidence from the dataset. This command generates and opens the label file for the specified evidence.

## Initializing Configuration

To initialize or update the `.evidrc` configuration file with default settings, use:

```bash
evid rc
```

This command creates or updates `~/.evidrc` by adding missing fields from the default configuration, ensuring all required settings are present.

## Tips

- **Date Extraction**: `evid` automatically extracts dates from PDFs in various formats (e.g., "12/01/2023", "15. januar 2024").
- **Typst Setup**: Ensure Typst is installed for label and response generation.
- **VS Code Integration**: Use the provided `.vscode/keybindings.json` for a Ctrl+L shortcut in Typst files.
- **Git Tracking**: After tracking a dataset with `evid set track`, use standard Git commands (`git add`, `git commit`, etc.) to manage changes to tracked files (`label.bib`, `*.typ`, `info.yml`, `*.pdf`, `*.txt`).
- **Custom Directory**: Use the `-d` or `--directory` option with CLI commands to work with datasets in a non-default location (e.g., `evid list -d ~/my_evid_db`).

For development details, see the [Development](development.md) section.


