"""Prompt generation utilities."""

import json
import logging
from pathlib import Path

import yaml

from evid.core.models import InfoModel

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
    """Build a Markdown prompt from evidence UUIDs and copy to clipboard."""
    if not uuids:
        logger.warning("No entries selected for prompt.")
        return

    md = quotes_markdown(directory / dataset / uuid for uuid in uuids)
    if not md:
        logger.warning("No labelled entries found — nothing to copy.")
        return

    from PySide6.QtWidgets import QApplication  # noqa: PLC0415, RUF100

    QApplication.clipboard().setText(md)
    logger.info("Prompt copied to clipboard.")
