"""ID number recognizer."""

from presidio_analyzer import Pattern, PatternRecognizer


def get_id_number_recognizer(language):
    """Return PatternRecognizer for ID numbers."""
    patterns = [
        # Common IBAN pattern for both languages
        Pattern(name="iban", regex=r"\b[A-Z]{2}\d{2}[A-Z0-9]{4,30}\b", score=0.99),
    ]

    context = ["account", "iban", "ssn", "cpr", "konto"]

    if language == "da":
        # Danish-specific
        patterns.extend(
            [
                Pattern(name="cpr", regex=r"\b\d{6}-\d{4}\b", score=1.0),
                Pattern(name="dk_iban", regex=r"\bDK\d{18}\b", score=1.0),
                Pattern(name="long_number_da", regex=r"\b\d{15,}\b", score=0.95),
            ]
        )
    else:
        # English/US-specific
        patterns.extend(
            [
                Pattern(name="ssn", regex=r"\b\d{3}-\d{2}-\d{4}\b", score=1.0),
                Pattern(name="gb_iban", regex=r"\bGB[A-Z0-9]{20,24}\b", score=0.99),
                Pattern(
                    name="us_account",
                    regex=r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,20}\b",
                    score=0.95,
                ),
                Pattern(name="long_number_en", regex=r"\b\d{10,}\b", score=0.90),
            ]
        )

    # General patterns for both
    patterns.extend(
        [
            Pattern(name="long_digits", regex=r"\d{10,}", score=0.90),
            Pattern(
                name="id_code", regex=r"\b\d{3,}[\-\d]{3,}\s*\(\d{3,}\)\b", score=0.85
            ),
            Pattern(name="year_based_id", regex=r"\b\d{4}-\d{5}\b", score=0.85),
        ]
    )

    return PatternRecognizer(
        supported_entity="ID_NUMBER",
        patterns=patterns,
        context=context,
        supported_language=language,
    )
