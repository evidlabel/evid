"""BibTeX utility functions for evid."""

from pathlib import Path
import re
import yaml
import pandas as pd
import demoji
import logging
import json
from evid.core.models import InfoModel

logger = logging.getLogger(__name__)


def replace_multiple_spaces(s):
    try:
        return re.sub(r" +", " ", s)
    except TypeError:
        print(s)
        return ""


def replace_underscores(s):
    try:
        return re.sub(r"_", " ", s)
    except TypeError:
        print(s)
        return ""


def remove_curly_brace_content(s):
    try:
        return re.sub(r"\{.*?\}", "", s).replace(".06em", "")
    except TypeError:
        print(s)
        return ""


def remove_backslash_substrings(s):
    try:
        return re.sub(r"\\[^ ]*", "", s)
    except TypeError:
        print(s)
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


def json_to_bib(json_file: Path, output_file: Path, exclude_note: bool):
    try:
        with open(json_file) as f:
            data = json.load(f)
        if not data:
            raise ValueError("JSON data is empty")
        df = pd.DataFrame([item["value"] for item in data])
        if df.empty:
            raise ValueError("DataFrame is empty")
        if "key" not in df.columns:
            raise KeyError("'key' column missing in JSON data")
        df.rename(columns={"key": "label", "text": "quote"}, inplace=True)
        df["date"] = pd.to_datetime(
            df.get("date", pd.Series([pd.NaT] * len(df))),
            dayfirst=False,
            errors="coerce",
        )
        uuid_prefix = load_uuid_prefix(json_file)
        df["latex_label"] = [f"{uuid_prefix}:{label.strip()}" for label in df["label"]]
        with open(output_file, "w", encoding="utf-8") as bibtex_file:
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

            # Write snippet entries
            for index, row in df.iterrows():
                entry_lines = [f"@article{{ {row['latex_label']}  ,"]

                note_value = row.get("note", "")
                if note_value:
                    note_key = "nonote" if exclude_note else "note"
                    entry_lines.append(f"    {note_key} = {{{note_value}}},")

                title_value = replace_underscores(
                    replace_multiple_spaces(
                        remove_backslash_substrings(row.get("quote", ""))
                    )
                )
                if title_value:
                    entry_lines.append(f"    title = {{{title_value}}},")

                journal_value = replace_underscores(
                    replace_multiple_spaces(
                        remove_curly_brace_content(
                            remove_backslash_substrings(row.get("title", ""))
                        )
                    )
                )
                if journal_value and journal_value != "NAME":
                    entry_lines.append(f"    journal = {{{journal_value}}},")

                author_value = load_authors(json_file)
                if author_value:
                    entry_lines.append(f"    author = {{{author_value}}},")

                date_value = (
                    row["date"].strftime("%Y-%m-%d")
                    if not pd.isnull(row["date"])
                    else ""
                )
                if date_value:
                    entry_lines.append(f"    date = {{{date_value}}},")

                pages_value = (
                    int(row.get("opage", ""))
                    if "opage" in row and not pd.isnull(row.get("opage", ""))
                    else ""
                )
                if pages_value:
                    entry_lines.append(f"    pages = {{{pages_value}}},")

                url_value = load_url(json_file)
                if url_value:
                    entry_lines.append(f"    url = {{{url_value}}},")

                entry_lines.append("    }")
                bibtex_entry = "\n".join(entry_lines)
                bibtex_file.write(emojis_to_text(bibtex_entry) + "\n")
    except Exception as e:
        raise ValueError(f"Error processing JSON: {e}")
