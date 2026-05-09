"""Helper functions for entity detection and processing."""

import re
from collections import defaultdict

# Type mapping for fallback (subset)
FALLBACK_TYPE_MAPPING = {
    "ID_NUMBER_FALLBACK": "id_number",
}


def filter_non_overlapping(base_results, extra_results):
    """Return extra_results that do not overlap with base_results."""
    non_overlapping = []
    for er in extra_results:
        overlap = False
        for br in base_results:
            if not (er.end <= br.start or er.start >= br.end):
                overlap = True
                break
        if not overlap:
            non_overlapping.append(er)
    return non_overlapping


def fallback_scan(
    text: str, all_entities: defaultdict[str, list], type_mapping: dict[str, str]
):
    """Fallback scan for critical entities like long IBANs, dates, spaced phones, and URLs.

    Mutates all_entities and type_mapping in-place. Returns the (possibly updated)
    type_mapping for convenience.
    """
    # Ensure expected keys exist
    for k in ("id_number", "general_number", "date_number", "phone_number", "url"):
        _ = all_entities[k]  # defaultdict will create the list if missing

    # Fallback for ID numbers (IBANs) - set mapping once if any found
    iban_pattern = r"\b[A-Z]{2}\d{14,}\b"
    iban_found = False
    for match in re.finditer(iban_pattern, text, re.IGNORECASE):
        entity_text = match.group()
        if entity_text not in all_entities["id_number"]:
            all_entities["id_number"].append(entity_text)
            if entity_text not in all_entities["general_number"]:
                iban_found = True
    if iban_found:
        type_mapping.setdefault("ID_NUMBER_FALLBACK", "id_number")

    # Fallback for dates (in case Presidio misses)
    date_patterns = [
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{2}\.\d{2}\.\d{4}\b",
        r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b",
    ]
    for pattern in date_patterns:
        for match in re.finditer(pattern, text):
            entity_text = match.group()
            if (
                entity_text
                and entity_text not in all_entities["date_number"]
                and entity_text not in all_entities["general_number"]
            ):
                all_entities["date_number"].append(entity_text)

    # Fallback for spaced phones (ensure caught even if context misses)
    phone_patterns = [
        r"\d{2}\s+\d{2}\s+\d{2}\s+\d{2}",
        r"\+45\s+\d{2}\s+\d{2}\s+\d{2}\s+\d{2}",
        r"\+45\s?\d{8}",
        r"\d{4}\s+\d{4}",
    ]
    for pattern in phone_patterns:
        for match in re.finditer(pattern, text):
            entity_text = match.group()
            if (
                entity_text
                and entity_text not in all_entities["phone_number"]
                and entity_text not in all_entities["general_number"]
            ):
                all_entities["phone_number"].append(entity_text)

    # Aggressive fallback for URLs (handle truncated, partial, or complex URLs)
    # Avoid capturing trailing punctuation and try to avoid matching simple words with dots that are not URLs.
    url_patterns = [
        r"https?://[^\s'\"<>()]+(?:\.{3})?",  # full http(s) URLs, allow truncated ...
        r"www\.[^\s'\"<>()]+(?:\.{3})?",  # www. style
        r"\b[a-zA-Z0-9-]{2,}\.[a-zA-Z]{2,}(?:/[^\s'\"<>()]*)?(?:\.{3})?",  # domain + optional path
        r"\b[^\s'\"<>()]+\.[a-zA-Z]{2,}/[^\s'\"<>()]*\?[^\s'\"<>()]*(?:\.{3})?",  # urls with query params
    ]
    for pattern in url_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            entity_text = match.group().strip()
            # strip common trailing punctuation
            entity_text = entity_text.rstrip(".,;:!)?\"'")
            # simple heuristic: ignore single-token things like "e.g." or filenames without path if they are short
            if not entity_text:
                continue
            if len(entity_text) < 4:
                continue
            if entity_text not in all_entities["url"]:
                all_entities["url"].append(entity_text)

    return type_mapping
