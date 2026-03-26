"""Tests for the CLI commands."""

import pytest
from click.testing import CliRunner
from vecdb.cli import cli
import shutil
import os
from unittest.mock import MagicMock


@pytest.fixture
def temp_dir():
    temp_path = "tests/temp_dir"
    os.makedirs(temp_path, exist_ok=True)
    yield temp_path
    shutil.rmtree(temp_path)


@pytest.fixture
def mock_db(monkeypatch):
    mock_client = MagicMock()
    monkeypatch.setattr("vecdb.core.db.get_client", lambda *args: mock_client)
    monkeypatch.setattr("vecdb.core.db.create_collection", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "vecdb.core.db.query_collection",
        lambda *args, **kwargs: {
            "ids": [["id1"]],
            "documents": [["Sample document"]],
            "distances": [[0.1234]],
        },
    )
    monkeypatch.setattr("vecdb.core.db.bulk_add_documents", lambda *args, **kwargs: None)


def test_init_command(temp_dir, mock_db):
    """Test initializing a collection."""
    runner = CliRunner()
    result = runner.invoke(cli, ["init", "-d", temp_dir, "-c", "test_collection"])
    assert result.exit_code == 0
    assert "Collection 'test_collection' created" in result.output


def test_query_command(temp_dir, mock_db):
    """Test querying a collection."""
    runner = CliRunner()
    result = runner.invoke(
        cli, ["query", "-d", temp_dir, "-c", "test_collection", "-q", "test query", "-n", 1]
    )
    assert result.exit_code == 0
    assert "Top Query Results" in result.output


def test_add_command(temp_dir, mock_db):
    """Test adding documents."""
    runner = CliRunner()
    # Create a dummy .tex file
    dummy_dir = os.path.join(temp_dir, "dummy")
    os.makedirs(dummy_dir, exist_ok=True)
    file_path = os.path.join(dummy_dir, "label.tex")
    with open(file_path, "w") as f:
        f.write("\\begin{document}\nTest content\n\\end{document}")
    result = runner.invoke(
        cli, ["add", "-d", temp_dir, "-c", "test_collection", "-t", temp_dir]
    )
    assert result.exit_code == 0
    assert "Added 1 snippets" in result.output
