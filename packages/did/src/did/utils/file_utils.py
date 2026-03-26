"""Utilities for handling different file types."""

import random
import re
from pathlib import Path

import bibtexparser

from ..core.anonymizer import Anonymizer


def extract_text(file_path: Path) -> str:
    """Extract processable text from the file based on its type."""
    if file_path.suffix in [".md", ".txt", ".pdf"]:
        if file_path.suffix == ".pdf":
            import fitz

            doc = fitz.open(file_path)
            text = ""
            for page in doc:
                text += page.get_text()
            return text
        with open(file_path, encoding="utf-8") as f:
            return f.read()
    elif file_path.suffix == ".tex":
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
            body_text = re.sub(r"\\[\w]+.*?(\s|})", " ", content)
            body_text = re.sub(
                r"\\begin\{.*?\}.*?\\end\{.*?\}", " ", body_text, flags=re.DOTALL
            )
            return re.sub(r"\s+", " ", body_text).strip()
    elif file_path.suffix == ".bib":
        with open(file_path, encoding="utf-8") as bibfile:
            database = bibtexparser.load(bibfile)
            text_content = []
            for entry in database.entries:
                for value in entry.values():
                    text_content.append(str(value))
            return " ".join(text_content)
    else:
        raise ValueError(f"Unsupported file type: {file_path.suffix}")


def anonymize_file(input_path: Path, anonymizer: Anonymizer, output_path: Path) -> dict:
    """Anonymize the file using the provided anonymizer and return counts."""
    counts = dict.fromkeys(anonymizer.counts, 0)
    if input_path.suffix in [".md", ".txt", ".tex", ".pdf"]:
        with open(input_path, encoding="utf-8") as f:
            text = f.read()
        if input_path.suffix == ".pdf":
            import fitz

            doc = fitz.open(input_path)
            text = ""
            for page in doc:
                text += page.get_text()
        anonymized_text, field_counts = anonymizer.anonymize(text)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(anonymized_text)
        for k in counts:
            counts[k] += field_counts[k]
    elif input_path.suffix == ".bib":
        with open(input_path, encoding="utf-8") as bibfile:
            database = bibtexparser.load(bibfile)
        for entry in database.entries:
            for field in list(entry.keys()):
                if field in entry:
                    field_text = str(entry[field])
                    anonymized_field, field_counts = anonymizer.anonymize(field_text)
                    entry[field] = anonymized_field
                    for k in counts:
                        counts[k] += field_counts[k]
        with open(output_path, "w", encoding="utf-8") as bibfile_out:
            bibtexparser.dump(database, bibfile_out)
    else:
        raise ValueError(f"Unsupported file type: {input_path.suffix}")
    return counts


def md_to_typst(md: str) -> str:
    """Simple Markdown to Typst converter."""
    # Headings
    md = re.sub(r"^#\s+(.*)$", r"= \1", md, flags=re.MULTILINE)
    md = re.sub(r"^##\s+(.*)$", r"== \1", md, flags=re.MULTILINE)
    md = re.sub(r"^###\s+(.*)$", r"=== \1", md, flags=re.MULTILINE)
    md = re.sub(r"^####\s+(.*)$", r"==== \1", md, flags=re.MULTILINE)
    # Italic and bold (process italic first to avoid conflict)
    md = re.sub(r"\*(.*?)\*", r"_\1_", md)
    md = re.sub(r"_(.*?)_", r"_\1_", md)
    md = re.sub(r"\*\*(.*?)\*\*", r"*\1*", md)
    md = re.sub(r"__(.*?)__", r"*\1*", md)
    # Code
    md = re.sub(r"`(.*?)`", r"`\1`", md)
    # Links
    md = re.sub(r"\[(.*?)\]\((.*?)\)", r'#link("\2")[\1]', md)
    return md


def export_to_typst(
    input_path: Path,
    anonymizer: Anonymizer,
    main_path: Path,
    vars_filename: str = None,
    fakevars_filename: str = None,
) -> None:
    """Export anonymized content to Typst files."""
    if input_path.suffix not in [".md", ".txt", ".pdf"]:
        raise ValueError(
            "Typst export currently supported only for .md, .txt, and .pdf files."
        )

    stem = main_path.stem
    parent = main_path.parent
    vars_path = parent / (vars_filename or f"{stem}_vars.typ")
    fake_path = parent / (
        fakevars_filename or f"{stem}_fakevars.typ"
    )

    # Generate Typst mappings
    var_counters = {
        "person": 0,
        "email_address": 0,
        "location": 0,
        "phone_number": 0,
        "date_number": 0,
        "id_number": 0,
        "code_number": 0,
        "general_number": 0,
        "url": 0,
    }
    typst_mappings = {}
    fake_mappings = {}

    def generate_fake_digits(length):
        return "".join(
            str(random.randint(1 if i == 0 else 0, 9)) for i in range(length)
        )

    def apply_format(variant, fake_digits):
        fake = ""
        d_idx = 0
        for char in variant:
            if char.isdigit():
                if d_idx < len(fake_digits):
                    fake += fake_digits[d_idx]
                    d_idx += 1
                else:
                    fake += str(random.randint(0, 9))
            else:
                fake += char
        return fake

    number_cats = [
        "phone_number",
        "date_number",
        "id_number",
        "code_number",
        "general_number",
    ]
    for cat in var_counters:
        prefix = {
            "person": "P",
            "email_address": "E",
            "location": "A",
            "phone_number": "PH",
            "date_number": "DT",
            "id_number": "ID",
            "code_number": "CD",
            "general_number": "GN",
            "url": "URL",
        }[cat]
        entities = getattr(anonymizer.entities, cat)
        for entity in entities:
            var_counters[cat] += 1
            ent_idx = var_counters[cat]

            if cat in number_cats:
                if entity.variants:
                    max_digit_len = max(
                        len(re.sub(r"\D", "", v)) for v in entity.variants
                    )
                    fake_digits = generate_fake_digits(max_digit_len)
                else:
                    fake_digits = ""
            else:
                fake_digits = ""

            for v_idx, variant in enumerate(entity.variants, 1):
                var = f"{prefix}{ent_idx}V{v_idx}"
                typst_mappings[var] = variant

                if cat == "person":
                    fake_var = f"Person{ent_idx} Var{v_idx}"
                elif cat == "email_address":
                    fake_var = f"email{ent_idx}var{v_idx}@example.com"
                elif cat == "location":
                    fake_var = f"Address{ent_idx} Var{v_idx}"
                elif cat == "url":
                    fake_var = f"https://example.com/url{ent_idx}v{v_idx}"
                elif cat in number_cats:
                    fake_var = apply_format(variant, fake_digits)
                else:
                    fake_var = "<FAKE>"
                fake_mappings[var] = fake_var

    # Anonymize the text using the standard method
    text = extract_text(input_path)
    anonymized_text, _ = anonymizer.anonymize(text)

    # Post-processing: Add empty line after lines ending with period
    lines = anonymized_text.split("\n")
    new_lines = []
    for line in lines:
        new_lines.append(line)
        if line.strip().endswith("."):
            new_lines.append("")
    anonymized_text = "\n".join(new_lines)

    # Remove sequences of multiple blank lines, reduce to single blank line
    cleaned_lines = []
    for line in new_lines:
        if line.strip() == "":
            if not cleaned_lines or cleaned_lines[-1].strip() != "":
                cleaned_lines.append(line)
        else:
            cleaned_lines.append(line)
    anonymized_text = "\n".join(cleaned_lines)

    parent.mkdir(parents=True, exist_ok=True)

    # Write vars.typ
    with open(vars_path, "w", encoding="utf-8") as f:
        for var, val in typst_mappings.items():
            escaped = val.replace("\\", "\\\\").replace('"', '\\"')
            f.write(f'#let {var} = "{escaped}"\n')

    # Write fakevars.typ
    with open(fake_path, "w", encoding="utf-8") as f:
        for var, val in fake_mappings.items():
            escaped = val.replace("\\", "\\\\").replace('"', '\\"')
            f.write(f'#let {var} = "{escaped}"\n')

    # Write main.typ
    with open(main_path, "w", encoding="utf-8") as f:
        f.write(f'#import "{fake_path.name}": *\n')
        f.write(f'// #import "{vars_path.name}": *\n')
        f.write(
            "// Uncomment the above line to show the document with real PII instead of fake data.\n\n"
        )
        if input_path.suffix in [".md", ".pdf"]:
            f.write(md_to_typst(anonymized_text))
        else:
            f.write(anonymized_text)
