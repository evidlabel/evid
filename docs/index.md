# evid - pdf labeller

`evid` is a GUI application for labelling text from PDF files, aimed at the legal industry. 
With `evid` you can label snippets and add remarks on read-through, which will then be citable in Typst documents. 

## Key Features

- **PDF Logging**: Add PDFs with metadata such as title, authors, tags, and dates.
- **Automatic Date Extraction**: Extract dates from PDFs using advanced text parsing.
- **PyQt6 GUI**: Intuitive interface with tabs for adding and browsing documents.
- **Typst Integration**: Generate Typst documents for labels and responses, with BibTeX support for citations.
- **Modular Database**: Organize documents into datasets with YAML-based metadata storage.
- **CLI Support**: Manage datasets and evidence through a powerful command-line interface.

## Getting Started

- [Installation Guide](installation.md): Set up `evid` on your system.
- [Usage Guide](usage.md): Learn how to add, browse, and manage documents.
- [Development](development.md): Contribute to `evid` or extend its functionality.

## Quick Start

```bash
uv pip install https://github.com/evidlabel/evid.git
evid
```


