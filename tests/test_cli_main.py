import pytest
import sys
from unittest.mock import patch
from evid.cli.main import app


def test_main_help(capsys):
    with patch.object(sys, "argv", ["evid", "--help"]):
        with pytest.raises(SystemExit):
            app.run()
    captured = capsys.readouterr()
    assert "evid CLI for managing PDF documents" in captured.out


def test_set_list(capsys):
    with patch.object(sys, "argv", ["evid", "set", "list"]):
        with pytest.raises(SystemExit):
            app.run()
    captured = capsys.readouterr()
    assert "No datasets found." in captured.out


def test_doc_list():
    with patch.object(sys, "argv", ["evid", "doc", "list"]):
        with pytest.raises(SystemExit) as exc:
            app.run()
    assert exc.value.code != 0  # Expect failure without dataset
