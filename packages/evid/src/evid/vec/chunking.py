"""Shared text chunking for vector indexing.

Splitting indexed text on blank lines alone turns a Typst section heading on
its own line into a one-word chunk, which then embeds and surfaces as a
context-free top hit. `chunk_text` merges sub-`MIN_CHARS` fragments into a
neighbour so only substantial passages are indexed.

Both `evid.services.vec_service` and `evid.vec.safe_index` use this so the two
indexing paths stay in sync.
"""

from __future__ import annotations

MIN_CHARS = 80  # fragments shorter than this are merged into a neighbour
_JOIN = "\n"


def _fragments(text: str) -> list[tuple[str, int]]:
    """Split on blank lines, returning (fragment, char_start) for each non-empty
    fragment. char_start is the offset of the fragment's first character in the
    original *text*, found with a forward-advancing scan."""
    frags: list[tuple[str, int]] = []
    pos = 0
    for raw in text.split("\n\n"):
        frag = raw.strip()
        if not frag:
            continue
        idx = text.find(frag, pos)
        start = idx if idx >= 0 else pos
        frags.append((frag, start))
        if idx >= 0:
            pos = idx + len(frag)
    return frags


def chunk_text(text: str) -> list[tuple[str, int]]:
    """Split *text* on blank lines, then merge short fragments into a neighbour.

    Returns a list of ``(chunk, char_start)`` where char_start is the offset of
    the chunk's first character in the original *text*. A fragment shorter than
    ``MIN_CHARS`` is appended to the previous accumulated chunk; a leading short
    fragment (e.g. a heading with no preceding chunk) is held and prepended to
    the next chunk. A document of only short fragments collapses to one chunk;
    a single fragment ``>= MIN_CHARS`` passes through unchanged.
    """
    frags = _fragments(text)
    if not frags:
        return []

    chunks: list[list] = []  # [chunk_text, char_start]
    pending: tuple[str, int] | None = None  # leading short fragment held over

    for frag, start in frags:
        cur_frag, cur_start = frag, start
        if pending is not None:
            cur_frag = pending[0] + _JOIN + cur_frag
            cur_start = pending[1]
            pending = None
        if len(cur_frag) < MIN_CHARS:
            if chunks:
                chunks[-1][0] = chunks[-1][0] + _JOIN + cur_frag
            else:
                pending = (cur_frag, cur_start)
        else:
            chunks.append([cur_frag, cur_start])

    if pending is not None:
        if chunks:
            chunks[-1][0] = chunks[-1][0] + _JOIN + pending[0]
        else:
            chunks.append([pending[0], pending[1]])

    return [(c, s) for c, s in chunks]
