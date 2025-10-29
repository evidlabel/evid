"""Test CLI main functionality."""

import pytest
from unittest.mock import patch
import sys
from evid.cli.main import main
from evid import CONFIG


@pytest.fixture
def mock_directory(tmp_path):
    original_dir = CONFIG["default_dir"]
    CONFIG["default_dir"] = str(tmp_path)
    yield tmp_path
    CONFIG["default_dir"] = original_dir


def test_set_list(mock_directory, capsys):
    with patch.object(sys, "argv", ["evid", "set", "list"]):
        main()
    captured = capsys.readouterr()
    assert "No datasets found." in captured.out


def test_set_create(mock_directory):
    with patch("evid.cli.callbacks.create_dataset") as mock_create:
        with patch.object(
            sys, "argv", ["evid", "set", "create", "--dataset", "new_ds"]
        ):
            main()
        mock_create.assert_called_once_with(mock_directory, "new_ds")


def test_set_add(mock_directory):
    (mock_directory / "test_ds").mkdir(exist_ok=True)
    (mock_directory / "source.pdf").touch()
    with patch("evid.cli.callbacks.add_evidence") as mock_add:
        with patch.object(
            sys, "argv", ["evid", "set", "add", "source.pdf", "--dataset", "test_ds"]
        ):
            main()
        mock_add.assert_called_once_with(
            mock_directory, "test_ds", "source.pdf", None, None
        )


def test_doc_bibtex(mock_directory):
    dataset = "test_ds"
    uuid = "uuid"
    typ_file = mock_directory / dataset / uuid / "label.typ"
    typ_file.parent.mkdir(parents=True, exist_ok=True)
    typ_file.touch()
    with patch("evid.cli.callbacks.generate_bibtex") as mock_bibtex:
        with patch.object(
            sys, "argv", ["evid", "doc", "bibtex", "--dataset", dataset, "--uuid", uuid]
        ):
            main()
        mock_bibtex.assert_called_once_with([typ_file])


def test_doc_label(mock_directory):
    dataset = "test_ds"
    (mock_directory / dataset).mkdir(exist_ok=True)
    with patch("evid.cli.callbacks.label_evidence") as mock_label:
        with patch.object(sys, "argv", ["evid", "doc", "label", "--dataset", dataset]):
            main()
        mock_label.assert_called_once_with(mock_directory, dataset, None, "label.typ")


def test_doc_rebut(mock_directory):
    dataset = "test_ds"
    uuid = "uuid"
    workdir = mock_directory / dataset / uuid
    workdir.mkdir(parents=True, exist_ok=True)
    with patch("evid.cli.callbacks.rebut_doc") as mock_rebut:
        with patch.object(
            sys, "argv", ["evid", "doc", "rebut", "--dataset", dataset, "--uuid", uuid]
        ):
            main()
        mock_rebut.assert_called_once_with(workdir)


def test_doc_list(mock_directory):
    dataset = "test_ds"
    (mock_directory / dataset).mkdir(exist_ok=True)
    with patch("evid.cli.callbacks.get_evidence_list") as mock_list_docs:
        mock_list_docs.return_value = [
            {"date": "2023-01-01", "uuid": "uuid", "title": "Test"}
        ]
        with patch.object(sys, "argv", ["evid", "doc", "list", "--dataset", dataset]):
            main()
        mock_list_docs.assert_called_once_with(mock_directory, dataset)


@patch("yaml.dump")
@patch("yaml.safe_load")
def test_config_update(mock_load, mock_dump, mock_directory):
    mock_load.return_value = {}
    with patch.object(sys, "argv", ["evid", "config", "update"]):
        main()
    mock_dump.assert_called()


@patch("yaml.safe_load")
def test_config_show(mock_load, mock_directory):
    mock_load.return_value = {}
    with patch.object(sys, "argv", ["evid", "config", "show"]):
        main()


def test_db_option(tmp_path):
    """Test using --db option with a custom directory."""
    custom_db = tmp_path / "custom_db"
    custom_db.mkdir()
    with patch("evid.cli.callbacks.create_dataset") as mock_create:
        with patch.object(
            sys,
            "argv",
            ["evid", "--db", str(custom_db), "set", "create", "--dataset", "test_ds"],
        ):
            main()
        mock_create.assert_called_once_with(custom_db, "test_ds")
