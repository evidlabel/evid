# Development Guide

This guide is for developers looking to contribute to or extend `evid`, a tool for managing PDF documents with metadata and labels.

## Project Structure

```
evid/
├── src/
│   ├── evid/
│   │   ├── core/           # Core functionality (database, date extraction, LaTeX)
│   │   ├── gui/            # PyQt6 GUI components
│   │   ├── cli/            # Command-line interface modules
│   │   └── __init__.py     # Package metadata
├── tests/                  # Unit tests
├── docs/                   # MkDocs documentation
├── .github/workflows/      # CI pipeline
├── pyproject.toml          # Project configuration
├── README.md               # Project overview
└── mkdocs.yml              # MkDocs configuration
```

## Setting Up for Development

1. **Clone and Install**:

```bash
git clone <repository-url>
cd evid
uv pip install .
```

This installs `evid` and its dependencies using `uv`.

2. **Run Tests**:

```bash
pytest
```

Tests cover date extraction, GUI components, LaTeX generation, and database functionality.

## Contributing

1. **Fork and Branch**:
- Fork the repository and create a feature branch: `git checkout -b feature/your-feature`.

2. **Code Style**:
- Follow PEP 8 for Python code.
- Use type hints where applicable (see `src/evid/core/` for examples).
- Add docstrings for public functions and classes.

3. **Add Tests**:
- Add unit tests in the `tests/` directory for new functionality.
- Use `pytest` fixtures for setup (e.g., `temp_pdf` in `test_dateextract.py`).

4. **Update Documentation**:
- Modify `docs/` files for new features or changes.
- Preview documentation locally:

```bash
mkdocs serve
```

5. **Submit a Pull Request**:
- Push your branch and create a PR against the `main` branch.
- Ensure the CI pipeline passes (runs `pytest` on Ubuntu with Python 3.11).

## Extending evid

- **New GUI Tabs**: Add new classes in `src/evid/gui/tabs/` and register them in `src/evid/gui/main.py`.
- **Custom Metadata**: Extend `info.yml` fields in `src/evid/gui/tabs/add_evidence.py`.
- **LaTeX Templates**: Modify templates in `src/evid/core/label_setup.py` or `src/evid/core/rebut_doc.py`.
- **CLI Commands**: Add new commands in `src/evid/cli/` by extending the `main.py` Click group.

For issues or feature requests, check the repository's issue tracker.

