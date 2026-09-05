"""BibTeX utility functions for evid."""

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path

import demoji
import yaml

from evid.models import InfoModel

logger = logging.getLogger(__name__)


def replace_multiple_spaces(s):
    try:
        return re.sub(r" +", " ", s)
    except TypeError:
        return ""


def replace_underscores(s):
    try:
        return re.sub(r"_", " ", s)
    except TypeError:
        return ""


def remove_curly_brace_content(s):
    try:
        return re.sub(r"\{.*?\}", "", s).replace(".06em", "")
    except TypeError:
        return ""


def remove_backslash_substrings(s):
    try:
        return re.sub(r"\\[^ ]*", "", s)
    except TypeError:
        return ""


def emojis_to_text(s):
    # Replace all emojis in the content
    return demoji.replace(s, "(emoji)")


def bib_escape(s: str) -> str:
    """Escape special characters for BibTeX string fields."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def load_uuid_prefix(file_path: Path) -> str:
    info_file = file_path.with_name("info.yml")
    if info_file.exists():
        with info_file.open("r") as info_file:
            info_data = yaml.safe_load(info_file)
            # Validate with Pydantic
            try:
                validated_info = InfoModel(**info_data)
                info_data = validated_info.model_dump()
            except ValueError as e:
                logger.warning(f"Validation error for {info_file}: {e}")
                return ""
            if "uuid" in info_data:
                return info_data["uuid"][:4]
    return ""


def load_url(file_path: Path) -> str:
    info_file = file_path.with_name("info.yml")
    if info_file.exists():
        with info_file.open("r") as info_file:
            info_data = yaml.safe_load(info_file)
            # Validate with Pydantic
            try:
                validated_info = InfoModel(**info_data)
                info_data = validated_info.model_dump()
            except ValueError as e:
                logger.warning(f"Validation error for {info_file}: {e}")
                return ""
            if "url" in info_data:
                return str(info_data["url"])
    return ""


def load_authors(file_path: Path) -> str:
    """Load authors from info.yml."""
    info_file = file_path.with_name("info.yml")
    if info_file.exists():
        with info_file.open("r") as info_file:
            info_data = yaml.safe_load(info_file)
            # Validate with Pydantic
            try:
                validated_info = InfoModel(**info_data)
                info_data = validated_info.model_dump()
            except ValueError as e:
                logger.warning(f"Validation error for {info_file}: {e}")
                return ""
            if "authors" in info_data:
                return str(info_data["authors"])
    return ""


def load_title(file_path: Path) -> str:
    info_file = file_path.with_name("info.yml")
    if info_file.exists():
        with info_file.open("r") as info_file:
            info_data = yaml.safe_load(info_file)
            # Validate with Pydantic
            try:
                validated_info = InfoModel(**info_data)
                info_data = validated_info.model_dump()
            except ValueError as e:
                logger.warning(f"Validation error for {info_file}: {e}")
                return ""
            if "title" in info_data:
                return str(info_data["title"])
    return ""


def load_dates(file_path: Path) -> str:
    info_file = file_path.with_name("info.yml")
    if info_file.exists():
        with info_file.open("r") as info_file:
            info_data = yaml.safe_load(info_file)
            # Validate with Pydantic
            try:
                validated_info = InfoModel(**info_data)
                info_data = validated_info.model_dump()
            except ValueError as e:
                logger.warning(f"Validation error for {info_file}: {e}")
                return ""
            if "dates" in info_data:
                return str(info_data["dates"])
    return ""


def _parse_bib_date(value) -> str:
    """Snippet date as YYYY-MM-DD, or '' if missing/unparseable.

    Accepts ISO dates and a bare year (mapped to YYYY-01-01, matching the old
    pandas to_datetime coerce). Placeholders like ``DATE`` are dropped.
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return ""
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        pass
    if re.fullmatch(r"\d{4}", text):
        return f"{text}-01-01"
    return ""


def _bib_pages(value) -> str:
    if value is None or value == "":
        return ""
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return ""


def json_to_bib(json_file: Path, output_file: Path, exclude_note: bool):
    try:
        with json_file.open() as f:
            data = json.load(f)
        if not data:
            raise ValueError("JSON data is empty")
        rows = [item["value"] for item in data]
        if not rows:
            raise ValueError("JSON data is empty")
        if any("key" not in row for row in rows):
            raise KeyError("'key' column missing in JSON data")
        uuid_prefix = load_uuid_prefix(json_file)
        with output_file.open("w", encoding="utf-8") as bibtex_file:
            # Write main document entry first
            main_lines = [f"@article{{ {uuid_prefix}:main  ,"]
            title_value = replace_underscores(
                replace_multiple_spaces(
                    remove_curly_brace_content(
                        remove_backslash_substrings(load_title(json_file))
                    )
                )
            )
            if title_value:
                main_lines.append(f"    title = {{{title_value}}},")
            author_value = load_authors(json_file)
            if author_value:
                main_lines.append(f"    author = {{{author_value}}},")
            date_value = load_dates(json_file)
            if date_value:
                main_lines.append(f"    date = {{{date_value}}},")
            url_value = load_url(json_file)
            if url_value:
                main_lines.append(f"    url = {{{url_value}}},")
            main_lines.append("    }")
            bibtex_file.write(emojis_to_text("\n".join(main_lines)) + "\n")

            for row in rows:
                label = str(row["key"]).strip()
                entry_lines = [f"@article{{ {uuid_prefix}:{label}  ,"]

                note_value = row.get("note") or ""
                if note_value:
                    note_key = "nonote" if exclude_note else "note"
                    entry_lines.append(f"    {note_key} = {{{note_value}}},")

                quote = row.get("quote") or row.get("text") or ""
                title_value = replace_underscores(
                    replace_multiple_spaces(remove_backslash_substrings(quote))
                )
                if title_value:
                    entry_lines.append(f"    title = {{{title_value}}},")

                journal_value = replace_underscores(
                    replace_multiple_spaces(
                        remove_curly_brace_content(
                            remove_backslash_substrings(row.get("title") or "")
                        )
                    )
                )
                if journal_value and journal_value != "NAME":
                    entry_lines.append(f"    journal = {{{journal_value}}},")

                author_value = load_authors(json_file)
                if author_value:
                    entry_lines.append(f"    author = {{{author_value}}},")

                date_value = _parse_bib_date(row.get("date"))
                if date_value:
                    entry_lines.append(f"    date = {{{date_value}}},")

                pages_value = _bib_pages(row.get("opage"))
                if pages_value:
                    entry_lines.append(f"    pages = {{{pages_value}}},")

                url_value = load_url(json_file)
                if url_value:
                    entry_lines.append(f"    url = {{{url_value}}},")

                entry_lines.append("    }")
                bibtex_file.write(emojis_to_text("\n".join(entry_lines)) + "\n")
    except Exception as e:
        raise ValueError(f"Error processing JSON: {e}") from e
