"""Tests for evidmgr.models."""

from datetime import UTC, datetime
from pathlib import Path

from evid.models import (
    Document,
    EvidenceSet,
    SetType,
)


def test_enums_have_expected_values():
    assert SetType.NORMAL == "normal"


def test_evidence_set_defaults():
    es = EvidenceSet(
        name="Test",
        slug="test",
        path=Path("/tmp/test"),
        set_type=SetType.NORMAL,
        created=datetime.now(tz=UTC),
    )
    assert es.description == ""


def test_document_defaults():
    doc = Document(
        uuid="abc",
        path=Path("/tmp"),
        label="Test",
        tags=[],
        added=datetime.now(tz=UTC),
    )
    assert not doc.indexed
    assert doc.notes == ""
