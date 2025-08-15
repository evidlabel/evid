def normalize_text(text: str | bytes | None, default: str = "") -> str:
    """Normalize text to UTF-8, preserving Danish characters (æ, ø, å)."""
    if text is None:
        return default
    if isinstance(text, bytes):
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError:
            text = text.decode("latin-1", errors="replace")
    text = str(text).strip()
    return text
