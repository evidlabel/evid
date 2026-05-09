"""Code number recognizer."""

from presidio_analyzer import Pattern, PatternRecognizer


def get_code_number_recognizer(language):
    """Return PatternRecognizer for code numbers."""
    patterns = [
        Pattern(name="parenthesized_code", regex=r"\(\d{6}\)\b", score=0.9),
        Pattern(
            name="channel_identifier",
            regex=r"\b\d{1,2},\d{1,2}\.[a-zA-Z]{2,3}\b",
            score=0.85,
        ),
    ]
    return PatternRecognizer(
        supported_entity="CODE_NUMBER",
        patterns=patterns,
        supported_language=language,
    )
