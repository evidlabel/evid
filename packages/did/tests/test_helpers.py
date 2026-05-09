"""Tests for helper functions."""

from collections import defaultdict

from did.core.helpers import fallback_scan, filter_non_overlapping


def test_filter_non_overlapping():
    # Mock result objects with start, end
    class MockResult:
        def __init__(self, start, end):
            self.start = start
            self.end = end

    base_results = [MockResult(0, 5), MockResult(10, 15)]
    extra_results = [
        MockResult(5, 10),
        MockResult(15, 20),
        MockResult(0, 3),
    ]  # 0-3 overlaps, 5-10 doesn't, 15-20 doesn't
    non_overlapping = filter_non_overlapping(base_results, extra_results)
    assert len(non_overlapping) == 2
    assert non_overlapping[0].start == 5
    assert non_overlapping[1].start == 15

    base_results = []
    extra_results = [MockResult(0, 5)]
    non_overlapping = filter_non_overlapping(base_results, extra_results)
    assert len(non_overlapping) == 1


def test_fallback_scan():
    text = "IBAN: DE89370400440532013000 Phone: 12 34 56 78 Date: 2023-10-15 URL: https://example.com"
    all_entities = defaultdict(list)
    type_mapping = {}

    fallback_scan(text, all_entities, type_mapping)

    assert "DE89370400440532013000" in all_entities["id_number"]
    assert "12 34 56 78" in all_entities["phone_number"]
    assert "2023-10-15" in all_entities["date_number"]
    assert "https://example.com" in all_entities["url"]

    # Test IBAN mapping
    assert type_mapping.get("ID_NUMBER_FALLBACK") == "id_number"

    # Test no duplicates
    text2 = "IBAN: DE89370400440532013000 again"
    all_entities2 = defaultdict(list)
    type_mapping2 = {}
    fallback_scan(text2, all_entities2, type_mapping2)
    assert all_entities2["id_number"].count("DE89370400440532013000") == 1

    # Test spaced phones
    text3 = "+45 12 34 56 78"
    all_entities3 = defaultdict(list)
    type_mapping3 = {}
    fallback_scan(text3, all_entities3, type_mapping3)
    assert "+45 12 34 56 78" in all_entities3["phone_number"]

    # Test URLs
    text4 = "Visit www.example.com or example.org/path"
    all_entities4 = defaultdict(list)
    type_mapping4 = {}
    fallback_scan(text4, all_entities4, type_mapping4)
    assert "www.example.com" in all_entities4["url"]
    assert "example.org/path" in all_entities4["url"]

    # Test date patterns
    text5 = "Date: 15.10.2023 or 10/15/2023"
    all_entities5 = defaultdict(list)
    type_mapping5 = {}
    fallback_scan(text5, all_entities5, type_mapping5)
    assert "15.10.2023" in all_entities5["date_number"]
    assert "10/15/2023" in all_entities5["date_number"]

    # Test short or invalid
    text6 = "e.g. test"
    all_entities6 = defaultdict(list)
    type_mapping6 = {}
    fallback_scan(text6, all_entities6, type_mapping6)
    assert "e.g." not in all_entities6["url"]
