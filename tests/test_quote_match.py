"""Tests for the deterministic fuzzy quote matcher."""

from evid.core.quote_match import fuzzy_locate, snap_to_sentence

SOURCE = (
    "The court considered the matter at length. "
    "After lengthy deliberation, the committee found that the evidence was "
    "conclusive and the defendant had acted in clear violation of the rules. "
    "The appeal was dismissed."
)


def test_snap_to_sentence_expands_to_boundaries():
    # Point inside the second sentence.
    idx = SOURCE.index("committee")
    start, end = snap_to_sentence(SOURCE, idx, idx + 5)
    excerpt = SOURCE[start:end]
    assert excerpt.startswith("After lengthy deliberation")
    assert excerpt.rstrip().endswith("violation of the rules.")
    # Span is a contiguous substring.
    assert SOURCE[start:end] == excerpt


def test_fuzzy_locate_returns_verbatim_span():
    # Paraphrased / loose candidate.
    candidate = "the committee found the evidence conclusive and the defendant violated the rules"
    res = fuzzy_locate(candidate, SOURCE, min_ratio=0.6)
    assert res.match_found
    # The returned quote is a verbatim substring of the source.
    assert res.exact_quote in SOURCE
    assert "committee found that the evidence was" in res.exact_quote


def test_fuzzy_locate_below_threshold_not_found():
    res = fuzzy_locate("entirely unrelated text about astronomy", SOURCE, min_ratio=0.9)
    assert not res.match_found


def test_fuzzy_locate_is_deterministic():
    candidate = "appeal was dismissed"
    a = fuzzy_locate(candidate, SOURCE, 0.6)
    b = fuzzy_locate(candidate, SOURCE, 0.6)
    assert (a.exact_quote, a.score, a.match_start) == (
        b.exact_quote,
        b.score,
        b.match_start,
    )
