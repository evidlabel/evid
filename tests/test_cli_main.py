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


@patch("evid.cli.main.gui_main")
def test_main_no_args(mock_gui, mock_directory):
    with patch.object(sys, "argv", ["evid"]):
        main()
    mock_gui.assert_called_once_with(mock_directory)


@patch("evid.cli.main.list_datasets")
def test_set_list(mock_list, mock_directory):
    with patch.object(sys, "argv", ["evid", "set", "list"]):
        main()
    mock_list.assert_called_once_with(mock_directory)


@patch("evid.cli.main.create_dataset")
def test_set_create(mock_create, mock_directory):
    with patch.object(sys, "argv", ["evid", "set", "create", "--dataset", "new_ds"]):
        main()
    mock_create.assert_called_once_with(mock_directory, "new_ds")


@patch("evid.cli.main.add_evidence")
def test_set_add(mock_add, mock_directory):
    (mock_directory / "test_ds").mkdir(exist_ok=True)
    with patch.object(
        sys, "argv", ["evid", "set", "add", "source.pdf", "--dataset", "test_ds"]
    ):
        main()
    mock_add.assert_called_once_with(
        mock_directory, "test_ds", "source.pdf", None, None
    )


@patch("evid.cli.main.generate_bibtex")
def test_doc_bibtex(mock_bibtex, mock_directory):
    dataset = "test_ds"
    uuid = "uuid"
    typ_file = mock_directory / dataset / uuid / "label.typ"
    typ_file.parent.mkdir(parents=True, exist_ok=True)
    typ_file.touch()
    with patch("evid.cli.main.select_dataset", return_value=dataset):
        with patch("evid.cli.main.select_evidence", return_value=uuid):
            with patch.object(sys, "argv", ["evid", "doc", "bibtex"]):
                main()
    mock_bibtex.assert_called_once_with([typ_file])


@patch("evid.cli.main.label_evidence")
def test_doc_label(mock_label, mock_directory):
    dataset = "test_ds"
    (mock_directory / dataset).mkdir(exist_ok=True)
    with patch("evid.cli.main.select_dataset", return_value=dataset):
        with patch.object(sys, "argv", ["evid", "doc", "label"]):
            main()
    mock_label.assert_called_once_with(mock_directory, dataset, None)


@patch("evid.cli.main.rebut_doc")
def test_doc_rebut(mock_rebut, mock_directory):
    dataset = "test_ds"
    uuid = "uuid"
    workdir = mock_directory / dataset / uuid
    workdir.mkdir(parents=True, exist_ok=True)
    with patch("evid.cli.main.select_dataset", return_value=dataset):
        with patch("evid.cli.main.select_evidence", return_value=uuid):
            with patch.object(sys, "argv", ["evid", "doc", "rebut"]):
                main()
    mock_rebut.assert_called_once_with(workdir)


@patch("evid.cli.main.get_evidence_list")
def test_doc_list(mock_list_docs, mock_directory):
    dataset = "test_ds"
    (mock_directory / dataset).mkdir(exist_ok=True)
    mock_list_docs.return_value = [
        {"date": "2023-01-01", "uuid": "uuid", "title": "Test"}
    ]
    with patch("evid.cli.main.select_dataset", return_value=dataset):
        with patch.object(sys, "argv", ["evid", "doc", "list"]):
            main()
    mock_list_docs.assert_called_once_with(mock_directory, dataset)


@patch("evid.cli.main.gui_main")
def test_gui(mock_gui, mock_directory):
    with patch.object(sys, "argv", ["evid", "gui"]):
        main()
    mock_gui.assert_called_once_with(mock_directory)


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
