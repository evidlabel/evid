"""Recognizers package."""

from .code_number import get_code_number_recognizer
from .date_number import get_date_number_recognizer
from .general_number import get_general_number_recognizer
from .id_number import get_id_number_recognizer
from .location import get_location_recognizer
from .phone_number import get_phone_number_recognizer
from .url import get_url_recognizer


def get_custom_recognizers(language):
    """Return a list of custom PatternRecognizers for different entity types."""
    return [
        get_general_number_recognizer(language),
        get_date_number_recognizer(language),
        get_id_number_recognizer(language),
        get_code_number_recognizer(language),
        get_location_recognizer(language),
        get_phone_number_recognizer(language),
        get_url_recognizer(language),
    ]
