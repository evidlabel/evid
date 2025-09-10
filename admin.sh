#!/bin/bash

# Format code
ruff format

# Lint and fix, pipe to out.txt
ruff check --fix > out.txt

# Commit each file separately
git add pyproject.toml
git commit pyproject.toml -m 'summary of edits for pyproject.toml'
git add src/evid/__init__.py
git commit src/evid/__init__.py -m 'summary of edits for src/evid/__init__.py'
git add src/evid/cli/evidence.py
git commit src/evid/cli/evidence.py -m 'summary of edits for src/evid/cli/evidence.py'
git add src/evid/cli/dataset.py
git commit src/evid/cli/dataset.py -m 'summary of edits for src/evid/cli/dataset.py'
git add src/evid/cli/main.py
git commit src/evid/cli/main.py -m 'summary of edits for src/evid/cli/main.py'
git add src/evid/cli/__init__.py
git commit src/evid/cli/__init__.py -m 'summary of edits for src/evid/cli/__init__.py'
git add src/evid/gui/main.py
git commit src/evid/gui/main.py -m 'summary of edits for src/evid/gui/main.py'
git add src/evid/gui/tabs/add_evidence.py
git commit src/evid/gui/tabs/add_evidence.py -m 'summary of edits for src/evid/gui/tabs/add_evidence.py'
git add src/evid/gui/tabs/browse_evidence.py
git commit src/evid/gui/tabs/browse_evidence.py -m 'summary of edits for src/evid/gui/tabs/browse_evidence.py'
git add src/evid/core/bibtex.py
git commit src/evid/core/bibtex.py -m 'summary of edits for src/evid/core/bibtex.py'
git add src/evid/core/rebut_doc.py
git commit src/evid/core/rebut_doc.py -m 'summary of edits for src/evid/core/rebut_doc.py'
git add src/evid/core/label_setup.py
git commit src/evid/core/label_setup.py -m 'summary of edits for src/evid/core/label_setup.py'
git add src/evid/core/label.py
git commit src/evid/core/label.py -m 'summary of edits for src/evid/core/label.py'
git add src/evid/core/models.py
git commit src/evid/core/models.py -m 'summary of edits for src/evid/core/models.py'
git add src/evid/core/pdf_metadata.py
git commit src/evid/core/pdf_metadata.py -m 'summary of edits for src/evid/core/pdf_metadata.py'
git add src/evid/core/database.py
git commit src/evid/core/database.py -m 'summary of edits for src/evid/core/database.py'
git add src/evid/utils/text.py
git commit src/evid/utils/text.py -m 'summary of edits for src/evid/utils/text.py'
git add tests/test_cli.py
git commit tests/test_cli.py -m 'summary of edits for tests/test_cli.py'
git add tests/test_cli_main.py
git commit tests/test_cli_main.py -m 'summary of edits for tests/test_cli_main.py'
git add tests/test_core_label.py
git commit tests/test_core_label.py -m 'summary of edits for tests/test_core_label.py'
git add tests/test_cli_evidence.py
git commit tests/test_cli_evidence.py -m 'summary of edits for tests/test_cli_evidence.py'
git add tests/test_core_rebut_doc.py
git commit tests/test_core_rebut_doc.py -m 'summary of edits for tests/test_core_rebut_doc.py'
git add tests/test_core_database.py
git commit tests/test_core_database.py -m 'summary of edits for tests/test_core_database.py'
git add tests/test_gui_main.py
git commit tests/test_gui_main.py -m 'summary of edits for tests/test_gui_main.py'
git add tests/test_core_bibtex.py
git commit tests/test_core_bibtex.py -m 'summary of edits for tests/test_core_bibtex.py'
git add tests/test_evidence.py
git commit tests/test_evidence.py -m 'summary of edits for tests/test_evidence.py'
git add tests/test_gui_add_evidence.py
git commit tests/test_gui_add_evidence.py -m 'summary of edits for tests/test_gui_add_evidence.py'
git add tests/test_label_setup.py
git commit tests/test_label_setup.py -m 'summary of edits for tests/test_label_setup.py'
git add tests/test_core_pdf_metadata.py
git commit tests/test_core_pdf_metadata.py -m 'summary of edits for tests/test_core_pdf_metadata.py'
git add tests/test_gui_browse_evidence.py
git commit tests/test_gui_browse_evidence.py -m 'summary of edits for tests/test_gui_browse_evidence.py'
git add tests/test_rebut_doc.py
git commit tests/test_rebut_doc.py -m 'summary of edits for tests/test_rebut_doc.py'
git add tests/test_core_label_setup.py
git commit tests/test_core_label_setup.py -m 'summary of edits for tests/test_core_label_setup.py'
git add tests/test_cli_dataset.py
git commit tests/test_cli_dataset.py -m 'summary of edits for tests/test_cli_dataset.py'
git add tests/test_database.py
git commit tests/test_database.py -m 'summary of edits for tests/test_database.py'
git add tests/test_init.py
git commit tests/test_init.py -m 'summary of edits for tests/test_init.py'
git add tests/test_utils_text.py
git commit tests/test_utils_text.py -m 'summary of edits for tests/test_utils_text.py'

# Run tests, append to out.txt
uv run pytest -v >> out.txt
