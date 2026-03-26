#!/bin/bash
src/evid/gui/tabs/add_evidence.py
pyproject.toml

ruff format
ruff check --fix > out.txt

git add src/evid/gui/tabs/add_evidence.py
git commit src/evid/gui/tabs/add_evidence.py -m 'Adjust temp file handling for URL downloads to use temp dir with original filename'

git add pyproject.toml
git commit pyproject.toml -m 'Add pyproject.toml to make CLI callable'

uv run pytest -v >> out.txt
