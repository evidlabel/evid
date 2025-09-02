#!/bin/bash

ruff format
ruff check --fix > out.txt
git commit tests/test_cli_main.py -m 'Fixed CLI main tests by proper mocking and setup'
git commit tests/test_gui_main.py -m 'Fixed GUI main test by importing patch and addressing F841'
uv run pytest -v >> out.txt
