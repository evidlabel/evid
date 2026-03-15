"""Prompt generation utilities."""

import json
import logging
from pathlib import Path
import yaml
from PySide6.QtWidgets import QMessageBox, QApplication
from evid.core.bibtex import generate_bib_from_typ
from evid.core.models import InfoModel

logger = logging.getLogger(__name__)


def create_prompt(uuids, dataset, directory):
    """Generate a concatenated Markdown prompt from selected evidence UUIDs."""
    if not uuids:
        QMessageBox.warning(
            None, "No Selection", "Please select at least one evidence entry."
        )
        return

    markdown_parts = []
    for uuid in uuids:
        workdir = directory / dataset / uuid
        typ_file = workdir / "label.typ"
        json_file = workdir / "label.json"
        info_file = workdir / "info.yml"

        # Ensure JSON exists by generating BibTeX if needed
        if not json_file.exists():
            success, msg = generate_bib_from_typ(typ_file)
            if not success:
                logger.error(msg)
                QMessageBox.critical(
                    None,
                    "Prompt Generation Error",
                    f"Failed to generate data for {uuid}: {msg}",
                )
                continue

        # Load info.yml
        try:
            with info_file.open("r", encoding="utf-8") as f:
                info = yaml.safe_load(f)
            validated_info = InfoModel(**info)
            info = validated_info.model_dump()
        except Exception as e:
            logger.error(f"Failed to load info for {uuid}: {e}")
            QMessageBox.critical(
                None,
                "Info Load Error",
                f"Failed to load metadata for {uuid}: {str(e)}",
            )
            continue

        title = info.get("title", "Unknown")
        authors = info.get("authors", "Unknown")
        url = info.get("url", "")
        pdf_path_full = str(workdir / info.get("original_name", ""))
        # Replace home directory with 'HOME' for privacy
        home = str(Path.home())
        if pdf_path_full.startswith(home):
            pdf_path = pdf_path_full.replace(home, "HOME", 1)
        else:
            pdf_path = pdf_path_full

        # Load label.json
        try:
            with json_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load JSON for {uuid}: {e}")
            QMessageBox.critical(
                None,
                "JSON Load Error",
                f"Failed to load labels for {uuid}: {str(e)}",
            )
            continue

        # Build Markdown chapter
        chapter = f"# {title}\n\n"
        chapter += f"**Author:** {authors}\n\n"
        if url:
            chapter += f"**Link:** {url}\n\n"
        chapter += f"**PDF:** {pdf_path}\n\n"

        # Extract labels (exclude 'main')
        labels = [
            item["value"] for item in data if item["value"].get("key") != "main"
        ]
        for label in labels:
            opage = label.get("opage", "")
            text = label.get("text", "")
            note = label.get("note", "")
            content = note if note else text
            # Indent multiline content properly for Markdown lists
            indented_content = content.replace("\n", "\n  ")
            chapter += f"- Page {opage}: {indented_content}\n"

        markdown_parts.append(chapter)

    full_markdown = "\n\n".join(markdown_parts)
    # Copy to clipboard
    clipboard = QApplication.clipboard()
    clipboard.setText(full_markdown)
    QMessageBox.information(
        None,
        "Prompt Generated",
        "Markdown prompt copied to clipboard.",
    )