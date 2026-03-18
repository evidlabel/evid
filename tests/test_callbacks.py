"""Test callback functions."""

import os
from unittest.mock import patch

import pytest


def test_create_callback(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    with patch("evid.cli.callbacks.create_dataset") as mock_create:
        from evid.cli.callbacks import create_callback

        create_callback(dataset="test_ds")
        mock_create.assert_called_once_with(tmp_path, "test_ds")


def test_create_callback_prompts_input(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    with patch("evid.cli.callbacks.create_dataset") as mock_create:
        with patch("builtins.input", return_value="prompted_ds"):
            from evid.cli.callbacks import create_callback

            create_callback(dataset=None)
            mock_create.assert_called_once_with(tmp_path, "prompted_ds")


def test_create_callback_empty_input_exits(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    with patch("builtins.input", return_value=""):
        from evid.cli.callbacks import create_callback

        with pytest.raises(SystemExit):
            create_callback(dataset=None)


def test_track_callback(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    with patch(
        "evid.cli.callbacks.select_dataset", return_value="selected_ds"
    ) as mock_select, patch("evid.cli.callbacks.track_dataset") as mock_track:
        from evid.cli.callbacks import track_callback

        track_callback(dataset=None)
        mock_select.assert_called_once_with(tmp_path, "Select dataset to track")
        mock_track.assert_called_once_with(tmp_path, "selected_ds")


def test_track_callback_digit_dataset(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    with patch("evid.cli.callbacks.track_dataset") as mock_track:
        with patch("evid.cli.callbacks.get_datasets", return_value=["alpha", "beta"]):
            from evid.cli.callbacks import track_callback

            track_callback(dataset="1")
            mock_track.assert_called_once_with(tmp_path, "alpha")


def test_track_callback_digit_out_of_range(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    with patch("evid.cli.callbacks.get_datasets", return_value=["alpha"]):
        from evid.cli.callbacks import track_callback

        with pytest.raises(SystemExit):
            track_callback(dataset="99")


def test_list_datasets_callback(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    with patch("evid.cli.callbacks.list_datasets") as mock_list:
        from evid.cli.callbacks import list_datasets_callback

        list_datasets_callback()
        mock_list.assert_called_once_with(tmp_path)


def test_add_callback(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    with patch(
        "evid.cli.callbacks.select_dataset", return_value="selected_ds"
    ) as mock_select, patch("evid.cli.callbacks.add_evidence") as mock_add:
        from evid.cli.callbacks import add_callback

        add_callback(source="source.pdf", dataset=None)
        mock_select.assert_called_once_with(
            tmp_path, "Select dataset for adding document"
        )
        mock_add.assert_called_once_with(
            tmp_path, "selected_ds", "source.pdf", False, False
        )


def test_add_callback_digit_dataset(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    ds_path = tmp_path / "alpha"
    ds_path.mkdir()
    with patch("evid.cli.callbacks.get_datasets", return_value=["alpha", "beta"]):
        with patch("evid.cli.callbacks.add_evidence") as mock_add:
            from evid.cli.callbacks import add_callback

            add_callback(source="source.pdf", dataset="1")
            mock_add.assert_called_once_with(
                tmp_path, "alpha", "source.pdf", False, False
            )


def test_add_callback_digit_out_of_range(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    with patch("evid.cli.callbacks.get_datasets", return_value=["alpha"]):
        from evid.cli.callbacks import add_callback

        with pytest.raises(SystemExit):
            add_callback(source="source.pdf", dataset="99")


def test_add_callback_named_dataset_not_exists(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    from evid.cli.callbacks import add_callback

    with pytest.raises(SystemExit):
        add_callback(source="source.pdf", dataset="nonexistent")


def test_add_callback_named_dataset_exists(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    (tmp_path / "myds").mkdir()
    with patch("evid.cli.callbacks.add_evidence") as mock_add:
        from evid.cli.callbacks import add_callback

        add_callback(source="source.pdf", dataset="myds")
        mock_add.assert_called_once_with(tmp_path, "myds", "source.pdf", False, False)


def test_bibtex_callback_dataset_and_uuid(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    typ_file = tmp_path / "ds" / "uuid1" / "label.typ"
    typ_file.parent.mkdir(parents=True)
    typ_file.touch()
    with patch("evid.cli.callbacks.generate_bibtex") as mock_bib:
        from evid.cli.callbacks import bibtex_callback

        bibtex_callback(dataset="ds", uuid="uuid1")
        mock_bib.assert_called_once_with([typ_file])


def test_bibtex_callback_missing_typ(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    from evid.cli.callbacks import bibtex_callback

    with pytest.raises(SystemExit):
        bibtex_callback(dataset="ds", uuid="uuid1")


def test_bibtex_callback_selects_dataset_and_uuid(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    typ_file = tmp_path / "selected_ds" / "uuid1" / "label.typ"
    typ_file.parent.mkdir(parents=True)
    typ_file.touch()
    with patch("evid.cli.callbacks.select_dataset", return_value="selected_ds"):
        with patch("evid.cli.callbacks.select_evidence", return_value="uuid1"):
            with patch("evid.cli.callbacks.generate_bibtex") as mock_bib:
                from evid.cli.callbacks import bibtex_callback

                bibtex_callback(dataset=None, uuid=None)
                mock_bib.assert_called_once()


def test_label_callback_valid(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    (tmp_path / "myds").mkdir()
    with patch("evid.cli.callbacks.label_evidence") as mock_label:
        from evid.cli.callbacks import label_callback

        label_callback(dataset="myds", uuid="uuid1")
        mock_label.assert_called_once_with(tmp_path, "myds", "uuid1", "label.typ")


def test_label_callback_digit_dataset(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    (tmp_path / "alpha").mkdir()
    with patch("evid.cli.callbacks.get_datasets", return_value=["alpha"]):
        with patch("evid.cli.callbacks.label_evidence") as mock_label:
            from evid.cli.callbacks import label_callback

            label_callback(dataset="1", uuid="uuid1")
            mock_label.assert_called_once_with(tmp_path, "alpha", "uuid1", "label.typ")


def test_label_callback_digit_out_of_range(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    with patch("evid.cli.callbacks.get_datasets", return_value=["alpha"]):
        from evid.cli.callbacks import label_callback

        with pytest.raises(SystemExit):
            label_callback(dataset="99", uuid="uuid1")


def test_label_callback_nonexistent_dataset(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    from evid.cli.callbacks import label_callback

    with pytest.raises(SystemExit):
        label_callback(dataset="nonexistent", uuid="uuid1")


def test_label_callback_selects_dataset(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    (tmp_path / "selected_ds").mkdir()
    with patch("evid.cli.callbacks.select_dataset", return_value="selected_ds"):
        with patch("evid.cli.callbacks.label_evidence") as mock_label:
            from evid.cli.callbacks import label_callback

            label_callback(dataset=None, uuid="uuid1")
            mock_label.assert_called_once()


def test_rebut_callback_valid(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    (tmp_path / "myds" / "uuid1").mkdir(parents=True)
    with patch("evid.cli.callbacks.rebut_doc") as mock_rebut:
        from evid.cli.callbacks import rebut_callback

        rebut_callback(dataset="myds", uuid="uuid1")
        mock_rebut.assert_called_once_with(tmp_path / "myds" / "uuid1")


def test_rebut_callback_digit_dataset(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    (tmp_path / "alpha" / "uuid1").mkdir(parents=True)
    with patch("evid.cli.callbacks.get_datasets", return_value=["alpha"]):
        with patch("evid.cli.callbacks.rebut_doc") as mock_rebut:
            from evid.cli.callbacks import rebut_callback

            rebut_callback(dataset="1", uuid="uuid1")
            mock_rebut.assert_called_once()


def test_rebut_callback_nonexistent_dataset(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    from evid.cli.callbacks import rebut_callback

    with pytest.raises(SystemExit):
        rebut_callback(dataset="nonexistent", uuid="uuid1")


def test_rebut_callback_nonexistent_workdir(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    (tmp_path / "myds").mkdir()
    from evid.cli.callbacks import rebut_callback

    with pytest.raises(SystemExit):
        rebut_callback(dataset="myds", uuid="missing_uuid")


def test_rebut_callback_selects_both(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    (tmp_path / "ds" / "uuid1").mkdir(parents=True)
    with patch("evid.cli.callbacks.select_dataset", return_value="ds"):
        with patch("evid.cli.callbacks.select_evidence", return_value="uuid1"):
            with patch("evid.cli.callbacks.rebut_doc") as mock_rebut:
                from evid.cli.callbacks import rebut_callback

                rebut_callback(dataset=None, uuid=None)
                mock_rebut.assert_called_once()


def test_rebut_callback_exception(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    (tmp_path / "myds" / "uuid1").mkdir(parents=True)
    with patch("evid.cli.callbacks.rebut_doc", side_effect=Exception("oops")):
        from evid.cli.callbacks import rebut_callback

        with pytest.raises(SystemExit):
            rebut_callback(dataset="myds", uuid="uuid1")


def test_list_docs_callback_valid(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    (tmp_path / "myds").mkdir()
    docs = [{"date": "2023-01-01", "uuid": "uuid1", "title": "Test"}]
    with patch("evid.cli.callbacks.get_evidence_list", return_value=docs):
        with patch("evid.cli.callbacks.Console") as mock_console:
            from evid.cli.callbacks import list_docs_callback

            list_docs_callback(dataset="myds")
            mock_console.return_value.print.assert_called_once()


def test_list_docs_callback_no_docs(tmp_path, capsys):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    (tmp_path / "myds").mkdir()
    with patch("evid.cli.callbacks.get_evidence_list", return_value=[]):
        from evid.cli.callbacks import list_docs_callback

        list_docs_callback(dataset="myds")
        assert "No documents found." in capsys.readouterr().out


def test_list_docs_callback_specific_uuid(tmp_path, capsys):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    (tmp_path / "myds").mkdir()
    from evid.cli.callbacks import list_docs_callback

    list_docs_callback(dataset="myds", uuid="uuid1")
    assert "uuid1" in capsys.readouterr().out


def test_list_docs_callback_nonexistent_dataset(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    from evid.cli.callbacks import list_docs_callback

    with pytest.raises(SystemExit):
        list_docs_callback(dataset="nonexistent")


def test_list_docs_callback_digit_out_of_range(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    with patch("evid.cli.callbacks.get_datasets", return_value=["alpha"]):
        from evid.cli.callbacks import list_docs_callback

        with pytest.raises(SystemExit):
            list_docs_callback(dataset="99")


def test_update_callback_no_file(tmp_path):
    from evid.cli.callbacks import update_callback

    config_path = tmp_path / ".evidrc"
    with patch("evid.cli.callbacks.Path.home", return_value=tmp_path):
        update_callback()
        assert config_path.exists()


def test_update_callback_existing_valid_file(tmp_path):
    import yaml

    from evid.cli.callbacks import update_callback

    config_path = tmp_path / ".evidrc"
    config_path.write_text(yaml.dump({"editor": "vim"}))
    with patch("evid.cli.callbacks.Path.home", return_value=tmp_path):
        update_callback()
        with config_path.open() as f:
            result = yaml.safe_load(f)
        assert result["editor"] == "vim"


def test_update_callback_invalid_yaml(tmp_path, capsys):
    from evid.cli.callbacks import update_callback

    config_path = tmp_path / ".evidrc"
    config_path.write_text(": invalid: yaml: [")
    with patch("evid.cli.callbacks.Path.home", return_value=tmp_path):
        update_callback()
        assert config_path.exists()


def test_show_callback_no_file(tmp_path, capsys):
    from evid.cli.callbacks import show_callback

    with patch("evid.cli.callbacks.Path.home", return_value=tmp_path):
        show_callback()
        out = capsys.readouterr().out
        assert "Not found" in out


def test_show_callback_with_override(tmp_path, capsys):
    import yaml

    from evid.cli.callbacks import show_callback

    config_path = tmp_path / ".evidrc"
    config_path.write_text(yaml.dump({"editor": "vim"}))
    with patch("evid.cli.callbacks.Path.home", return_value=tmp_path):
        show_callback()
        out = capsys.readouterr().out
        assert "vim" in out


def test_show_callback_invalid_yaml(tmp_path, capsys):
    from evid.cli.callbacks import show_callback

    config_path = tmp_path / ".evidrc"
    config_path.write_text(": invalid: yaml: [")
    with patch("evid.cli.callbacks.Path.home", return_value=tmp_path):
        show_callback()
        out = capsys.readouterr().out
        assert "Invalid" in out or "default" in out


@pytest.mark.skipif(
    os.environ.get("HEADLESS") == "1"
    or os.environ.get("QT_QPA_PLATFORM") == "offscreen"
    or os.environ.get("CI") == "true",
    reason="Skipped in headless or CI mode",
)
def test_bibtex_callback(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    typ_file = tmp_path / "selected_ds" / "uuid1" / "label.typ"
    typ_file.parent.mkdir(parents=True, exist_ok=True)
    typ_file.touch()
    with patch(
        "evid.cli.callbacks.select_dataset", return_value="selected_ds"
    ) as mock_select, patch(
        "evid.cli.callbacks.select_evidence", return_value="uuid1"
    ) as mock_evidence, patch("evid.cli.callbacks.generate_bibtex") as mock_bibtex:
        from evid.cli.callbacks import bibtex_callback

        bibtex_callback(dataset=None, uuid=None)
        mock_select.assert_called_once_with(
            tmp_path, "Select dataset for BibTeX generation", allow_create=False
        )
        mock_evidence.assert_called_once_with(tmp_path, "selected_ds")
        mock_bibtex.assert_called_once()


@pytest.mark.skipif(
    os.environ.get("HEADLESS") == "1"
    or os.environ.get("QT_QPA_PLATFORM") == "offscreen"
    or os.environ.get("CI") == "true",
    reason="Skipped in headless or CI mode",
)
def test_gui_callback(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    from evid.cli.callbacks import gui_callback

    with pytest.raises(SystemExit):
        gui_callback()
