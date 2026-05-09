"""Tests for core Anonymizer functionality."""

import pytest
from ruamel import yaml

from did.core.anonymizer import Anonymizer


@pytest.fixture
def anonymizer():
    return Anonymizer(language="en")


def test_extract_empty_text(anonymizer):
    anonymizer.detect_entities([""])
    yaml_obj = yaml.YAML()
    config_str = anonymizer.generate_yaml()
    config = yaml_obj.load(config_str)
    assert config["PERSON"] == []
    assert config["EMAIL_ADDRESS"] == []
    assert config["LOCATION"] == []
    assert config["PHONE_NUMBER"] == []
    assert config["DATE_NUMBER"] == []
    assert config["ID_NUMBER"] == []
    assert config["CODE_NUMBER"] == []
    assert config["GENERAL_NUMBER"] == []
    assert all(count == 0 for count in anonymizer.counts.values())


def test_anonymize_name_exact(anonymizer):
    text = "Hello John Doe, how are you?"
    anonymizer.detect_entities([text])
    anonymizer.load_replacements(
        anonymizer.entities.model_dump(by_alias=True, exclude_none=True)
    )
    result, counts = anonymizer.anonymize(text)
    assert "#(P1V" in result
    assert counts["person_found"] >= 1
    assert counts["person_replaced"] >= 1


def test_anonymize_name_variants(anonymizer):
    text = "John Doe and Jon Doe and john DOE were mentioned."
    anonymizer.detect_entities([text])
    anonymizer.load_replacements(
        anonymizer.entities.model_dump(by_alias=True, exclude_none=True)
    )
    config_str = anonymizer.generate_yaml()
    yaml_obj = yaml.YAML()
    config = yaml_obj.load(config_str)
    assert len(config["PERSON"]) == 1
    result, counts = anonymizer.anonymize(text)
    assert "#(P1V" in result
    assert counts["person_found"] == 3
    assert counts["person_replaced"] == 3


def test_anonymize_number_variants(anonymizer):
    text = "Account: 1234567890, Phone: 1234567, Code: 12 34 56 78"
    anonymizer.detect_entities([text])
    anonymizer.load_replacements(
        anonymizer.entities.model_dump(by_alias=True, exclude_none=True)
    )
    config_str = anonymizer.generate_yaml()
    yaml_obj = yaml.YAML()
    config = yaml_obj.load(config_str)
    assert any(
        "1234567890" in entry["variants"]
        for entry in config.get("PHONE_NUMBER", []) + config.get("GENERAL_NUMBER", [])
    )
    assert any(
        "12 34 56 78" in entry["variants"]
        for entry in config.get("PHONE_NUMBER", []) + config.get("GENERAL_NUMBER", [])
    )
    result, counts = anonymizer.anonymize(text)
    assert "#(PH" in result or "#(GN" in result
    assert counts["phone_number_found"] + counts["general_number_found"] >= 3


def test_anonymize_address(anonymizer):
    text = "Lives at 123 Oneway St, Springfield, US"
    anonymizer.detect_entities([text])
    anonymizer.load_replacements(
        anonymizer.entities.model_dump(by_alias=True, exclude_none=True)
    )
    result, counts = anonymizer.anonymize(text)
    assert "#(A1V" in result
    assert counts["location_found"] >= 1
    assert counts["location_replaced"] >= 1


def test_anonymize_danish_address():
    anonymizer = Anonymizer(language="da")
    text = "Bor på Langelandsgade 14, 1.tv, 7300 Jelling"
    anonymizer.detect_entities([text])
    assert anonymizer.counts["location_found"] >= 1
    anonymizer.load_replacements(
        anonymizer.entities.model_dump(by_alias=True, exclude_none=True)
    )
    result, counts = anonymizer.anonymize(text)
    assert "#(A1V" in result
    assert counts["location_found"] >= 1
    assert counts["location_replaced"] >= 1


def test_anonymize_cpr():
    anonymizer = Anonymizer(language="da")
    text = "CPR: 123456-1234"
    anonymizer.detect_entities([text])
    anonymizer.load_replacements(
        anonymizer.entities.model_dump(by_alias=True, exclude_none=True)
    )
    result, counts = anonymizer.anonymize(text)
    assert "#(GN1V" in result
    assert counts["general_number_found"] >= 1
    assert counts["general_number_replaced"] >= 1


def test_anonymize_danish_compound_name():
    anonymizer = Anonymizer(language="da")
    text = "Stine Louise Eising von Christierson bor i København."
    anonymizer.detect_entities([text])
    anonymizer.load_replacements(
        anonymizer.entities.model_dump(by_alias=True, exclude_none=True)
    )
    result, counts = anonymizer.anonymize(text)
    assert "#(P1V" in result
    assert counts["person_found"] >= 1
    assert counts["person_replaced"] >= 1
    assert "Stine" not in result


def test_anonymize_mixed_content(anonymizer):
    text = "Contact John Doe at 1234567890 or Jane Smith via 12 34 56 78. Jon Doe and Jane Smyth share details at 123 Oneway St, Springfield, US. CPR: 123456-1234. Additional phone: 1234567"
    anonymizer.detect_entities([text])
    anonymizer.load_replacements(
        anonymizer.entities.model_dump(by_alias=True, exclude_none=True)
    )
    result, counts = anonymizer.anonymize(text)
    assert "#(PH" in result or "#(GN" in result
    assert "#(A" in result
    assert counts["person_found"] >= 4
    assert counts["person_replaced"] >= 4
    assert counts["phone_number_found"] + counts["general_number_found"] >= 2
    assert counts["location_found"] >= 1
    assert counts["location_replaced"] >= 1
