"""Prompt generation utilities."""

import json
import logging
from pathlib import Path

import yaml

from evid.models import InfoModel

logger = logging.getLogger(__name__)


def _doc_chapter(workdir: Path) -> str | None:
    """Build the markdown chapter for one doc workdir, or None if it has no labels."""
    json_file = workdir / "label.json"
    info_file = workdir / "info.yml"

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

    try:
        with info_file.open("r", encoding="utf-8") as f:
            info = yaml.safe_load(f)
        validated_info = InfoModel(**info)
        info = validated_info.model_dump()
    except (OSError, yaml.YAMLError, ValueError):
        logger.exception("Failed to load info for %s", workdir)
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


def labels_to_yaml(docs: list[tuple[str, list[tuple[str, dict]]]]) -> str:
    """Serialize labelled quotes as YAML, stating each doc's UUID once.

    ``docs`` is a list of ``(uuid, items)`` pairs where ``items`` is a list of
    ``(key, value_dict)`` pairs using the label.json field names (``text``,
    ``note``, ``opage``, ``title``). A single doc yields a mapping, several
    docs a list of mappings. Returns "" if nothing is labelled.
    """
    payload = []
    for uuid, items in docs:
        labels: dict[str, dict] = {}
        for key, val in items:
            entry = {}
            if val.get("text"):
                entry["text"] = val["text"]
            if val.get("note"):
                entry["note"] = val["note"]
            if val.get("opage"):
                entry["page"] = val["opage"]
            if val.get("title"):
                entry["section"] = val["title"]
            labels[key] = entry
        if labels:
            payload.append({"uuid": uuid, "labels": labels})
    if not payload:
        return ""
    out = payload[0] if len(payload) == 1 else payload
    return yaml.safe_dump(out, allow_unicode=True, sort_keys=False)


def quotes_yaml(workdirs) -> str:
    """YAML dump of labelled quotes for a list of doc workdirs.

    Returns an empty string if no doc has labels.
    """
    return labels_to_yaml([(Path(wd).name, label_entries(wd)) for wd in workdirs])


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
