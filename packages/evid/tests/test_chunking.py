"""Tests for evid.vec.chunking.chunk_text — small-fragment merging."""

from evid.vec.chunking import MIN_CHARS, chunk_text

LONG = "x" * (MIN_CHARS + 10)  # a fragment that passes through unchanged
LONG2 = "y" * (MIN_CHARS + 10)
SHORT = "Heading"  # < MIN_CHARS


def test_empty_text():
    assert chunk_text("") == []
    assert chunk_text("\n\n   \n\n") == []


def test_long_paragraph_passes_through():
    pairs = chunk_text(LONG)
    assert len(pairs) == 1
    assert pairs[0][0] == LONG
    assert pairs[0][1] == 0


def test_heading_then_paragraph_merge():
    text = f"{SHORT}\n\n{LONG}"
    pairs = chunk_text(text)
    assert len(pairs) == 1
    chunk, start = pairs[0]
    assert SHORT in chunk
    assert LONG in chunk
    assert start == 0  # points at the heading, the first character


def test_leading_short_prepends_to_next():
    text = f"{SHORT}\n\n{LONG}\n\n{LONG2}"
    pairs = chunk_text(text)
    # heading merges into first long; second long is its own chunk
    assert len(pairs) == 2
    assert SHORT in pairs[0][0]
    assert LONG in pairs[0][0]
    assert pairs[1][0] == LONG2


def test_trailing_short_appends_to_previous():
    text = f"{LONG}\n\n{SHORT}"
    pairs = chunk_text(text)
    assert len(pairs) == 1
    assert LONG in pairs[0][0]
    assert SHORT in pairs[0][0]


def test_all_short_collapses_to_one():
    text = "a\n\nb\n\nc"
    pairs = chunk_text(text)
    assert len(pairs) == 1
    assert pairs[0][1] == 0


def test_char_start_offsets_point_correctly():
    text = f"intro line padding {LONG}\n\n{LONG2}"
    pairs = chunk_text(text)
    assert len(pairs) == 2
    # each char_start indexes the original text at the chunk's first fragment
    first_frag = pairs[0][0].split("\n")[0]
    assert text[pairs[0][1] : pairs[0][1] + len(first_frag)] == first_frag
    assert text[pairs[1][1] : pairs[1][1] + len(LONG2)] == LONG2


def test_no_one_word_chunks_surface_alone():
    # A bare heading sandwiched between paragraphs never stands alone.
    text = f"{LONG}\n\n{SHORT}\n\n{LONG2}"
    pairs = chunk_text(text)
    for chunk, _ in pairs:
        assert len(chunk) >= MIN_CHARS
