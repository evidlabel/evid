#!/bin/bash

# Run ruff format
ruff format

# Run ruff check with fix and pipe to out.txt
ruff check --fix > out.txt

# Run pytest and append to out.txt
uv run pytest -v >> out.txt

# Stage and commit modified files
git add src/evid/core/rebut_doc.py
git commit -m 'summary of edits for src/evid/core/rebut_doc.py'

git add admin.sh
git commit -m 'summary of edits for admin.sh'

