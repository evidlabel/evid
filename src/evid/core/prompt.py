"""Prompt generation utilities."""

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from evid.models import InfoModel

logger = logging.getLogger(__name__)

_HEADER_KEYS = ("title", "authors", "url")


class _Literal(str):
    """String emitted as a YAML literal block scalar (``|`` / ``|-``)."""

    __slots__ = ()


class _LabelsDumper(yaml.SafeDumper):
    """SafeDumper with a representer for verbatim quote blocks."""


def _represent_literal(dumper: yaml.SafeDumper, data: str):
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style="|")


_LabelsDumper.add_representer(_Literal, _represent_literal)


def _quote_scalar(value: object) -> str | _Literal:
    text = str(value)
    return _Literal(text) if "\n" in text else text


def _load_info(workdir: Path) -> dict | None:
    """Load and validate info.yml for a doc workdir. None if unreadable."""
    info_file = workdir / "info.yml"
    try:
        with info_file.open("r", encoding="utf-8") as f:
            info = yaml.safe_load(f)
        return InfoModel(**info).model_dump()
    except (OSError, yaml.YAMLError, TypeError, ValueError):
        logger.exception("Failed to load info for %s", workdir)
        return None


def _info_header(workdir: Path) -> dict[str, str]:
    """title / authors / url from info.yml; omits empty fields."""
    info = _load_info(workdir)
    if not info:
        return {}
    header: dict[str, str] = {}
    for key in _HEADER_KEYS:
        val = info.get(key) or ""
        if isinstance(val, list):
            val = ", ".join(str(x) for x in val)
        val = str(val).strip()
        if val:
            header[key] = val
    return header


def _doc_ref(ref: str | Mapping[str, Any]) -> tuple[str, dict[str, str]]:
    """Split a labels_to_yaml doc ref into (uuid, header fields)."""
    if isinstance(ref, str):
        return ref, {}
    uuid = str(ref.get("uuid") or "")
    header: dict[str, str] = {}
    for key in _HEADER_KEYS:
        val = ref.get(key)
        if key == "authors" and not val:
            val = ref.get("author")
        text = str(val).strip() if val else ""
        if text:
            header[key] = text
    return uuid, header


def _doc_chapter(workdir: Path) -> str | None:
    """Build the markdown chapter for one doc workdir, or None if it has no labels."""
    json_file = workdir / "label.json"

    if not json_file.exists():
        logger.debug("No label.json for %s — unlabelled, skipping.", workdir)
        return None

    raw = json_file.read_text(encoding="utf-8").strip()
    if not raw:
        logger.debug("Empty label.json for %s — unlabelled, skipping.", workdir)
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("Malformed label.json for %s: %s", workdir, e)
        return None

    info = _load_info(workdir)
    if info is None:
        return None

    title = info.get("title", "Unknown")
    authors = info.get("authors", "Unknown")
    url = info.get("url", "")
    uuid = info.get("uuid") or workdir.name
    dataset = (
        workdir.parent.parent.name
        if workdir.parent.name == "docs"
        else workdir.parent.name
    )

    chapter = f"# {title}\n\n"
    chapter += f"**Author:** {authors}\n\n"
    if url:
        chapter += f"**Link:** {url}\n\n"
    chapter += f"**Dataset:** {dataset}\n\n"
    chapter += f"**UUID:** {uuid}\n\n"

    labels = [item["value"] for item in data if item["value"].get("key") != "main"]
    for label in labels:
        opage = label.get("opage", "")
        text = label.get("text", "")
        chapter += f"- Page {opage}: {text.replace(chr(10), chr(10) + '  ')}\n"

    return chapter


def label_entries(workdir: Path) -> list[tuple[str, dict]]:
    """Load ``(key, value)`` label pairs from a doc workdir's label.json.

    Skips the ``main`` entry and entries without a key. Returns [] if the doc
    has no (readable) label.json.
    """
    json_file = Path(workdir) / "label.json"
    if not json_file.exists():
        return []
    raw = json_file.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("Malformed label.json for %s: %s", workdir, e)
        return []
    pairs = []
    for item in data:
        val = item.get("value", {}) if isinstance(item, dict) else {}
        key = val.get("key", "")
        if not key or key == "main":
            continue
        pairs.append((key, val))
    return pairs


def labels_to_yaml(
    docs: list[tuple[str | Mapping[str, Any], list[tuple[str, dict]]]],
) -> str:
    """Serialize labelled quotes as YAML, stating each doc's UUID once.

    ``docs`` is a list of ``(ref, items)`` pairs. ``ref`` is the UUID string or
    a mapping with ``uuid`` and optional ``title``, ``authors``, ``url``.
    ``items`` is a list of ``(key, value_dict)`` pairs using the label.json
    field names (``text``, ``note``, ``opage``, ``title``). A single doc yields
    a mapping, several docs a list of mappings. Returns "" if nothing is labelled.
    """
    payload = []
    for ref, items in docs:
        uuid, header = _doc_ref(ref)
        labels: dict[str, dict] = {}
        for key, val in items:
            entry = {}
            if val.get("text"):
                entry["text"] = _quote_scalar(val["text"])
            if val.get("note"):
                entry["note"] = _quote_scalar(val["note"])
            if val.get("opage"):
                entry["page"] = val["opage"]
            if val.get("title"):
                section = str(val["title"]).strip()
                # labtyp copies #mset title (the doc title) onto every label.
                # After the header already states it, repeating it as section
                # is noise — keep only a title that actually differs.
                if section and section != header.get("title"):
                    entry["section"] = section
            labels[key] = entry
        if labels:
            doc: dict[str, Any] = {"uuid": uuid}
            doc.update(header)
            doc["labels"] = labels
            payload.append(doc)
    if not payload:
        return ""
    out = payload[0] if len(payload) == 1 else payload
    return yaml.dump(
        out,
        Dumper=_LabelsDumper,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=2**20,
    )


def quotes_yaml(workdirs) -> str:
    """YAML dump of labelled quotes for a list of doc workdirs.

    Each doc is a mapping with uuid plus title / authors / url from info.yml
    when those fields are set. Returns an empty string if no doc has labels.
    """
    docs = []
    for workdir in workdirs:
        wd = Path(workdir)
        ref: dict[str, str] = {"uuid": wd.name, **_info_header(wd)}
        docs.append((ref, label_entries(wd)))
    return labels_to_yaml(docs)


def quotes_markdown(workdirs) -> str:
    """Concatenate markdown quote-chapters from a list of doc workdirs.

    Returns an empty string if no doc has labels.
    """
    parts = []
    for workdir in workdirs:
        chapter = _doc_chapter(Path(workdir))
        if chapter is not None:
            parts.append(chapter)
    return "\n\n".join(parts)


def create_prompt(uuids, dataset, directory):
    """Build a YAML quote prompt from evidence UUIDs and copy to clipboard."""
    if not uuids:
        logger.warning("No entries selected for prompt.")
        return

    md = quotes_yaml(directory / dataset / uuid for uuid in uuids)
    if not md:
        logger.warning("No labelled entries found — nothing to copy.")
        return

    from PySide6.QtWidgets import QApplication  # noqa: PLC0415, RUF100

    QApplication.clipboard().setText(md)
    logger.info("Prompt copied to clipboard.")
