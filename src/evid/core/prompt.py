"""Prompt generation utilities."""

import json
import logging
from pathlib import Path

import yaml
from PySide6.QtWidgets import QApplication

from evid.core.models import InfoModel

logger = logging.getLogger(__name__)


def create_prompt(uuids, dataset, directory):
    """Generate a concatenated Markdown prompt from selected evidence UUIDs."""
    if not uuids:
        logger.warning("No entries selected for prompt.")
        return

    markdown_parts = []
    for uuid in uuids:
        workdir = directory / dataset / uuid
        json_file = workdir / "label.json"
        info_file = workdir / "info.yml"

        if not json_file.exists():
            logger.warning("No label.json for %s — skipping.", uuid)
            continue

        try:
            with info_file.open("r", encoding="utf-8") as f:
                info = yaml.safe_load(f)
            validated_info = InfoModel(**info)
            info = validated_info.model_dump()
        except Exception as e:
            logger.error("Failed to load info for %s: %s", uuid, e)
            continue

        title = info.get("title", "Unknown")
        authors = info.get("authors", "Unknown")
        url = info.get("url", "")
        pdf_path_full = str(workdir / info.get("original_name", ""))
        home = str(Path.home())
        pdf_path = pdf_path_full.replace(home, "HOME", 1) if pdf_path_full.startswith(home) else pdf_path_full

        try:
            with json_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error("Failed to load JSON for %s: %s", uuid, e)
            continue

        chapter = f"# {title}\n\n"
        chapter += f"**Author:** {authors}\n\n"
        if url:
            chapter += f"**Link:** {url}\n\n"
        chapter += f"**PDF:** {pdf_path}\n\n"

        labels = [
            item["value"] for item in data if item["value"].get("key") != "main"
        ]
        for label in labels:
            opage = label.get("opage", "")
            text = label.get("text", "")
            note = label.get("note", "")
            content = note if note else text
            chapter += f"- Page {opage}: {content.replace(chr(10), chr(10) + '  ')}\n"

        markdown_parts.append(chapter)

    if not markdown_parts:
        logger.warning("No labelled entries found — nothing to copy.")
        return

    QApplication.clipboard().setText("\n\n".join(markdown_parts))
    logger.info("Prompt copied to clipboard (%d entries).", len(markdown_parts))
