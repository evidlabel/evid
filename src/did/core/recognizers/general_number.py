"""General number recognizer."""

from presidio_analyzer import Pattern, PatternRecognizer


def get_general_number_recognizer(language):
    """Return PatternRecognizer for general numbers."""
    patterns = [
        Pattern(
            name="aggressive_number",
            regex=r"\b[\d\s\-.,+/()]*\d[\d\s\-.,+/()]*\b",  # Removed literal spaces
            score=0.7,
        ),
        Pattern(name="single_digit", regex=r"\b\d\b", score=0.6),
        Pattern(name="letter_digit", regex=r"\b[A-Z]{1,4}\d{2,10}", score=0.8),
        Pattern(name="digit_sequence", regex=r"\d{2,20}", score=0.85),
    ]
    return PatternRecognizer(
        supported_entity="GENERAL_NUMBER",
        patterns=patterns,
        supported_language=language,
    )
