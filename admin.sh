#!/bin/bash

# Run ruff format
ruff format

# Run ruff check with fix and pipe to out.txt
ruff check --fix > out.txt

# Stage and commit modified files
git add src/evid/cli/main.py
git commit -m 'Add custom rich help printing with colors and structured output for CLI commands and options'

# Run pytest and append to out.txt
uv run pytest -v >> out.txt

