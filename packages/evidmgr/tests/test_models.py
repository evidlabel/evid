"""Tests for evidmgr.models."""

from evidmgr.models import (
    AnonMode,
    Document,
    EvidenceSet,
    Gender,
    NameOrigin,
    SetType,
    make_seed,
    seeded_rng,
)
from pathlib import Path
from datetime import datetime, timezone


def test_enums_have_expected_values():
    assert SetType.NORMAL == "normal"
    assert SetType.ANON == "anon"
    assert AnonMode.REAL == "real"
    assert AnonMode.PLACEHOLDER == "placeholder"
    assert AnonMode.FAKE == "fake"
    assert Gender.MALE == "male"
    assert NameOrigin.DANISH == "danish"


def test_evidence_set_defaults():
    es = EvidenceSet(
        name="Test",
        slug="test",
        path=Path("/tmp/test"),
        set_type=SetType.NORMAL,
        created=datetime.now(tz=timezone.utc),
    )
    assert es.description == ""
    assert es.anon_language == "da"


def test_document_defaults():
    doc = Document(
        uuid="abc",
        path=Path("/tmp"),
        label="Test",
        tags=[],
        added=datetime.now(tz=timezone.utc),
    )
    assert not doc.indexed
    assert not doc.anon_pending
    assert doc.notes == ""


def test_make_seed_deterministic():
    s1 = make_seed("uuid-1", 0, "same")
    s2 = make_seed("uuid-1", 0, "same")
    s3 = make_seed("uuid-1", 1, "same")
    assert s1 == s2
    assert s1 != s3


def test_seeded_rng_reproducible():
    r1 = seeded_rng("uuid-1", 0, "gender_inverted")
    r2 = seeded_rng("uuid-1", 0, "gender_inverted")
    assert r1.random() == r2.random()
