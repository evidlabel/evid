"""Tests for entity utility functions."""

from did.utils.entity_utils import (
    find_name_variants,
    find_number_variants,
    is_possible_variant,
    is_valid_name,
    normalize_name,
    normalize_number,
    strip_titles,
)


def test_strip_titles():
    assert strip_titles("Dr. John Doe") == "John Doe"
    assert strip_titles("Prof. Jane Smith") == "Jane Smith"
    assert strip_titles("Mr. John Doe") == "John Doe"
    assert strip_titles("Mrs. Jane Smith") == "Jane Smith"
    assert strip_titles("Ms. Jane Smith") == "Jane Smith"
    assert strip_titles("Ph.D. John Doe") == "John Doe"
    assert strip_titles("M.D. John Doe") == "John Doe"
    assert strip_titles("Ing. John Doe") == "John Doe"
    assert strip_titles("Fru Jane Smith") == "Jane Smith"
    assert strip_titles("Hr. John Doe") == "John Doe"
    assert strip_titles("Md. John Doe") == "John Doe"
    assert strip_titles("Lic. John Doe") == "John Doe"
    assert strip_titles("John Doe") == "John Doe"  # No title
    assert strip_titles("dr. john doe") == "john doe"  # Case insensitive


def test_normalize_name():
    assert normalize_name("John Doe") == "john doe"
    assert normalize_name("Åse Ærø") == "aase aeroe"
    assert normalize_name("Øystein") == "oeystein"
    assert normalize_name("Jean-Paul") == "jeanpaul"
    assert normalize_name("Dr. John Doe\n") == "john doe"
    assert normalize_name("JOHN DOE") == "john doe"


def test_normalize_number():
    assert normalize_number("123 456 789") == "123456789"
    assert normalize_number("123-456-789") == "123456789"
    assert normalize_number("(123) 456-789") == "123456789"
    assert normalize_number("+45 12345678") == "4512345678"
    assert normalize_number("123.456.789") == "123.456.789"  # Dots not removed


def test_is_valid_name():
    assert is_valid_name("John Doe") is True
    assert is_valid_name("Jane Smith Jones") is True
    assert is_valid_name("J. Doe") is True
    assert is_valid_name("John") is True
    assert is_valid_name("123") is False
    assert is_valid_name("Phone Number") is False
    assert is_valid_name("Account Code") is False
    assert is_valid_name("") is False
    assert is_valid_name("Multiline Name") is False
    assert is_valid_name("Street Address") is False


def test_is_possible_variant():
    assert is_possible_variant("J. Doe", "John Doe") is True
    assert is_possible_variant("John", "John Doe") is True
    assert is_possible_variant("Doe", "John Doe") is True
    assert is_possible_variant("J.D.", "John Doe") is True
    assert is_possible_variant("John Doe", "J. Doe") is False  # Shorter not variant of longer
    assert is_possible_variant("Jane Doe", "John Doe") is False  # Different name
    assert is_possible_variant("", "John Doe") is False
    assert is_possible_variant("John Doe Smith", "John Doe") is False  # Longer not variant


def test_find_name_variants():
    names = ["John Doe", "J. Doe", "Jon Doe", "Jane Smith", "J. Smith"]
    groups = find_name_variants(names)
    assert len(groups) == 2
    assert {"John Doe", "J. Doe", "Jon Doe"} in [set(g) for g in groups]
    assert {"Jane Smith", "J. Smith"} in [set(g) for g in groups]

    names = ["John Doe", "Jane Doe"]  # Not similar
    groups = find_name_variants(names)
    assert len(groups) == 2

    names = []
    groups = find_name_variants(names)
    assert groups == []


def test_find_number_variants():
    numbers = ["123456789", "123 456 789", "123-456-789"]
    groups = find_number_variants(numbers)
    assert len(groups) == 1
    assert set(groups[0]) == {"123456789", "123 456 789", "123-456-789"}

    numbers = ["123456789", "987654321"]  # Not similar
    groups = find_number_variants(numbers)
    assert len(groups) == 2

    numbers = []
    groups = find_number_variants(numbers)
    assert groups == []
