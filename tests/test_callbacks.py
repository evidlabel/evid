"""Test callback functions."""

import pytest
from unittest.mock import patch
import os


def test_create_callback(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    with patch("evid.cli.callbacks.create_dataset") as mock_create:
        from evid.cli.callbacks import create_callback

        create_callback(dataset="test_ds")
        mock_create.assert_called_once_with(tmp_path, "test_ds")


def test_track_callback(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    with patch(
        "evid.cli.callbacks.select_dataset", return_value="selected_ds"
    ) as mock_select:
        with patch("evid.cli.callbacks.track_dataset") as mock_track:
            from evid.cli.callbacks import track_callback

            track_callback(dataset=None)
            mock_select.assert_called_once_with(tmp_path, "Select dataset to track")
            mock_track.assert_called_once_with(tmp_path, "selected_ds")


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
    ) as mock_select:
        with patch("evid.cli.callbacks.add_evidence") as mock_add:
            from evid.cli.callbacks import add_callback

            add_callback(source="source.pdf", dataset=None)
            mock_select.assert_called_once_with(
                tmp_path, "Select dataset for adding document"
            )
            mock_add.assert_called_once_with(
                tmp_path, "selected_ds", "source.pdf", False, False
            )


@pytest.mark.skipif(
    os.environ.get("HEADLESS") == "1"
    or os.environ.get("QT_QPA_PLATFORM") == "offscreen",
    reason="Skipped in headless mode",
)
def test_bibtex_callback(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    typ_file = tmp_path / "selected_ds" / "uuid1" / "label.typ"
    typ_file.parent.mkdir(parents=True, exist_ok=True)
    typ_file.touch()
    with patch(
        "evid.cli.callbacks.select_dataset", return_value="selected_ds"
    ) as mock_select:
        with patch(
            "evid.cli.callbacks.select_evidence", return_value="uuid1"
        ) as mock_evidence:
            with patch("evid.cli.callbacks.generate_bibtex") as mock_bibtex:
                from evid.cli.callbacks import bibtex_callback

                bibtex_callback(dataset=None, uuid=None)
                mock_select.assert_called_once_with(
                    tmp_path, "Select dataset for BibTeX generation", allow_create=False
                )
                mock_evidence.assert_called_once_with(tmp_path, "selected_ds")
                mock_bibtex.assert_called_once()


@pytest.mark.skipif(
    os.environ.get("HEADLESS") == "1"
    or os.environ.get("QT_QPA_PLATFORM") == "offscreen",
    reason="Skipped in headless mode",
)
def test_gui_callback(tmp_path):
    import evid.cli.callbacks

    evid.cli.callbacks.DIRECTORY = tmp_path
    from evid.cli.callbacks import gui_callback

    with pytest.raises(SystemExit):
        gui_callback()
