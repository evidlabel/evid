"""Text cleaning functions for evid."""

import logging
import re

logger = logging.getLogger(__name__)

LIGATURES = {
    "\ufb00": "ff",  # ﬀ
    "\ufb01": "fi",  # ﬁ
    "\ufb02": "fl",  # ﬂ
    "\ufb03": "ffi",  # ﬃ
    "\ufb04": "ffl",  # ﬄ
    "\ufb05": "ft",  # ﬅ
    "\ufb06": "st",  # ﬆ
}


_URL_CONT_END = "/?#&=-+_"
_URL_CONT_START = "/?#&="
_URL_SPLIT_RE = re.compile(r"(https?://\S+)\n(\S+)")


def _rejoin_split_urls(text: str) -> str:
    """Rejoin URLs broken across lines by HTML/PDF text extraction.

    BeautifulSoup's get_text(separator='\\n') and PDF text extraction can
    split URLs at element boundaries (e.g. <wbr>) or visual line wraps,
    leaving fragments like:
        https://example.com/
        very/long/path?x=1
    Merge such pairs only when there is a strong continuation signal
    (URL-internal punctuation at the join), to avoid gluing a URL onto a
    following sentence.
    """

    def _maybe_join(m: re.Match) -> str:
        head, tail = m.group(1), m.group(2)
        if head[-1] in _URL_CONT_END or tail[0] in _URL_CONT_START:
            return head + tail
        return m.group(0)

    prev = None
    while text != prev:
        prev = text
        text = _URL_SPLIT_RE.sub(_maybe_join, text)
    return text


def clean_text_for_typst(text: str) -> str:
    """Clean text for Typst by expanding ligatures and commenting lines with '@'."""
    logger.info(f"clean_text_for_typst called with text length: {len(text)}")
    text = _rejoin_split_urls(text)
    # Expand ligatures
    for lig, repl in LIGATURES.items():
        if lig in text:
            logger.info(f"Found ligature {lig!r} in text")
            text = text.replace(lig, repl)
            logger.info(f"Replaced ligature {lig!r} with {repl!r}")

    # Split into lines
    lines = text.split("\n")

    # Process lines: comment if '@' in line, and add extra newline if ends with punctuation
    processed_lines = []
    for line in lines:
        if "@" in line:
            processed_lines.append("// " + line)
        else:
            processed_lines.append(line)
            stripped = line.strip()
            if stripped and stripped[-1] in ".!?":
                processed_lines.append("")

    # Join back
    text = "\n".join(processed_lines)

    # Escape bare Typst special characters: #, * and $
    text = re.sub(r"(?<!\\)#", r"\\#", text)
    text = re.sub(r"(?<!\\)\*", r"\\*", text)
    text = re.sub(r"(?<!\\)\$", r"\\$", text)

    # Escape line-leading '/' that Typst would parse as a term-list item.
    # Typst term syntax is `/ TERM: DESCRIPTION`; a bare '/' or '/' followed by
    # whitespace at line start triggers `error: expected colon`.
    text = re.sub(r"(?m)^([ \t]*)/(?=[ \t]*$|[ \t]+\S)", r"\1\\/", text)

    # Collapse multiple newlines
    text = re.sub(r"(\n\s*\n)+", r"\n\n", text)
    return text
