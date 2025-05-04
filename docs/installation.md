# Installation

This guide covers how to install `evid` on your system using Poetry, the project's dependency manager.

## Prerequisites

- **Python**: Version 3.9 or higher (but less than 4.0).
- **Poetry**: For dependency management and virtual environment setup.
- **Git**: To clone the repository.
- **Optional**: A LaTeX distribution (e.g., TeX Live) for generating LaTeX documents.

## Step-by-Step Installation

1. **Clone the Repository**

   ```bash
   git clone <repository-url>
   cd evid
   ```

2. **Install Poetry**

   If you don't have Poetry installed, run:

   ```bash
   curl -sSL https://install.python-poetry.org | python3 -
   ```

   Ensure Poetry is in your PATH. On Linux/macOS, you may need to add:

   ```bash
   export PATH="$HOME/.local/bin:$PATH"
   ```

3. **Install Dependencies**

   Use Poetry to install all required dependencies:

   ```bash
   poetry install
   ```

   This sets up a virtual environment and installs dependencies like `PyQt6`, `pymupdf`, and `pyyaml`.

4. **Verify Installation**

   Run the application to ensure it launches:

   ```bash
   poetry run evid
   ```

   This should open the `evid` GUI.

## Troubleshooting

- **Poetry errors**: Ensure Python 3.9+ is installed and Poetry is correctly configured. Try `poetry env use python3.9` if Poetry uses the wrong Python version.
- **Missing LaTeX**: If LaTeX documents fail to generate, install a LaTeX distribution like TeX Live.
- **GUI issues**: Verify that `PyQt6` is installed correctly. Check for Qt-related errors in the terminal output.

For further help, check the [Development](development.md) section or file an issue on the repository.

