# evid - PDF labeller

evid is a Python-based tool for managing PDF files with metadata extraction and organization capabilities, featuring a PyQt6-based GUI and a command-line interface.

## Features
- PDF logging with metadata (title, authors, tags, dates)
- Automatic date extraction from PDFs
- PyQt6 GUI with tabs for adding and browsing documents
- CLI for adding PDFs via URL or local file
- LaTeX document generation for labels and rebuttals

## Installation
1. Clone the repository: git clone <repository-url>
2. Install dependencies: poetry install
3. Run GUI: poetry run evid-gui or CLI: poetry run evid --help

## Usage
Launch the GUI with poetry run evid-gui to access the interface for adding and browsing documents.

Use the CLI to add PDFs:
- Add from URL: poetry run evid add-url <url> [--dataset <dataset>]
- Add local PDF: poetry run evid add-localpdf <path> [--dataset <dataset>]

If --dataset is not specified, the CLI prompts to select or create a dataset.

