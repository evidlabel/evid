"""Tests for the vecdb CLI functions."""

from unittest.mock import MagicMock, patch

import pytest
from vecdb.cli import add, init, query


@pytest.fixture
def temp_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture
def mock_client():
    return MagicMock()


def test_init_command(temp_dir, mock_client, capsys):
    with (
        patch("vecdb.cli.get_client", return_value=mock_client),
        patch("vecdb.cli.create_collection") as mock_create,
    ):
        init(directory=temp_dir, collection="test_collection")
        mock_create.assert_called_once()
    assert "test_collection" in capsys.readouterr().out


def test_query_command(temp_dir, mock_client, capsys):
    fake_results = {
        "ids": [["id1"]],
        "documents": [["Sample document"]],
        "distances": [[0.1234]],
        "metadatas": [[{"title": "Doc 1", "url": ""}]],
    }
    with (
        patch("vecdb.cli.get_client", return_value=mock_client),
        patch("vecdb.cli.query_collection", return_value=fake_results),
    ):
        query(
            directory=temp_dir,
            query_text="test query",
            collection="test_collection",
            top_n=1,
        )


def test_add_command(temp_dir, mock_client, capsys):
    with (
        patch("vecdb.cli.get_client", return_value=mock_client),
        patch(
            "vecdb.cli.get_documents_with_metadata",
            return_value=(["doc"], [{}], ["id1"]),
        ),
        patch("vecdb.cli.get_label_files", return_value=["label.typ"]),
        patch("vecdb.cli.bulk_add_documents") as mock_add,
    ):
        add(directory=temp_dir, target_dir=temp_dir, collection="test_collection")
        mock_add.assert_called_once()
    assert "Added" in capsys.readouterr().out
