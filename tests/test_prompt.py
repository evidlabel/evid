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


def test_labels_to_yaml_includes_title_authors_url() -> None:
    out = labels_to_yaml(
        [
            (
                {
                    "uuid": "abc-123",
                    "title": "The Child Act",
                    "authors": "Parliament",
                    "url": "https://www.retsinformation.dk/eli/lta/2019/123",
                },
                [("k1", {"text": "quoted passage"})],
            )
        ]
    )
    data = yaml.safe_load(out)
    assert data["uuid"] == "abc-123"
    assert data["title"] == "The Child Act"
    assert data["authors"] == "Parliament"
    assert data["url"] == "https://www.retsinformation.dk/eli/lta/2019/123"
    assert data["labels"] == {"k1": {"text": "quoted passage"}}
    dumped = out.split("labels:", 1)[0]
    assert dumped.index("uuid:") < dumped.index("title:") < dumped.index("authors:")
    assert dumped.index("authors:") < dumped.index("url:")


def test_labels_to_yaml_omits_section_when_it_repeats_doc_title() -> None:
    """labtyp copies #mset title onto every label; that is the doc title, not a heading."""
    out = labels_to_yaml(
        [
            (
                {
                    "uuid": "abc-123",
                    "title": "The Child Act",
                    "authors": "Parliament",
                    "url": "https://example.com/x",
                },
                [
                    (
                        "k1",
                        {
                            "text": "quoted passage",
                            "opage": 5,
                            "title": "The Child Act",
                        },
                    ),
                    (
                        "k2",
                        {
                            "text": "another quote",
                            "title": "Børnesyn",
                        },
                    ),
                ],
            )
        ]
    )
    data = yaml.safe_load(out)
    assert data["title"] == "The Child Act"
    assert data["labels"]["k1"] == {"text": "quoted passage", "page": 5}
    assert data["labels"]["k2"] == {"text": "another quote", "section": "Børnesyn"}


def test_quotes_yaml_includes_title_authors_url_from_info(tmp_path: Path) -> None:
    workdir = _make_doc(tmp_path, "case_hdr", "uuid-hdr")

    data = yaml.safe_load(quotes_yaml([workdir]))

    assert data["uuid"] == "uuid-hdr"
    assert data["title"] == "Sample Title"
    assert data["authors"] == "Alice"
    assert data["url"] == "https://example.com/doc"
    assert data["labels"]["q1"] == {"text": "Quoted passage.", "page": 3}


def test_quotes_yaml_omits_empty_url(tmp_path: Path) -> None:
    workdir = _make_doc(tmp_path, "case_nourl", "uuid-nourl", url="")

    data = yaml.safe_load(quotes_yaml([workdir]))

    assert "url" not in data
    assert data["title"] == "Sample Title"
    assert data["authors"] == "Alice"


def test_labels_to_yaml_does_not_wrap_long_quotes() -> None:
    quote = "Børnesyn " + ("principper " * 20)
    assert len(quote) > 80
    out = labels_to_yaml(
        [
            (
                {
                    "uuid": "abc",
                    "title": "Barnets Lov",
                    "authors": "Ministeriet",
                    "url": "https://example.com/x",
                },
                [
                    ("k1", {"text": quote, "opage": 5}),
                    ("k2", {"text": "second selected quote", "opage": 6}),
                ],
            )
        ]
    )
    data = yaml.safe_load(out)
    assert data["labels"]["k1"]["text"] == quote
    assert data["labels"]["k2"]["text"] == "second selected quote"
    assert quote in out


def test_labels_to_yaml_multiline_quotes_are_block_scalars() -> None:
    quote = "line1\nline2\nline3"
    out = labels_to_yaml(
        [
            (
                {"uuid": "abc", "title": "T", "authors": "A"},
                [
                    ("k1", {"text": quote, "opage": 1}),
                    ("k2", {"text": "other", "opage": 2}),
                ],
            )
        ]
    )
    data = yaml.safe_load(out)
    assert data["labels"]["k1"]["text"] == quote
    assert data["labels"]["k2"]["text"] == "other"
    assert "line1\n\n" not in out
