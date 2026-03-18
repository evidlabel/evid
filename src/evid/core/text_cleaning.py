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


def clean_text_for_typst(text: str) -> str:
    """Clean text for Typst by expanding ligatures and commenting lines with '@'."""
    logger.info(f"clean_text_for_typst called with text length: {len(text)}")
    print(text)
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

    # Escape bare Typst special characters: * and $
    text = re.sub(r"(?<!\\)\*", r"\\*", text)
    text = re.sub(r"(?<!\\)\$", r"\\$", text)

    # Collapse multiple newlines
    text = re.sub(r"(\n\s*\n)+", r"\n\n", text)
    return text
