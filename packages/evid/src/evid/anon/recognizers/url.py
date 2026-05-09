"""URL recognizer."""

from presidio_analyzer import Pattern, PatternRecognizer


def get_url_recognizer(language):
    """Return PatternRecognizer for URLs."""
    patterns = [
        # Full HTTP/HTTPS URLs with paths, query params, fragments, and truncation
        Pattern(
            name="full_url",
            regex=r"https?://(?:[a-zA-Z0-9-._~:/?#\[\]@!$&'()*+,;%=]+)(?:\.{3})?",
            score=0.99,
        ),
        # WWW URLs
        Pattern(
            name="www_url",
            regex=r"www\.(?:[a-zA-Z0-9-._~:/?#\[\]@!$&'()*+,;%=]+)(?:\.{3})?",
            score=0.98,
        ),
        # Domain-only or with path/query (aggressive fallback)
        Pattern(
            name="domain_url",
            regex=r"(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?:/[a-zA-Z0-9./?=&%#~-]*)?(?:\.{3})?",
            score=0.95,
        ),
        # URLs with query params or fragments
        Pattern(
            name="query_url",
            regex=r"[a-zA-Z0-9-]+\.[a-zA-Z]{2,}\?[^\\s]+(?:\.{3})?",
            score=0.97,
        ),
    ]
    return PatternRecognizer(
        supported_entity="URL",
        patterns=patterns,
        context=["http", "https", "www", "url", "link", "site"],
        supported_language=language,
    )
