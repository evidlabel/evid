import pytest
from click.testing import CliRunner
from evid.cli.main import main

@pytest.fixture
def runner():
    return CliRunner()

def test_main_help(runner):
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "evid CLI for managing PDF documents" in result.output

def test_set_list(runner):
    result = runner.invoke(main, ["set", "list"])
    assert result.exit_code == 0
    assert "No datasets found." in result.output

def test_doc_list(runner):
    result = runner.invoke(main, ["doc", "list"])
    assert result.exit_code != 0  # Expect failure without dataset
