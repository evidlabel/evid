#!/bin/bash

# Formatting and checking
ruff format
ruff check --fix > out.txt

# Commit modified files
git add tests/test_cli_dataset.py
git commit tests/test_cli_dataset.py -m 'Updated test_track_dataset to mock Repo constructor raising InvalidGitRepositoryError'
git add tests/test_cli_main.py
git commit tests/test_cli_main.py -m 'Set DIRECTORY in tests to avoid NoneType errors'
git add tests/test_core_bibtex.py
git commit tests/test_core_bibtex.py -m 'Changed patch target to evid.core.bibtex.json_to_bib to match import'

# Run tests
uv run pytest -v >> out.txt
