"""Location recognizer."""

from presidio_analyzer import Pattern, PatternRecognizer


def get_location_recognizer(language):
    """Return PatternRecognizer for locations, prioritizing multiline addresses."""
    patterns = []
    context = []

    if language == "da":
        # Danish patterns (existing)
        patterns = [
            # Multiline Danish address: Street name (optional space) suffix number\nzip city
            Pattern(
                name="multiline_danish_address",
                regex=r"\b[A-Z\u00c6\u00d8\u00c5][a-z\u00e6\u00f8\u00e5\u00e9\u00fc]+\s*(?:gade|vej|str\u00e6de|plads|torv|all\u00e9|boulevard)\s+\d+\n\d{4}\s+[A-Z\u00c6\u00d8\u00c5][a-z\u00e6\u00f8\u00e5\u00e9\u00fc]+(?:\s+[A-Z\u00c6\u00d8\u00c5][a-z\u00e6\u00f8\u00e5\u00e9\u00fc]+)*[.\s]*\b",
                score=0.98,
            ),
            # Single line address
            Pattern(
                name="single_address_line",
                regex=r"\b[A-Z\u00c6\u00d8\u00c5][a-z\u00e6\u00f8\u00e5\u00e9\u00fc]+\s*(?:gade|vej|str\u00e6de|plads|torv|all\u00e9|boulevard)\s+\d+[.\s]*\b",
                score=0.9,
            ),
        ]
        context = ["adresse", "vej", "gade"]
    else:
        # English/US patterns
        patterns = [
            # Multiline English address: Street number Street name\nCity, State ZIP
            Pattern(
                name="multiline_english_address",
                regex=r"\b\d+\s+[A-Z][a-z]+(?:\s+(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Dr|Drive|Ln|Lane|Ct|Court|Pl|Place))?(?:\s+[A-Za-z0-9]+)*\n[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:,\s*[A-Z]{2})?\s*\d{5}(?:-\d{4})?\b",
                score=0.98,
            ),
            # Single line English address: number street, city, state ZIP
            Pattern(
                name="single_english_address",
                regex=r"\b\d+\s+[A-Z][a-z]+(?:\s+(?:St|Ave|Rd|Blvd|Dr|Ln|Ct|Pl))?(?:\s+[A-Za-z0-9]+)*,\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s*[A-Z]{2}\s*\d{5}(?:-\d{4})?\b",
                score=0.95,
            ),
            # City, State ZIP pattern
            Pattern(
                name="city_state_zip",
                regex=r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s*[A-Z]{2}\s*\d{5}(?:-\d{4})?\b",
                score=0.90,
            ),
            # Street address only
            Pattern(
                name="street_address",
                regex=r"\b\d+\s+[A-Z][a-z]+(?:\s+(?:St|Ave|Rd|Blvd|Dr|Ln|Ct|Pl))?(?:\s+[A-Za-z0-9]+)*\b",
                score=0.85,
            ),
        ]
        context = ["address", "street", "city", "state", "zip"]

    return PatternRecognizer(
        supported_entity="LOCATION",
        patterns=patterns,
        context=context,
        supported_language=language,
    )
