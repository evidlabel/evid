"""Deterministic fuzzy quote locator.

Given an approximate candidate quote and a full source text, locate the best
verbatim span in the source via ``rapidfuzz.fuzz.partial_ratio_alignment``, snap
the span to sentence boundaries, and return it. No LLM is involved in the match —
the returned ``exact_quote`` is a contiguous substring of the source text and
must be copied verbatim.

Ported from the standalone ``precise-quoter`` skill into evid's core so that
machine quoting is part of the CLI (see ``evid doc quote``).
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

SENTENCE_END = ".!?"


@dataclass
class MatchResult:
    """Result of locating a candidate quote in a source text.

    ``exact_quote`` is a verbatim, contiguous substring of the source between
    ``match_start`` and ``match_end`` (stripped of leading/trailing whitespace);
    it must never be retyped. ``score`` is the rapidfuzz partial ratio in [0, 1].
    """

    exact_quote: str
    score: float
    match_found: bool
    match_start: int
    match_end: int


def snap_to_sentence(text: str, start: int, end: int) -> tuple[int, int]:
    """Expand ``[start, end)`` outward to the nearest sentence boundaries.

    Walks left until a sentence terminator (``.!?``) or a newline appears just
    before the index, then skips whitespace. Walks right until a sentence
    terminator is included or EOF is hit. The returned span is a clean, readable
    excerpt that still satisfies: ``text[new_start:new_end]`` is a contiguous
    substring of ``text``.
    """
    i = start
    while i > 0:
        prev = text[i - 1]
        if prev in SENTENCE_END or prev == "\n":
            break
        i -= 1
    while i < len(text) and text[i].isspace():
        i += 1
    new_start = i

    j = max(end, new_start + 1)
    while j < len(text):
        if text[j - 1] in SENTENCE_END:
            break
        if text[j - 1] == "\n" and j - 1 >= new_start + 1:
            break
        j += 1
    new_end = min(j, len(text))

    return new_start, new_end


def fuzzy_locate(
    candidate: str, full_text: str, min_ratio: float = 0.78
) -> MatchResult:
    """Locate ``candidate`` in ``full_text`` and snap to sentence boundaries.

    Returns a :class:`MatchResult`. ``match_found`` is ``True`` when the partial
    ratio is at or above ``min_ratio``.
    """
    align = fuzz.partial_ratio_alignment(candidate, full_text)
    score = align.score / 100.0

    snap_start, snap_end = snap_to_sentence(full_text, align.dest_start, align.dest_end)
    exact_quote = full_text[snap_start:snap_end].strip()

    return MatchResult(
        exact_quote=exact_quote,
        score=round(score, 4),
        match_found=score >= min_ratio,
        match_start=snap_start,
        match_end=snap_end,
    )
