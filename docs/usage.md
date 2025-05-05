# Usage Guide

This guide explains how to use `evid` to manage PDF documents through its PyQt6-based GUI.

## Launching the Application

After [installation](installation.md), launch `evid` with:

```bash
poetry run evid
```

This opens the GUI with two tabs: **Add** and **Browse**.

## Adding Documents

Use the **Add** tab to log PDFs with metadata.

1. **Select or Create a Dataset**:
   - Choose an existing dataset from the dropdown or enter a new dataset name and click **Create**.
   - Datasets are folders in `~/Documents/evid` where documents are stored.

2. **Add a PDF**:
   - Click **Browse** to select a local PDF or enter a URL and click **Quick Add URL**.
   - The GUI auto-fills metadata (title, authors, dates) from the PDF if possible.

3. **Fill Metadata**:
   - Edit fields like **Title**, **Authors**, **Tags**, **Dates**, **Label**, and **URL**.
   - Preview the metadata in the preview pane.

4. **Save Document**:
   - Click **Add** to save the PDF and metadata to a unique folder in the selected dataset.
   - Metadata is stored in an `info.yml` file alongside the PDF.

## Browsing Documents

Use the **Browse** tab to view and manage existing documents.

1. **Load a Dataset**:
   - Select a dataset from the dropdown and click **Load**.
   - The table displays metadata (Author, Title, Date, File Name, UUID) for each document entry.

2. **View Details**:
   - Select a row and click **Open Dir** to view the document folder in your file explorer.

3. **Create Labels**:
   - Select an entry and click **Label** to generate a LaTeX document (`label.tex`) from the PDF.
   - Edit the LaTeX file in Visual Studio Code (Ctrl+L inserts a `\lb` snippet) to add labels.
   - Save the file to generate a `label.csv`, which is then converted to `label_table.bib`.

4. **Generate Responses**:
   - Select an entry and click **Rebut** to create a response document (`rebut.tex`) using the BibTeX file.
   - The response lists citations with notes, formatted in LaTeX, suitable for LLM integration.

## Tips

- **Date Extraction**: `evid` automatically extracts dates from PDFs in various formats (e.g., "12/01/2023", "15. januar 2024").
- **LaTeX Setup**: Ensure a LaTeX distribution is installed for label and response generation.
- **VS Code Integration**: Use the provided `.vscode/keybindings.json` for a Ctrl+L shortcut in LaTeX files.

For development details, see the [Development](development.md) section.

