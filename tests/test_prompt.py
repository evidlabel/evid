"""Tests for evid.core.prompt."""

import json
from pathlib import Path

import yaml

from evid.core.prompt import labels_to_yaml, quotes_markdown, quotes_yaml


def _make_doc(
    base: Path,
    dataset: str,
    uuid: str,
    *,
    title: str = "Sample Title",
    authors: str = "Alice",
    url: str = "https://example.com/doc",
    original_name: str = "doc.pdf",
    labels: list[dict] | None = None,
) -> Path:
    workdir = base / dataset / "docs" / uuid
    workdir.mkdir(parents=True)
    info = {
        "uuid": uuid,
        "original_name": original_name,
        "title": title,
        "authors": authors,
        "url": url,
        "tags": "",
        "label": title,
    }
    (workdir / "info.yml").write_text(yaml.safe_dump(info), encoding="utf-8")
    label_items = (
        [{"value": {"key": "q1", "opage": 3, "text": "Quoted passage.", "note": ""}}]
        if labels is None
        else labels
    )
    (workdir / "label.json").write_text(json.dumps(label_items), encoding="utf-8")
    return workdir


def test_quotes_markdown_includes_dataset_and_uuid(tmp_path: Path) -> None:
    dataset = "case_alpha"
    uuid = "abc-123"
    workdir = _make_doc(tmp_path, dataset, uuid)

    md = quotes_markdown([workdir])

    assert "# Sample Title" in md
    assert f"**Dataset:** {dataset}" in md
    assert f"**UUID:** {uuid}" in md
    assert "**Author:** Alice" in md
    assert "**Link:** https://example.com/doc" in md
    assert "- Page 3: Quoted passage." in md


def test_quotes_markdown_omits_local_path_and_pdf_line(tmp_path: Path) -> None:
    workdir = _make_doc(tmp_path, "case_beta", "uuid-xyz")

    md = quotes_markdown([workdir])

    assert "**PDF:**" not in md
    assert "HOME" not in md
    assert str(tmp_path) not in md
    assert "doc.pdf" not in md


def test_quotes_markdown_handles_legacy_layout(tmp_path: Path) -> None:
    # Legacy CLI layout: {db}/{dataset}/{uuid}/  (no intermediate "docs" dir)
    dataset = "legacy_set"
    uuid = "legacy-uuid"
    workdir = tmp_path / dataset / uuid
    workdir.mkdir(parents=True)
    info = {
        "uuid": uuid,
        "original_name": "legacy.pdf",
        "title": "Legacy Doc",
        "authors": "Bob",
        "url": "",
        "tags": "",
        "label": "Legacy Doc",
    }
    (workdir / "info.yml").write_text(yaml.safe_dump(info), encoding="utf-8")
    (workdir / "label.json").write_text(
        json.dumps([{"value": {"key": "q1", "opage": 1, "text": "hi", "note": ""}}]),
        encoding="utf-8",
    )

    md = quotes_markdown([workdir])

    assert f"**Dataset:** {dataset}" in md
    assert f"**UUID:** {uuid}" in md


def test_quotes_markdown_uses_quote_text_not_note(tmp_path: Path) -> None:
    workdir = _make_doc(
        tmp_path,
        "case_delta",
        "uuid-note",
        labels=[
            {
                "value": {
                    "key": "q1",
                    "opage": 5,
                    "text": "The actual quote.",
                    "note": "Editorial note.",
                }
            }
        ],
    )

    md = quotes_markdown([workdir])

    assert "- Page 5: The actual quote." in md
    assert "Editorial note." not in md


def test_quotes_markdown_empty_when_no_label_json(tmp_path: Path) -> None:
    workdir = tmp_path / "case_gamma" / "docs" / "uuid-empty"
    workdir.mkdir(parents=True)
    (workdir / "info.yml").write_text(
        yaml.safe_dump(
            {
                "uuid": "uuid-empty",
                "original_name": "x.pdf",
                "title": "X",
                "authors": "Y",
                "label": "X",
            }
        ),
        encoding="utf-8",
    )
    # No label.json — unlabelled doc is skipped entirely.
    assert quotes_markdown([workdir]) == ""
    assert quotes_yaml([workdir]) == ""


def test_labels_to_yaml_roundtrip() -> None:
    out = labels_to_yaml(
        [
            (
                "c827520ead3c68c549e89e452884abcd",
                [
                    (
                        "principper",
                        {
                            "text": "Børnesyn består af",
                            "note": "vigtig",
                            "opage": 5,
                            "title": "Børnesyn",
                        },
                    ),
                    ("fleremekanisk", {"text": "flere mekanismer"}),
                ],
            )
        ]
    )
    data = yaml.safe_load(out)
    assert data["uuid"] == "c827520ead3c68c549e89e452884abcd"
    assert set(data["labels"]) == {"principper", "fleremekanisk"}
    assert data["labels"]["principper"] == {
        "text": "Børnesyn består af",
        "note": "vigtig",
        "page": 5,
        "section": "Børnesyn",
    }
    assert data["labels"]["fleremekanisk"] == {"text": "flere mekanismer"}


def test_quotes_yaml_single_doc_is_mapping(tmp_path: Path) -> None:
    workdir = _make_doc(tmp_path, "case_yaml", "uuid-yaml-1")

    data = yaml.safe_load(quotes_yaml([workdir]))

    assert data["uuid"] == "uuid-yaml-1"
    assert data["labels"]["q1"] == {"text": "Quoted passage.", "page": 3}


def test_quotes_yaml_multi_doc_is_list_with_uuid_once_each(tmp_path: Path) -> None:
    wd1 = _make_doc(tmp_path, "case_yaml2", "uuid-a")
    wd2 = _make_doc(
        tmp_path,
        "case_yaml2",
        "uuid-b",
        labels=[
            {"value": {"key": "main", "text": "skipped"}},
            {"value": {"key": "k2", "opage": 7, "text": "Second doc quote."}},
        ],
    )

    data = yaml.safe_load(quotes_yaml([wd1, wd2]))

    assert isinstance(data, list)
    assert [d["uuid"] for d in data] == ["uuid-a", "uuid-b"]
    assert data[1]["labels"] == {"k2": {"text": "Second doc quote.", "page": 7}}
