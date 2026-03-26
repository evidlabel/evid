[![Test](https://github.com/evidlabel/did/actions/workflows/pytest.yaml/badge.svg)](https://github.com/evidlabel/did/actions/workflows/pytest.yml)![Version](https://img.shields.io/github/v/release/evidlabel/did)

# DID (De-ID) Pseudonymizer

A CLI tool to anonymize Markdown, plain text, TeX, and BibTeX files with spaCy-based entity detection and automatic YAML configuration.

## Features
- Detects names, emails, addresses, phone numbers, and CPR numbers using Presidio with spaCy
- Groups name and number variants using rapidfuzz
- Extracts entities to generate a YAML config (`did extract`)
- Anonymizes text using YAML config (`did pseudo`), preserving file formats
- Supports English (`en`) and Danish (`da`)

## Installation
```bash
uv pip install https://github.com/evidlabel/did.git
```

## Quick Usage

```bash
uv sync --dev  # installs test/dev deps
pre-commit install
pre-commit run --all-files
pytest --cov
```

## Quick Usage

![help](docs/assets/help.svg)
For details, see the [documentation](docs/index.md).
