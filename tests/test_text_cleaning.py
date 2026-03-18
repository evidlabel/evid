"""Tests for text_cleaning module."""

from evid.core.text_cleaning import clean_text_for_typst


def test_ligature_expansion():
    assert clean_text_for_typst("\ufb01le") == "file"


def test_at_sign_commented():
    result = clean_text_for_typst("email@example.com")
    assert result.startswith("// ")


def test_bare_asterisk_escaped():
    assert "\\*" in clean_text_for_typst("a * b")


def test_bare_dollar_escaped():
    assert "\\$" in clean_text_for_typst("costs $100")


def test_already_escaped_asterisk_unchanged():
    result = clean_text_for_typst("already \\* escaped")
    assert result.count("\\*") == 1


def test_already_escaped_dollar_unchanged():
    result = clean_text_for_typst("already \\$ escaped")
    assert result.count("\\$") == 1


def test_multiple_newlines_collapsed():
    result = clean_text_for_typst("a\n\n\n\nb")
    assert "\n\n\n" not in result
