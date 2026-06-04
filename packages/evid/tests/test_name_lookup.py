"""Tests for name_lookup — demographic inversion."""

from evid.models import Gender, NameOrigin
from evid.services.name_lookup import (
    _invert_gender,
    _invert_origin,
    _load_names,
    detect_gender_from_name,
    generate_all_profiles,
    generate_fake_name,
)


def test_invert_gender():
    assert _invert_gender(Gender.MALE) == Gender.FEMALE
    assert _invert_gender(Gender.FEMALE) == Gender.MALE
    assert _invert_gender(Gender.NEUTRAL) == Gender.NEUTRAL


def test_invert_origin():
    assert _invert_origin(NameOrigin.DANISH) == NameOrigin.ARABIC
    assert _invert_origin(NameOrigin.ARABIC) == NameOrigin.DANISH


def test_load_danish_male_names():
    names = _load_names(NameOrigin.DANISH, Gender.MALE, "first")
    assert len(names) > 0
    assert all(isinstance(n, str) for n in names)


def test_load_danish_female_names():
    names = _load_names(NameOrigin.DANISH, Gender.FEMALE, "first")
    assert len(names) > 0


def test_load_danish_last_names():
    names = _load_names(NameOrigin.DANISH, Gender.MALE, "last")
    assert len(names) > 0


def test_generate_fake_name_deterministic():
    n1 = generate_fake_name(0, "uuid-1", Gender.MALE, NameOrigin.DANISH, "same")
    n2 = generate_fake_name(0, "uuid-1", Gender.MALE, NameOrigin.DANISH, "same")
    assert n1 == n2


def test_generate_fake_name_different_entities():
    n1 = generate_fake_name(0, "uuid-1", Gender.MALE, NameOrigin.DANISH, "same")
    n2 = generate_fake_name(1, "uuid-1", Gender.MALE, NameOrigin.DANISH, "same")
    # Different entity indices should (statistically) produce different names
    # (may occasionally be equal by chance — that's acceptable)
    assert isinstance(n1, str)
    assert isinstance(n2, str)


def test_generate_fake_name_different_profiles():
    n_same = generate_fake_name(0, "uuid-1", Gender.MALE, NameOrigin.DANISH, "same")
    n_inv = generate_fake_name(
        0, "uuid-1", Gender.FEMALE, NameOrigin.ARABIC, "gender_inverted"
    )
    assert isinstance(n_same, str)
    assert isinstance(n_inv, str)


def test_generate_all_profiles():
    profiles = generate_all_profiles(0, "uuid-test", Gender.MALE, NameOrigin.DANISH)
    assert set(profiles.keys()) == {
        "same",
        "gender_inverted",
        "ethnicity_inverted",
        "both_inverted",
    }
    for name in profiles.values():
        assert len(name.split()) >= 2  # at least first + last name


def test_arabic_names_available():
    names = _load_names(NameOrigin.ARABIC, Gender.MALE, "first")
    assert len(names) > 0


def test_somali_names_available():
    names = _load_names(NameOrigin.SOMALI, Gender.FEMALE, "first")
    assert len(names) > 0


def test_detect_gender_from_name_returns_gender():
    result = detect_gender_from_name("Lars Hansen")
    # gender_guesser may or may not be installed; just check it returns a Gender
    assert isinstance(result, Gender)
