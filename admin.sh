#!/bin/bash

ruff format .
ruff check --fix . > out.txt
git commit src/evid/cli/main.py -m 'Fixed rc command by renaming --print option to --show to avoid shadowing built-in print'
uv
uv run pytest -v >> out.txt

