# VecDB

A command-line tool for managing a vector database of LaTeX snippets using ChromaDB.

## Installation

Prefer using uv for faster installation:

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[test]"
```

Alternatively, with pip:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
```

## Usage

Initialize a collection:

```bash
vecdb init --directory /path/to/db --collection mycollection
```

Add LaTeX files from a directory:

```bash
vecdb add --directory /path/to/db --collection mycollection --target-dir /path/to/tex/files
```

Query the collection:

```bash
vecdb query --directory /path/to/db --collection mycollection --query-text "search term" --top-n 5 --full
```

## Running Tests

```bash
pytest
```

## Documentation

Build and serve the docs:

```bash
mkdocs serve
```
