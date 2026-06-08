"""Tests that `gather` merges machine.hayagriva alongside manual labels."""

import yaml
from evid.core.gather import gather_dataset

MANUAL_BIB = """\
@article{ 1a2b:main ,
  title = {Test Judgment},
  author = {Test Court},
  date = {1978},
  url = {https://example.com/judgment}
}
@article{1a2b:intro,
  title = {a manually labelled snippet},
  pages = {1}
}
"""

MACHINE_HAYAGRIVA = """\
# generated-by: evid vX
1a2b:main:
  type: article
  title: "Test Judgment"
  url: https://example.com/judgment

# verbatim, rapidfuzz-verified
1a2b:q1:
  type: article
  title: |-
    The appeal was therefore dismissed in its entirety.
  url: https://example.com/judgment
  page-range: "2"
  serial-number: "chars 100-150"
"""


def _make_dataset(tmp_path):
    docs = tmp_path / "sets" / "demo" / "docs"
    doc = docs / "1a2b3c4d5e6f"
    doc.mkdir(parents=True)
    info = {"uuid": "1a2b3c4d5e6f", "title": "Test Judgment", "author": "Test Court"}
    (doc / "info.yml").write_text(yaml.safe_dump(info), encoding="utf-8")
    (doc / "label.bib").write_text(MANUAL_BIB, encoding="utf-8")
    (doc / "machine.hayagriva").write_text(MACHINE_HAYAGRIVA, encoding="utf-8")
    return tmp_path


def test_gather_machine_only_dataset(tmp_path):
    """A doc with machine quotes but no manual label.bib still gathers."""
    docs = tmp_path / "sets" / "demo" / "docs"
    doc = docs / "1a2b3c4d5e6f"
    doc.mkdir(parents=True)
    info = {"uuid": "1a2b3c4d5e6f", "title": "Test Judgment"}
    (doc / "info.yml").write_text(yaml.safe_dump(info), encoding="utf-8")
    (doc / "machine.hayagriva").write_text(MACHINE_HAYAGRIVA, encoding="utf-8")

    out = tmp_path / "refs.yml"
    gather_dataset(tmp_path, "demo", out, regen=False)
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert "1a2b:q1" in data
    assert data["1a2b:q1"]["serial-number"] == "chars 100-150"


def test_gather_yaml_merges_machine_with_serial_number(tmp_path):
    root = _make_dataset(tmp_path)
    out = tmp_path / "refs.yml"
    gather_dataset(root, "demo", out, regen=False)
    data = yaml.safe_load(out.read_text(encoding="utf-8"))

    # Manual snippet and machine quote both present; single :main (no duplicate).
    assert "1a2b:intro" in data
    assert "1a2b:q1" in data
    assert sum(1 for k in data if k.endswith(":main")) == 1
    # Machine-only field preserved in the YAML export.
    assert data["1a2b:q1"]["serial-number"] == "chars 100-150"
    assert "dismissed in its entirety" in data["1a2b:q1"]["title"]


def test_gather_bib_includes_machine_quote(tmp_path):
    root = _make_dataset(tmp_path)
    out = tmp_path / "refs.bib"
    gather_dataset(root, "demo", out, regen=False)
    text = out.read_text(encoding="utf-8")
    assert "1a2b:q1" in text
    assert "dismissed in its entirety" in text


def test_gather_md_includes_machine_quote(tmp_path):
    root = _make_dataset(tmp_path)
    out = tmp_path / "refs.md"
    gather_dataset(root, "demo", out, regen=False)
    text = out.read_text(encoding="utf-8")
    assert "dismissed in its entirety" in text
    assert "a manually labelled snippet" in text
