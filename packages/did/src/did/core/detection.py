"""Entity detection logic for Anonymizer."""

from collections import defaultdict

from did.utils.console import console
from did.utils.entity_utils import find_name_variants, find_number_variants

from .helpers import fallback_scan
from .models import Entity

# Type mapping for entities
TYPE_MAPPING = {
    "PERSON": "person",
    "EMAIL_ADDRESS": "email_address",
    "LOCATION": "location",
    "PHONE_NUMBER": "phone_number",
    "DATE_TIME": "date_number",
    "GENERAL_NUMBER": "general_number",
    "DATE_NUMBER": "date_number",
    "ID_NUMBER": "id_number",
    "CODE_NUMBER": "code_number",
    "URL": "url",
}


CATEGORIES = [
    "person",
    "email_address",
    "location",
    "phone_number",
    "date_number",
    "id_number",
    "code_number",
    "general_number",
    "url",
]


NUMBER_CATEGORIES = [
    "phone_number",
    "date_number",
    "id_number",
    "code_number",
    "general_number",
]


def generate_possessives(variants: list[str]) -> list[str]:
    """Generate possessive forms for person name variants."""
    expanded = set(variants)
    for v in variants:
        # Add standard possessive 's
        expanded.add(v + "'s")
        # If ends with 's', also add just '
        if v.strip().endswith("s"):
            expanded.add(v + "'")
        # For Danish/English plural-like, add 's without apostrophe in some cases, but keep simple
        expanded.add(v + "s")
    return list(expanded)


def detect_entities(anonymizer, texts: list):
    """Detect entities in multiple texts using Presidio."""
    model_used = anonymizer.model_map.get(anonymizer.language, "unknown")
    console.log(
        f"Using spaCy model [bold]{model_used}[/bold] for language [bold]{anonymizer.language}[/bold]"
    )
    all_entities = defaultdict(list)
    for text in texts:
        detection_text, map_to_original = anonymizer.preprocess_text(text)
        results = anonymizer.analyzer.analyze(
            text=detection_text,
            language=anonymizer.language,
            entities=None,
        )

        # Aggressive deduplication: Prefer longer entities, then higher score
        sorted_results = sorted(results, key=lambda r: (-(r.end - r.start), -r.score))
        selected_results = []
        used_spans = []
        for result in sorted_results:
            overlap = False
            for s_start, s_end in used_spans:
                if not (result.end <= s_start or result.start >= s_end):
                    overlap = True
                    break
            if not overlap:
                selected_results.append(result)
                used_spans.append((result.start, result.end))

        for result in selected_results:
            o_start, o_end = map_to_original(result.start, result.end)
            try:
                entity_text = text[o_start:o_end].strip()
            except IndexError:
                entity_text = ""
            ent_type = result.entity_type
            if ent_type in TYPE_MAPPING and entity_text:
                mapped = TYPE_MAPPING[ent_type]
                if entity_text not in all_entities[mapped]:
                    all_entities[mapped].append(entity_text)
                    anonymizer.counts[f"{mapped}_found"] += 1

        # Fallback scan
        fallback_scan(text, all_entities, TYPE_MAPPING)

    # Group entities
    for cat in CATEGORIES:
        items = all_entities.get(cat, [])
        if cat == "person":
            grouped = find_name_variants(items)
            # Expand with possessive variants
            expanded_groups = []
            for group in grouped:
                expanded_variants = generate_possessives(group)
                expanded_groups.append(expanded_variants)
            grouped = expanded_groups
        elif cat in ["email_address", "location", "url"]:
            grouped = [[item] for item in items if item]
        else:
            threshold = 95 if cat == "date_number" else 80
            grouped = find_number_variants(items, threshold=threshold)
        count = 1
        for variants in grouped:
            ent_type_upper = cat.upper() if cat != "email_address" else "EMAIL_ADDRESS"
            getattr(anonymizer.entities, cat).append(
                Entity(id=f"{ent_type_upper}_{count}", variants=variants)
            )
            count += 1


def preprocess_text(text: str):
    """Preprocess text to join hyphenated multi-line words for detection."""
    positions = []
    detection_text = ""
    i = 0
    while i < len(text):
        if (
            i > 0
            and (text[i - 1].isalpha() or text[i - 1].isdigit())
            and text[i] == "-"
            and i + 1 < len(text)
            and text[i + 1] == "\n"
            and i + 2 < len(text)
            and (text[i + 2].isalpha() or text[i + 2].isdigit())
        ):
            i += 2
            continue
        detection_text += text[i]
        positions.append(i)
        i += 1

    def map_to_original(d_start: int, d_end: int):
        if d_start >= len(positions):
            return len(text), len(text)
        o_start = positions[d_start]
        o_end = (
            positions[d_end - 1] + 1
            if d_end > 0 and d_end <= len(positions)
            else len(text)
        )
        return o_start, o_end

    return detection_text, map_to_original
