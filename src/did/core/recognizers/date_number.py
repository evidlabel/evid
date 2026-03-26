"""Date number recognizer."""

from presidio_analyzer import Pattern, PatternRecognizer


def get_date_number_recognizer(language):
    """Return PatternRecognizer for date numbers."""
    patterns = [
        Pattern(
            name="full_date", regex=r"\b\d{4}-\d{2}-\d{2}\b", score=0.95
        ),
        Pattern(name="dotted_date", regex=r"\b\d{2}\.\d{2}\.\d{4}\b", score=0.95),
        Pattern(name="short_date", regex=r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b", score=0.9),
        Pattern(name="year_only", regex=r"\b\d{4}\b", score=0.8),
    ]
    return PatternRecognizer(
        supported_entity="DATE_NUMBER",
        patterns=patterns,
        supported_language=language,
    )
