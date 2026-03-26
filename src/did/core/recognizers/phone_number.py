"""Phone number recognizer."""

from presidio_analyzer import Pattern, PatternRecognizer


def get_phone_number_recognizer(language):
    """Return PatternRecognizer for phone numbers."""
    patterns = [
        Pattern(
            name="danish_phone_with_45_spaced",
            regex=r"\+45\s\d{4}\s\d{4}",
            score=0.95,
        ),
        Pattern(
            name="danish_phone_with_45_spaced_2",
            regex=r"\+45\s\d{2}\s\d{2}\s\d{2}\s\d{2}",
            score=0.95,
        ),
        Pattern(
            name="danish_phone_with_45_8_digits",
            regex=r"\+45\s?\d{8}",
            score=0.95,
        ),
        Pattern(
            name="danish_phone_spaced",
            regex=r"\d{4}\s\d{4}",
            score=0.9,
        ),
        Pattern(
            name="danish_phone_2_2_2_2",
            regex=r"\d{2}\s\d{2}\s\d{2}\s\d{2}",
            score=0.92,
        ),
        Pattern(
            name="danish_phone_8_digits",
            regex=r"\b\d{8}\b",
            score=0.85,
        ),
    ]
    return PatternRecognizer(
        supported_entity="PHONE_NUMBER",
        patterns=patterns,
        context=["telefon", "mobil", "phone", "tel"],
        supported_language=language,
    )
