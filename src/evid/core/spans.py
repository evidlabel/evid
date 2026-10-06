"""Spans: a passage of a document's canonical text (``label/text.txt``).

Human labels, passage annotations and machine quotes all point into the text
the same way::

    {"start": 1234, "end": 1290, "page": 2, "text": "the exact slice",
     "prefix": "…32 chars before", "suffix": "32 chars after…"}

``text`` is always ``full_text[start:end]`` — verbatim, never retyped. The
``prefix`` / ``suffix`` context lets a span find its place again if the text is
ever extracted anew (see :func:`reanchor`).
"""

from __future__ import annotations

from typing import Any

CONTEXT = 32  # characters of context kept each side


def page_for_offset(offset: int, pages: list[list[int]] | list[tuple[int, int]]) -> int:
    """1-based page number of a character offset, from ``[[start_offset, page], …]``."""
    page = pages[0][1] if pages else 1
    for start, no in pages:
        if start <= offset:
            page = no
        else:
            break
    return page


def make_span(full_text: str, start: int, end: int, pages) -> dict[str, Any]:
    """A span over ``full_text[start:end]`` (whitespace at the ends trimmed)."""
    if not 0 <= start < end <= len(full_text):
        msg = f"span {start}-{end} is outside the text (0-{len(full_text)})"
        raise ValueError(msg)
    while start < end and full_text[start].isspace():
        start += 1
    while end > start and full_text[end - 1].isspace():
        end -= 1
    if start == end:
        msg = "the passage is empty"
        raise ValueError(msg)
    return {
        "start": start,
        "end": end,
        "page": page_for_offset(start, pages),
        "text": full_text[start:end],
        "prefix": full_text[max(0, start - CONTEXT) : start],
        "suffix": full_text[end : end + CONTEXT],
    }


def is_valid(span: dict, full_text: str) -> bool:
    """The stored offsets still hold the stored text."""
    s, e = span.get("start", -1), span.get("end", -1)
    return 0 <= s < e <= len(full_text) and full_text[s:e] == span.get("text")


def _occurrences(text: str, needle: str) -> list[int]:
    out, i = [], text.find(needle)
    while i != -1:
        out.append(i)
        i = text.find(needle, i + 1)
    return out


def reanchor(
    span: dict, full_text: str, pages, min_ratio: float = 0.92
) -> tuple[dict | None, str]:
    """Find *span* in *full_text* again. Returns ``(span, how)``:

    - ``"same"``: the offsets still hold the text;
    - ``"moved"``: the exact text, found again (the one whose context fits best);
    - ``"fuzzy"``: the closest passage (rapidfuzz ratio >= *min_ratio*), now verbatim;
    - ``(None, "lost")``: not found.
    """
    if is_valid(span, full_text):
        return make_span(full_text, span["start"], span["end"], pages) | _keep(
            span
        ), "same"
    needle = span.get("text") or ""
    hits = _occurrences(full_text, needle) if needle else []
    if hits:
        pre, suf = span.get("prefix", ""), span.get("suffix", "")

        def fit(i: int) -> int:
            before = full_text[max(0, i - len(pre)) : i]
            after = full_text[i + len(needle) : i + len(needle) + len(suf)]
            return sum(
                a == b for a, b in zip(reversed(before), reversed(pre), strict=False)
            ) + sum(a == b for a, b in zip(after, suf, strict=False))

        best = max(hits, key=lambda i: (fit(i), -abs(i - span.get("start", 0))))
        return make_span(full_text, best, best + len(needle), pages) | _keep(
            span
        ), "moved"
    if needle:
        found = locate(needle, full_text, min_ratio)
        if found:
            start, end, _score, how = found
            return make_span(full_text, start, end, pages) | _keep(
                span
            ), "moved" if how == "spaces" else "fuzzy"
    return None, "lost"


def _squash(text: str) -> tuple[str, list[int]]:
    """*text* with every run of whitespace as one space, and each char's offset in *text*."""
    out, where, space = [], [], False
    for i, c in enumerate(text):
        if c.isspace():
            if not space and out:
                out.append(" ")
                where.append(i)
            space = True
        else:
            out.append(c)
            where.append(i)
            space = False
    return "".join(out), where


def locate(
    needle: str, full_text: str, min_ratio: float = 0.92
) -> tuple[int, int, float, str] | None:
    """Where *needle* is in *full_text*: ``(start, end, score, how)`` or None.

    ``how`` is ``exact``, ``spaces`` (equal once line breaks / runs of spaces are
    ignored) or ``fuzzy`` (rapidfuzz alignment, score >= *min_ratio*; the extent
    is the aligned passage, not snapped to sentences).
    """
    needle = needle.strip()
    if not needle:
        return None
    i = full_text.find(needle)
    if i != -1:
        return i, i + len(needle), 1.0, "exact"
    sq_text, where = _squash(full_text)
    sq_needle = _squash(needle)[0].strip()
    j = sq_text.find(sq_needle)
    if j != -1 and sq_needle:
        return where[j], where[j + len(sq_needle) - 1] + 1, 1.0, "spaces"
    from rapidfuzz import fuzz

    al = fuzz.partial_ratio_alignment(sq_needle, sq_text)
    score = al.score / 100.0
    if score >= min_ratio and al.dest_end > al.dest_start:
        return where[al.dest_start], where[al.dest_end - 1] + 1, score, "fuzzy"
    return None


def _keep(span: dict) -> dict:
    """Fields of a record that are not the span itself (key, notes, …)."""
    return {
        k: v
        for k, v in span.items()
        if k not in ("start", "end", "page", "text", "prefix", "suffix")
    }
